# B3Chain Stratum / Pool Implementer Guide

This document is the **authoritative reference for pool software, share
validators, and any non-node code that needs to compute or verify B3Chain
proof-of-work**. Node operators and solo miners should also read
[`doc/mining.md`](mining.md) for the wider RPC workflow and the bundled
reference CPU miner; this file is the narrow contract that everything
mining-adjacent must agree on.

It contains three things, and only three things:

1. How pools (and any external miner) compute the PoW hash.
2. Test vectors for verifying a BLAKE3 implementation byte-for-byte.
3. A reference to the official BLAKE3 specification.

If your implementation matches every test vector here, your shares and
blocks will be accepted by `b3chaind`. If it does not, they will not.

---

## 1. How pools compute the PoW hash

B3Chain replaces Bitcoin's `SHA256d` proof-of-work with **double
BLAKE3-256**:

```
PoW_hash = BLAKE3(BLAKE3(block_header))
```

`block_header` is the standard 80-byte serialized header — identical
layout to Bitcoin, identical endianness, identical fields:

| Field           | Size     | Encoding              |
|-----------------|----------|-----------------------|
| nVersion        | 4 bytes  | int32, little-endian  |
| hashPrevBlock   | 32 bytes | uint256, little-endian|
| hashMerkleRoot  | 32 bytes | uint256, little-endian|
| nTime           | 4 bytes  | uint32, little-endian |
| nBits           | 4 bytes  | uint32, little-endian |
| nNonce          | 4 bytes  | uint32, little-endian |

**Critical:** *Only the proof-of-work hash changes.* Block ID hashes,
txids, the merkle tree, and the witness merkle root all still use
`SHA256d`. This means:

| Hash                             | Algorithm |
|----------------------------------|-----------|
| `block.GetPoWHash()`             | BLAKE3d   |
| `block.GetHash()` (block ID)     | SHA256d   |
| `tx.GetHash()` (txid)            | SHA256d   |
| `tx.GetWitnessHash()` (wtxid)    | SHA256d   |
| Merkle root / witness merkle root| SHA256d   |
| `getblocktemplate` "target"      | nBits→target (compact, identical to Bitcoin) |

### Share validation

A pool validates a share by checking, in **little-endian integer**
comparison:

```
int_le(BLAKE3(BLAKE3(header))) <= share_target
```

`share_target` is a pool-side per-worker target, always less restrictive
than (numerically greater than or equal to) the network target derived
from `nBits`.

### Block submission

When `int_le(BLAKE3(BLAKE3(header))) <= block_target`, submit the block
via the node's `submitblock` RPC. The node revalidates with
`CheckProofOfWork(block.GetPoWHash(), block.nBits, ...)` — implemented
in [`src/validation.cpp`](../src/validation.cpp) — and rejects anything
that fails.

### Extranonce / coinbase

Extranonce handling in the coinbase scriptSig is identical to Bitcoin.
Only the final 80-byte-header hash computation differs. Standard
Stratum v1 `mining.notify` / `mining.submit` framing applies.

### Default ports

| Network | P2P Port | RPC Port |
|---------|----------|----------|
| Mainnet | 8533     | 8534     |
| Testnet | 18533    | 18534    |
| Regtest | 18544    | 18545    |

### End-to-end pseudocode

```python
import blake3, struct

def double_blake3(header_bytes: bytes) -> bytes:
    return blake3.blake3(blake3.blake3(header_bytes).digest()).digest()

def meets_target(header_bytes: bytes, target: int) -> bool:
    return int.from_bytes(double_blake3(header_bytes), 'little') <= target
```

A complete reference miner using this exact computation is at
[`contrib/miner/b3chain-cpuminer.py`](../contrib/miner/b3chain-cpuminer.py).

---

## 2. Test vectors

Implementations **MUST** reproduce every value below bit-for-bit before
being trusted with mainnet shares.

All hashes are shown in **big-endian display format** (most significant
byte first) — the same convention used by `bitcoin-cli`, block
explorers, and the BLAKE3 reference implementation. Bytes in memory and
on the wire are little-endian for header fields.

### 2.1 Single BLAKE3-256

```
BLAKE3("")        = af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262
BLAKE3("b3chain") = 492530272073ef2fb434ca4d9492bcea09502b24642b7e04021892bdda2aa806
```

### 2.2 Double BLAKE3-256 (the PoW primitive)

```
BLAKE3(BLAKE3(""))        = 82878ed8a480ee41775636820e05a934ca5c747223ca64306658ee5982e6c227
BLAKE3(BLAKE3("b3chain")) = f09be63a21ff0bc5646b5ddcadef1c43f8e0e47815793cff909cab0a345396d3
```

### 2.3 Full 80-byte block-header vectors

The point of these is to exercise the *exact* serialization a pool will
hash in production.

**Vector A — 80 zero bytes:**

```
Header (hex):  00000000 00000000000000000000000000000000000000000000000000000000000000000000
               00000000000000000000000000000000000000000000000000000000000000000000 00000000
               00000000 00000000
PoW hash:      fb6d63b21d8c9f215de0e4fd9f4d0e7ed53ff023c7243e76f5a7367b2a4507b6
ID hash:       14508459b221041eab257d2baaa7459775ba748246c8403609eb708f0e57e74b
```

**Vector B — version=1, rest zeros:**

```
Header (hex):  01000000 00...00 (version=1 LE in first 4 bytes, then 76 zero bytes)
PoW hash:      a8b60a455b3576a701ed73ad8ebf838839917a0331bfb6dfa99b77641c858c61
ID hash:       4ddd9f0855d58a375be5a763e5f51ece853d30525fcd9a3e477c2194fedb549f
```

> "PoW hash" is `BLAKE3(BLAKE3(header))`.
> "ID hash"  is `SHA256(SHA256(header))` — what `b3chaind` returns as
> the block hash. They are intentionally different.

### 2.4 Verifying your implementation

The repository ships a Python script that hashes any header and
cross-checks against a running daemon:

```
contrib/testing/verify-blake3-pow.py
```

The same hashing helpers are used by the functional test framework
(`test/functional/test_framework/messages.py::pow_hash_int`) and by the
reference miner, so passing this script's checks means your code agrees
with consensus.

---

## 3. References

- **BLAKE3 specification** (canonical): O'Connor, Aumasson, Neves,
  Wilcox-O'Hearn, *"BLAKE3: one function, fast everywhere"*,
  <https://github.com/BLAKE3-team/BLAKE3-specs/blob/master/blake3.pdf>.
- **BLAKE3 reference implementation** (Rust + C):
  <https://github.com/BLAKE3-team/BLAKE3>.
- **B3Chain PoW design rationale**:
  [`doc/b3chain-pow-design.md`](b3chain-pow-design.md).
- **B3Chain mining workflow & reference CPU miner**:
  [`doc/mining.md`](mining.md).
- **`getblocktemplate` (BIP 22 / 23)**:
  <https://github.com/bitcoin/bips/blob/master/bip-0022.mediawiki>,
  <https://github.com/bitcoin/bips/blob/master/bip-0023.mediawiki>.
- **Stratum v1** (de-facto, no formal RFC):
  <https://reference.cash/mining/stratum-protocol> (community spec; the
  hash-algorithm substitution above is the only B3Chain deviation).
