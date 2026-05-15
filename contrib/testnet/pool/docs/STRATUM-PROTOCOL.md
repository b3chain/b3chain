# Stratum V1 — B3Chain BLAKE3 specifics

The pool implements the standard 5-method Stratum V1 protocol. The only
difference from a Bitcoin pool is the proof-of-work hash and the
network-target check.

| Method | Direction | Notes |
|---|---|---|
| `mining.subscribe` | client → server | Returns `[[["mining.set_difficulty", subId], ["mining.notify", subId]], extranonce1, extranonce2_size]`. extranonce1 is 4 bytes, extranonce2 is 4 bytes. |
| `mining.authorize` | client → server | Username is `<email>.<workerName>`. Password is ignored. Anonymous shares are accepted but skipped from per-user accounting. |
| `mining.set_difficulty` | server → client | Pushed once after subscribe and on every vardiff retune. |
| `mining.notify` | server → client | Pushed on every new block template. `clean_jobs=true` invalidates older jobs. |
| `mining.submit` | client → server | Validated against (a) the connection's current share target derived from `mining.set_difficulty`, and (b) the network target from the active block template. |
| `mining.extranonce.subscribe` | client → server | Accepted, no-op. Required by some miners. |
| `mining.suggest_difficulty` | client → server | Accepted; the server clamps the request to `[minDiff, maxDiff]`. |

## Share validation

For each `mining.submit`:

1. Reassemble the 80-byte block header by:
   - Concatenating `coinb1 || extranonce1 || extranonce2 || coinb2`
     (this is the full coinbase tx).
   - Computing the coinbase txid as `SHA256(SHA256(coinbase))`.
   - Folding the merkle branches into the merkle root using
     `SHA256(SHA256(left || right))` at each level.
   - Filling in `version`, `prevhash`, `merkle_root`, `ntime`, `nbits`,
     `nonce` (all little-endian on the wire).
2. Compute `powHash = BLAKE3(BLAKE3(header))`.
   - This is the same primitive used by `b3chaind`'s consensus path —
     see `src/primitives/block.cpp:CBlockHeader::GetPoWHash()` and the
     reference `contrib/miner/b3chain-cpuminer.py`.
3. If `powHash <= shareTarget`, the share is accepted; otherwise
   rejected as `low difficulty`.
4. If `powHash <= networkTarget`, the share is also a block — submit
   the full serialized block to `b3chaind` via `submitblock` and (on
   success) record it in the `blocks` table.

Because the share hash and the block-validity hash are the same primitive,
shares that meet the network target *always* become valid blocks
(assuming the rest of the block — txns, BIP141 commitment — was built
from `getblocktemplate`).

## Vardiff

Each connection starts at `B3POOL_STRATUM_DEFAULT_DIFF`. Every
`B3POOL_STRATUM_VARDIFF_RETUNE_S` seconds the server measures the
average inter-share interval over that window and adjusts the target
multiplicatively to converge on `B3POOL_STRATUM_VARDIFF_TARGET_S`. The
single-step ratio is clamped to ≤ 4× and ≥ 0.25× per retune so a brief
hash spike doesn't overshoot. A new `mining.set_difficulty` is pushed
to the client whenever the change is ≥ 10%.

## Test vectors

`b3chain/doc/mining.md` lists BLAKE3 test vectors that
`tests/share-validator.test.ts` re-verifies on every test run.
