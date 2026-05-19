# B3Chain Stratum / Pool Implementer Guide

This document is the **authoritative reference for pool software, share
validators, and any non-node code that needs to compute or verify B3Chain
proof-of-work**. Node operators and solo miners should also read
[`doc/mining.md`](mining.md) for the wider RPC workflow and the bundled
reference CPU miner; this file is the narrow contract that everything
mining-adjacent must agree on.

It contains four things:

1. The PoW algorithm in use (and where its normative spec lives).
2. How pools compute the PoW hash from a share submission.
3. Test vectors for verifying an implementation byte-for-byte.
4. Implementation pointers for in-tree reference code.

If your implementation matches every test vector here and reproduces
the byte-exact output of the reference, your shares and blocks will be
accepted by `b3chaind`. If it does not, they will not.

---

## 1. PoW algorithm in use

| Field | Value |
|---|---|
| Algorithm | **B3PoW-Scratch v1.1** |
| `SPEC_VERSION` | `0x00010101` (1.1.1, F-1 fix) |
| Primitive | BLAKE3 (full + 2-round reduced) |
| Working set | 1 MiB scratchpad, 8 lanes × 128 KiB |
| Iterations | 2 048 read-modify-write rounds per hash |
| Spec | [`contrib/miner/b3miner-rtl/SPEC.md`](../contrib/miner/b3miner-rtl/SPEC.md) |
| Python reference | [`contrib/miner/b3miner-rtl/ref/b3pow_ref.py`](../contrib/miner/b3miner-rtl/ref/b3pow_ref.py) |
| C++ consensus | [`src/crypto/b3pow_scratch.cpp`](../src/crypto/b3pow_scratch.cpp) |
| TypeScript port (pool) | [`contrib/testnet/pool/src/lib/b3pow-scratch.ts`](../contrib/testnet/pool/src/lib/b3pow-scratch.ts) |
| Consensus vectors | [`src/test/data/b3pow_consensus_vectors.json`](../src/test/data/b3pow_consensus_vectors.json) |
| End-to-end verifier | [`contrib/testing/verify-b3pow.py`](../contrib/testing/verify-b3pow.py) |

> **The pool validates shares with the canonical B3PoW-Scratch v1.1
> algorithm exactly as the consensus code does**, including the
> per-parent scratchpad cache pattern.

---

## 2. How pools compute the PoW hash

```
PoW_hash = b3pow_scratch( header, prev_block_hash )
```

`header` is the standard 80-byte serialized block header — identical
layout to Bitcoin, identical endianness, identical fields:

| Field           | Size     | Encoding              |
|-----------------|----------|-----------------------|
| nVersion        | 4 bytes  | int32, little-endian  |
| hashPrevBlock   | 32 bytes | uint256, little-endian|
| hashMerkleRoot  | 32 bytes | uint256, little-endian|
| nTime           | 4 bytes  | uint32, little-endian |
| nBits           | 4 bytes  | uint32, little-endian |
| nNonce          | 4 bytes  | uint32, little-endian |

`prev_block_hash` is the 32-byte SHA-256d block-identity hash of the
parent block, **as raw little-endian bytes** (i.e. the same value that
appears in `hashPrevBlock` inside the header). Pools receive it
big-endian from `getblocktemplate`'s `previousblockhash` field;
byte-reverse before feeding it to `b3pow_scratch`.

**Critical:** *Only the proof-of-work hash differs from Bitcoin.* Block
ID hashes, txids, the merkle tree, and the witness merkle root all
still use `SHA256d`. This means:

| Hash                              | Algorithm |
|-----------------------------------|-----------|
| `block.GetPoWHash(prev, pad, …)`  | B3PoW-Scratch v1.1 |
| `block.GetHash()` (block ID)      | SHA-256d  |
| `tx.GetHash()` (txid)             | SHA-256d  |
| `tx.GetWitnessHash()` (wtxid)     | SHA-256d  |
| Merkle root / witness merkle root | SHA-256d  |
| `getblocktemplate` "target"       | nBits→target (compact, identical to Bitcoin) |

