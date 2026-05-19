# Tutorial - Why the dual-hash architecture is a real architectural risk

## The problem in one sentence

B3Chain uses **two different hash functions** for two purposes - SHA-256d
for block IDs (so external tools and explorers stay compatible) and
**B3PoW-Scratch v1.1** (a memory-hard BLAKE3 variant with a 1 MB
scratchpad) for the proof-of-work check - and confusing them is a
catastrophic, silent failure.

The authoritative algorithm spec lives at
[`contrib/miner/b3miner-rtl/SPEC.md`](../../../miner/b3miner-rtl/SPEC.md).

## The theory

Every block has two hashes:

```
GetHash()    -> SHA-256d(serialized header)              # block id, txid lookup, merkle leaf
GetPoWHash() -> B3PoW-Scratch(header, prev_block_hash)   # ContextualCheckProofOfWork only
```

A miner's job is to find a header with `GetPoWHash() <= target`. The
network's job is to verify that property. If `ContextualCheckProofOfWork`
ever calls `GetHash()` instead of `GetPoWHash()`:

- Block IDs are usually well below the target (SHA-256 outputs are
  uniform 32-byte numbers, much like any modern cryptographic hash).
- So almost any block submitted to such a buggy node would pass PoW
  validation - including blocks with no actual mining work behind
  them.
- Result: the chain's PoW security collapses to "whatever the easiest
  way to find a low SHA-256 hash is", which is effectively zero on
  modern CPUs.

The B3PoW-Scratch v1.1 swap *strengthens* this property because the
PoW hash is now memory-hard (1 MB scratchpad, 8 lanes, 2048
iterations), which makes commodity SHA-256 ASICs entirely useless for
attacking the chain even if the dual-hash design *were* compromised.

## Hands-on demo

```bash
python3 contrib/testing/audit/audit-b3pow-isolation.py
```

This audit does six things:

1. **Static grep [H-1]**: every `CheckProofOfWork(...)` call site in
   `src/` must pass a value derived from `GetPoWHash()` (or an
   already-computed `pow_hash`), never `GetHash()`.
2. **Static grep [H-1]**: `src/primitives/block.cpp` must include
   `<crypto/b3pow_scratch.h>` so the PoW path uses the B3PoW port and
   not bare BLAKE3.
3. **Static grep [H-1]**: `CBlockHeader::GetPoWHash(...)` must use the
   v1.1 4-argument signature (`prev_block_hash`, `pad`, `budget`,
   `out_exceeded`).
4. **Static grep [H-1.1]**: `BlockValidationResult::BLOCK_POW_BUDGET`
   must route to `Misbehaving("b3pow-budget-exceeded")` in
   `src/net_processing.cpp`.
5. **Static grep [H-1.2]**: `ChainstateManager` must own a
   `b3pow::Cache m_b3pow_cache` (the per-`prev_block_hash` LRU
   scratchpad cache).
6. **Static grep [H-1.3]**: `MAX_B3POW_VERIFY_PER_BATCH` must cap the
   number of headers verified per HEADERS message.

Then it runs a **functional check**: spin up a regtest node, mine one
block, fetch the header back, and verify:

- `getblockhash()` equals SHA-256d of the serialized header (block
  identity stays SHA-256d).
- `b3pow_ref.b3pow_scratch(header, prev_block_hash).pow_hash` differs
  from the block ID (the two algorithms are independent).
- The B3PoW hash satisfies the `nBits` target (mining actually
  searched the right space).

## Exercise

In `src/validation.cpp`, locate `CheckBlockHeaderPoW`. Replace the call
to `header.GetPoWHash(prev_block_hash, ...)` with the SHA-256d block
ID (`header.GetHash()`):

```cpp
// Before
auto pow_opt = header.GetPoWHash(prev_block_hash, pad, budget, exceeded);
// After (catastrophic)
auto pow_opt = std::optional<uint256>{header.GetHash()};
```

Rebuild, re-run the audit:

```
  FAIL  [H-1] CheckProofOfWork call at src/pow.cpp:NN uses GetHash
  FAIL  [H-1] block ID and B3PoW hash are different
AUDIT RESULT: FAIL  [H-1]
```

## Why "looks fine in CI" doesn't help

Most unit tests run on regtest where `nBits` is set very loose
(`0x207fffff`) so both hashes pass anyway. The bug only manifests in
production. That's exactly why this audit cross-checks the two
algorithms against a freshly mined header rather than relying on "did
the node accept the block?".

## Further reading

- [`contrib/miner/b3miner-rtl/SPEC.md`](../../../miner/b3miner-rtl/SPEC.md)
  - normative B3PoW-Scratch v1.1 algorithm spec.
- [`contrib/miner/b3miner-rtl/ref/b3pow_ref.py`](../../../miner/b3miner-rtl/ref/b3pow_ref.py)
  - byte-for-byte Python reference (the audit imports this).
- [`src/test/data/b3pow_consensus_vectors.json`](../../../../src/test/data/b3pow_consensus_vectors.json)
  - canonical consensus vectors the C++ port must agree with.
- BIP-141 SegWit txid vs wtxid (similar dual-identity pattern):
  github.com/bitcoin/bips/blob/master/bip-0141.mediawiki.
