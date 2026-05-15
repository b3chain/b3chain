# PPLNS — Pay Per Last N Shares

The pool credits each confirmed block to its contributors in proportion
to their share-difficulty contribution to the most recent **N = 4032**
shares submitted at or before the block's `found_at` timestamp.

`N = 4032` was picked because B3Chain's retarget interval is 2016
blocks; 4032 covers the last two windows, smoothing across one full
retarget while still being short enough that a single attacker with a
big short-burst hashrate cannot game multiple retarget periods.

## Algorithm

Given:

- `R` = block reward in B3C
- `f` = pool fee fraction (default 0.01)
- `S` = the N most recent shares submitted at or before `block.found_at`
- `D_u` = sum of `share.diff` over shares in `S` belonging to user `u`
- `D = sum(D_u)` over all users in `S`

For each user `u`:

```
credit_u = (R * (1 - f)) * (D_u / D)
```

The pool fee `R * f` is recorded in `blocks.pool_fee_b3c`; the
distributable amount is partitioned across the contributors and inserted
as one `balance_entries` row per user (`kind = 'credit'`). The block row
is marked `pplns_credited = TRUE` so the credit cannot run twice.

## Worked example

```
R = 50.00 B3C, f = 0.01

Shares in window (after sorting by submitted_at DESC, LIMIT N):
  alice: D_alice = 800
  bob:   D_bob   = 200
  carol: D_carol = 1000
  total D        = 2000

distributable = 50 * 0.99 = 49.5

alice credit = 49.5 * 800 / 2000 = 19.80
bob   credit = 49.5 * 200 / 2000 =  4.95
carol credit = 49.5 * 1000/2000  = 24.75
pool_fee     =                    0.50
```

Hand-verified in `tests/pplns.test.ts`.

## Why PPLNS, not PPS or proportional

- **PPS (pay-per-share)**: the pool absorbs all variance — a great
  miner experience, but the pool needs a war chest to handle
  multi-week dry spells. Out of scope for an open-source community
  pool.
- **Proportional**: divides each block among contributors during that
  block's round (since the previous block). Vulnerable to "pool
  hopping" — miners switching to the pool just before a block is
  expected to land. PPLNS fixes this by always weighting the last N
  shares regardless of round boundaries.

## Edge cases

- **Block found with empty PPLNS window** (e.g. solo-mined regtest
  block with zero accepted shares): the entire reward is recorded in
  `pool_fee_b3c`, no balance entries written. The pool operator can
  manually credit via `recompute-pplns.ts`.
- **Block orphaned**: `block.is_orphan = TRUE`, `pplns_credited` is
  never set, no balance entries written. If credits had already been
  written (very rare, only if confirmation count regressed) operators
  can reverse them with a SQL `INSERT INTO balance_entries (..., kind
  = 'adjustment', ...)`.
- **Address invalid at payout time**: payout job skips the user and
  logs; no balance is debited. The user can fix the address from
  `/dashboard/settings` and the next payout cycle will pick them up.