### 2.1 Scratchpad caching

`b3pow_scratch` begins by filling a 1 MiB scratchpad from
`BLAKE3-XOF(prev_block_hash || i)`. The pad depends only on
`prev_block_hash`, so a pool's share validator **must** maintain a
per-parent cache (e.g. an LRU keyed by `previousblockhash`) and reuse
the pad across every share for the same job:

```
pad = pad_cache.get_or_init(prev_block_hash, init_scratchpad)
pow = b3pow_scratch(header, prev_block_hash, pad=pad).pow_hash
```

Without caching, a validator pays a 1 MiB BLAKE3-XOF init (~10 ms on
a modern CPU) on every share, which scales catastrophically. The
reference pool's TS port enforces this pattern in
[`contrib/testnet/pool/src/lib/pad-cache.ts`](../contrib/testnet/pool/src/lib/pad-cache.ts).

### 2.2 Share validation

A pool validates a share by checking, in **little-endian integer**
comparison:

```
int_le( b3pow_scratch(header, prev) ) <= share_target
```

`share_target` is a pool-side per-worker target, always less restrictive
than (numerically greater than or equal to) the network target derived
from `nBits`.

### 2.3 Block submission

When `int_le( b3pow_scratch(header, prev) ) <= block_target`, submit
the block via the node's `submitblock` RPC. The node revalidates with
`CheckProofOfWork(block.GetPoWHash(prev, pad, …), block.nBits, …)` —
implemented in [`src/validation.cpp`](../src/validation.cpp) — and
rejects anything that fails.

### 2.4 Extranonce / coinbase

Extranonce handling in the coinbase scriptSig is identical to Bitcoin.
Only the final 80-byte-header hash computation differs. Standard
Stratum v1 `mining.notify` / `mining.submit` framing applies. Pools
that built share validators for double-BLAKE3 only need to swap the
hash function call — the `notify`/`submit` shape, extranonce, and
merkle-branch logic are unchanged.

### 2.5 Default ports

| Network | P2P Port | RPC Port |
|---------|----------|----------|
| Mainnet | 8533     | 8534     |
| Testnet | 18533    | 18534    |
| Regtest | 18544    | 18545    |

### 2.6 End-to-end pseudocode

```python
import struct, sys
sys.path.insert(0, 'contrib/miner/b3miner-rtl/ref')
from b3pow_ref import b3pow_scratch, init_scratchpad, nbits_to_target

pad_cache: dict[bytes, bytearray] = {}

def get_pad(prev_le: bytes) -> bytearray:
    p = pad_cache.get(prev_le)
    if p is None:
        p = init_scratchpad(prev_le)
        pad_cache[prev_le] = p
    return p

def meets_target(header: bytes, prev_le: bytes, target: int) -> bool:
    pad = get_pad(prev_le)
    pow_hash = b3pow_scratch(header, prev_le, pad=pad).pow_hash
    return int.from_bytes(pow_hash, 'little') <= target
```

`prev_le` is `bytes.fromhex(previousblockhash)[::-1]`, i.e. the raw
little-endian parent ID as it appears inside the header.

A complete reference miner using this exact computation is at
[`contrib/miner/b3chain-cpuminer.py`](../contrib/miner/b3chain-cpuminer.py).

---

## 3. Test vectors

Implementations **MUST** reproduce every value below bit-for-bit before
being trusted with mainnet shares.

The canonical, machine-readable vectors live at
[`src/test/data/b3pow_consensus_vectors.json`](../src/test/data/b3pow_consensus_vectors.json)
and ship with `schema_version = 1` and `spec_version = "0x00010101"`.
Each entry contains `header_hex`, `prev_block_hash_hex`,
`expected_pow_hash_hex`, `nbits_hex`, and `expected_check_pow`.
[`contrib/testing/verify-b3pow.py`](../contrib/testing/verify-b3pow.py)
re-derives every entry from the Python reference and (optionally,
with `--rpc-port`) re-derives every recent block on a live node.

