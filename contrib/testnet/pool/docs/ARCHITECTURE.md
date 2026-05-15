# B3Chain Pool — Architecture

Three Node.js services + one Postgres + one b3chaind. The pool is an
overlay — it never modifies consensus rules.

```
miners ───►  b3chain-pool-stratum (TCP :3333)
                │
                ▼  share events  (UNIX domain socket)
            b3chain-pool-daemon
                │   ▲
            shares  job templates
                ▼   │
              ┌─ Postgres
              │
              └─► b3chain-pool-web (HTTP :5100, behind nginx)
                      ▲
                      │  websocket pushes (Socket.IO /me + /)
                      ▼
                    browsers
```

Each box's responsibility:

| Service | Owns | Talks to |
|---|---|---|
| `b3chain-pool-stratum` | Per-connection TCP state, vardiff, share validation, in-memory job cache | b3chaind RPC (getblocktemplate, submitblock), pool daemon over UNIX sock |
| `b3chain-pool-daemon`  | Persistent share + block + balance ledger, PPLNS, payout job | Postgres, b3chaind RPC (getblock, sendmany) |
| `b3chain-pool-web`     | HTTP UI, auth, dashboards, live Socket.IO pushes | Postgres (read-mostly), b3chaind RPC (validateaddress) |

Why three processes? They each have very different failure modes (a slow
SQL query must not stall stratum; a stratum crash must not lose blocks).
Restarting any one of them does not lose accepted shares because:

- Accepted shares are queued in-memory and re-sent over IPC when the
  daemon comes back; the daemon batches inserts in a small in-process
  queue with at-least-once semantics.
- The block-confirmer is idempotent: it works off `blocks` table state,
  re-reads `getblock` on every tick, and PPLNS will only run once per
  block (`pplns_credited` flag).
- The hourly payout job locks the candidate user set in a single
  transaction; an interrupted `sendmany` cannot double-debit a user
  because the balance debit is in the same DB transaction as the
  `payouts` row. If `sendmany` itself was sent but the daemon crashed
  before the DB commit, the operator must use `recompute-pplns.ts` /
  `pay-now.ts` to reconcile.
