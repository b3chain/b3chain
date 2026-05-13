# Tutorial — Why the dual-hash architecture is a real architectural risk

## The problem in one sentence
B3Chain uses **two different hash functions** for two purposes — SHA-256d
for block IDs (so external tools and explorers stay compatible) and
BLAKE3d for the proof-of-work check — and confusing them is a
catastrophic, silent failure.

## The theory

Every block has two hashes:

```
GetHash()    -> SHA-256d(serialized header)    # used as block id, txid lookup, merkle leaf
GetPoWHash() -> BLAKE3d(serialized header)     # used by ContextualCheckProofOfWork
```

A miner's job is to find a header with `GetPoWHash() <= target`. The
network's job is to verify that property. If `ContextualCheckProofOfWork`
ever calls `GetHash()` instead of `GetPoWHash()`:

- Block IDs are usually well below the target (because SHA-256 outputs
  are uniform 32-byte numbers, just like BLAKE3 outputs).
- So almost any block submitted to such a buggy node would pass PoW
  validation — including blocks with no actual mining work behind them.
- Result: the chain's PoW security collapses to "whatever the easiest
  way to find a low SHA-256 hash is", which is effectively zero on
  modern CPUs.

## Hands-on demo

```bash
python3 contrib/testing/audit/audit-pow-isolation.py
```

This audit does two things:

1. **Static grep** over every `GetHash()` and `GetPoWHash()` call site in
   `src/`, classifying each one as "PoW context" or "ID context" and
   flagging mismatches.
2. **Functional test**: constructs a header where SHA-256d ≤ target but
   BLAKE3d > target, submits it to a regtest node, expects rejection.
   Then the inverse.

## Exercise

In `src/validation.cpp`, locate `ContextualCheckProofOfWork` (or
`CheckProofOfWork` depending on the call path). Replace the call to
`GetPoWHash()` with `GetHash()`. Rebuild, re-run the audit:

```cpp
// Before
if (!CheckProofOfWork(block.GetPoWHash(), block.nBits, params)) ...
// After (catastrophic)
if (!CheckProofOfWork(block.GetHash(), block.nBits, params)) ...
```

Expected new output:

```
  FAIL  [H-1] static audit found PoW check using GetHash (line N of validation.cpp)
  FAIL  [H-1] header with SHA256d-only PoW accepted by regtest node
AUDIT RESULT: FAIL  [H-1]
```

## Why "looks fine in CI" doesn't help

Most unit tests work with regtest, where `nBits` is set very low and
both hashes pass anyway. The bug only manifests in production once a
real attacker notices it. That's exactly why this audit runs the
contradiction check — a header that satisfies one hash function but not
the other — rather than relying on "did the node accept the block?".

## Further reading

- BIP-141 SegWit txid vs wtxid (similar dual-identity pattern):
  github.com/bitcoin/bips/blob/master/bip-0141.mediawiki
- The original BCH split confused some mining hardware about which
  difficulty algorithm to use; this is the same class of bug at the
  hash-function level.