All hashes are stored in **little-endian** bytes (wire / memory
convention). When displayed to humans (block explorers, `b3chain-cli`,
test-vector comments) the convention is **big-endian display hex**
(most significant byte first) — that's the byte-reverse of the wire
form.

### 3.1 BLAKE3 primitive (sanity)

```
BLAKE3("")        = af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262
BLAKE3("b3chain") = 492530272073ef2fb434ca4d9492bcea09502b24642b7e04021892bdda2aa806
```

These are the unmodified BLAKE3 outputs and only verify that your
primitive matches the reference; they do **not** validate
B3PoW-Scratch.

### 3.2 B3PoW-Scratch end-to-end

The full set of header→pow-hash mappings lives in
[`b3pow_consensus_vectors.json`](../src/test/data/b3pow_consensus_vectors.json).
Two representative entries:

**Vector `zero_header`** — 80 zero bytes, 32 zero bytes parent:

```
header_hex            : 00 × 80
prev_block_hash_hex   : 00 × 32
expected_pow_hash_hex : (see JSON entry, schema_version=1)
```

**Vector `version1`** — version=1, rest zeros:

```
header_hex            : 01000000 00 × 76
prev_block_hash_hex   : 00 × 32
expected_pow_hash_hex : (see JSON entry, schema_version=1)
```

> Inline hex values are intentionally omitted to prevent stale copies
> from drifting away from the JSON ground truth. Always re-derive
> against `b3pow_consensus_vectors.json`.

### 3.3 Verifying your implementation

The repository ships a verifier that imports the Python reference and
checks every JSON entry, plus (optionally) live block PoW from a node:

```
pip3 install blake3
python3 contrib/testing/verify-b3pow.py                  # vectors only
python3 contrib/testing/verify-b3pow.py --rpc-port=18545 # + live blocks
```

The same Python reference is used by:

- The functional test framework
  (`test/functional/test_framework/messages.py`).
- The reference CPU miner
  (`contrib/miner/b3chain-cpuminer.py`).
- The RTL parity tests in
  (`contrib/miner/b3miner-rtl/ref/tests/`).
- The pool's TypeScript port parity test in
  (`contrib/testnet/pool/test/b3pow-scratch.spec.ts`).

So passing the verifier means your code agrees with consensus, RTL,
and the production pool.

### 3.4 Legacy BLAKE3d vectors

The retired double-BLAKE3 PoW (used in early dev builds before
B3PoW-Scratch landed) has its vectors at
[`contrib/testing/verify-blake3-pow.py`](../contrib/testing/verify-blake3-pow.py).
They are kept only so historical headers can be regenerated for tooling
tests — **they do not validate any current or future B3Chain block**.
New code should not consume them.

---

## 4. References

- **B3PoW-Scratch v1.1 specification** (normative):
  [`contrib/miner/b3miner-rtl/SPEC.md`](../contrib/miner/b3miner-rtl/SPEC.md).
- **B3Chain PoW design rationale**:
  [`doc/b3chain-pow-design.md`](b3chain-pow-design.md).
- **B3Chain mining workflow & reference CPU miner**:
  [`doc/mining.md`](mining.md).
- **BLAKE3 specification** (canonical): O'Connor, Aumasson, Neves,
  Wilcox-O'Hearn, *"BLAKE3: one function, fast everywhere"*,
  <https://github.com/BLAKE3-team/BLAKE3-specs/blob/master/blake3.pdf>.
- **BLAKE3 reference implementation** (Rust + C):
  <https://github.com/BLAKE3-team/BLAKE3>.
- **`getblocktemplate` (BIP 22 / 23)**:
  <https://github.com/bitcoin/bips/blob/master/bip-0022.mediawiki>,
  <https://github.com/bitcoin/bips/blob/master/bip-0023.mediawiki>.
- **Stratum v1** (de-facto, no formal RFC):
  <https://reference.cash/mining/stratum-protocol>. The only B3Chain
  deviations from this spec are (a) the hash-algorithm substitution
  above and (b) the requirement that share validators carry a
  per-parent scratchpad cache.
