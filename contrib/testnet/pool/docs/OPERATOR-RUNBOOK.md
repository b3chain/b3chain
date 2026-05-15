# Operator runbook

Quick reference for the most common b3chain-pool incidents. Every
command should be run on seed1 as `root` (or `deploy` with sudo).

## Health overview

```bash
systemctl status 'b3chain-pool-*'
journalctl -u b3chain-pool-stratum -n 100 --no-pager
journalctl -u b3chain-pool-daemon  -n 100 --no-pager
journalctl -u b3chain-pool-web     -n 100 --no-pager
curl -s 127.0.0.1:5100/metrics | grep -E '^b3chain_pool_'
```

The `/metrics` endpoint is unauthenticated on localhost so it can be
scraped by Prometheus without credentials. Front it through nginx with
basic-auth before exposing publicly.

---

## "Pool is down"

Symptoms: miners disconnect, the landing page hashrate tile reads zero
for more than a few minutes.

1. Check the three services are running. If any failed, look at the
   journal for the immediate cause.
2. If `b3chain-pool-stratum` is up but accepting nothing:
   - Check `getblocktemplate` works:
     `b3chain-cli -testnet -rpcwallet=pool-payouts getblocktemplate '{"rules":["segwit"]}'`
   - If b3chaind is reorganising or syncing, miners get rejects. Wait
     it out.
3. If `b3chain-pool-daemon` is down, the IPC socket is gone — stratum
   keeps accepting and queues shares in memory (up to 5000) so a quick
   restart doesn't lose data.
4. Restart in this order: `daemon`, then `stratum`, then `web`.
   `systemctl restart b3chain-pool.target` does it for you.

---

## "A block I found was orphaned"

Confirmer logs `block orphaned`, the dashboard shows a red `orphan`
tag, and balances are unchanged.

This is normal — the pool tracks confirmation depth and only credits
PPLNS at 100 confirmations. If a block was credited and *then* orphaned
(only possible if `B3POOL_BLOCK_CONFIRMATIONS` were lowered or the
chain reorged > 100 deep), insert reversal balance entries by hand:

```sql
INSERT INTO balance_entries(user_id, block_id, delta_b3c, kind, description)
SELECT user_id, block_id, -delta_b3c, 'adjustment',
       'Reverse credit for orphaned block ' || block_id
  FROM balance_entries
 WHERE block_id = <ID>
   AND kind = 'credit';
```

---

## "User says their balance is wrong"

1. Reconstruct their ledger:
   ```sql
   SELECT created_at, kind, delta_b3c, description
     FROM balance_entries WHERE user_id = <UID>
     ORDER BY id;
   SELECT SUM(delta_b3c) FROM balance_entries WHERE user_id = <UID>;
   ```
2. Cross-check against the blocks they should have shared in:
   ```sql
   SELECT b.id, b.height, b.found_at, b.is_confirmed, b.pplns_credited
     FROM blocks b WHERE b.is_confirmed
     ORDER BY b.id DESC LIMIT 20;
   ```
3. If a block legitimately should have credited them but didn't (e.g.
   their `users.email` was added to the `shares` window after the fact),
   replay PPLNS for that block:
   ```bash
   sudo -u b3chain-pool -H bash -lc \
     'cd /usr/local/lib/b3chain-pool && npm run recompute-pplns -- 1234'
   ```
   The CLI deletes the previous credit entries for that block_id and
   re-runs `creditPplns()`.

---

## "Force a payout right now"

```bash
sudo -u b3chain-pool -H bash -lc \
  'cd /usr/local/lib/b3chain-pool && npm run pay-now'
```

Same logic as the hourly job: every user above their personal minimum
gets a `sendmany` line.

---

## "Stratum is rejecting all shares"

- Check `journalctl -u b3chain-pool-stratum -n 200 | grep -E 'reject|error'`.
- Most common: b3chaind is restarted and the new height invalidated old
  jobs. The job manager should re-poll every `B3POOL_TEMPLATE_POLL_MS`
  and broadcast a `cleanJobs=true` notify to all clients within 2 s.
- If the rejection is `low difficulty: invalid`, the coinbase split is
  wrong — likely a regression in `splitCoinbaseForExtranonce`. Bisect
  against `tests/share-validator.test.ts`.

---

## "Migrate the database"

```bash
sudo -u b3chain-pool -H bash -lc \
  'cd /usr/local/lib/b3chain-pool && npm run migrate'
```

The runner is idempotent — it tracks applied filenames in
`_migrations`. To force a re-run of one migration, `DELETE FROM
_migrations WHERE filename = '00X_*.sql'` first.
