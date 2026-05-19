# contrib/testnet/status-monitor/

Small Python 3 status exporter for the B3Chain public testnet. Polls
`b3chaind` RPC, the reference Stratum pool, and the faucet, and writes a
single `testnet-status.json` document that the public website
(`b3chain.org/testnet.html`) consumes for its live status panel.

| File                                | Purpose                                                |
|-------------------------------------|--------------------------------------------------------|
| `status-monitor.py`                 | Single-shot exporter — Python 3 stdlib only            |
| `config.example.ini`                | Example INI config (copy to `/etc/b3chain-status.conf`) |
| `systemd/b3chain-status.service`    | Oneshot service that runs the script                   |
| `systemd/b3chain-status.timer`      | Timer that fires the service every 60 s                |

## What it produces

A single JSON document at the path configured in `[output] path`
(default `/var/www/b3chain/testnet-status.json` on seed1, which nginx
serves as <https://b3chain.org/testnet-status.json>). Schema is
documented in [`doc/testnet-runbook.md`](../../../doc/testnet-runbook.md#10-live-status-monitor)
§10 and reproduced here for convenience:

```json
{
  "generated_at": "<ISO8601 UTC>",
  "chain": "test",
  "node": {
    "height": 12345,
    "best_block_hash": "...",
    "best_block_time": 1739200000,
    "difficulty": 1.0,
    "verification_progress": 1.0,
    "peer_count": 8
  },
  "network": {
    "hashrate_estimate_hps": 1234.5,
    "target_block_interval_s": 600,
    "actual_recent_interval_s": 612.4
  },
  "pool": {
    "url": "stratum+tcp://pool.b3chain.org:3333",
    "online": true,
    "connected_workers": 3,
    "hashrate_estimate_hps": 800.0,
    "blocks_found_24h": 4,
    "last_block_height": 12345
  },
  "faucet": {
    "online": true,
    "balance_satoshis": 5000000000,
    "address": null
  },
  "recent_blocks": [
    {"height": 12345, "hash": "...", "time": 1739200000, "tx_count": 1, "size_bytes": 280}
  ]
}
```

Every field is null-safe — if an upstream endpoint is down the
corresponding field is `null` rather than the whole document failing,
so the website's renderer can show "n/a" for one card without breaking
the others. The `generated_at` timestamp lets consumers detect a stale
file (treat anything older than 5 minutes as offline).

## Upstreams used

| Subtree | Source | Endpoint(s) |
|---|---|---|
| `node` / `network` / `recent_blocks` | `b3chaind` JSON-RPC | `getblockchaininfo`, `getnetworkinfo`, `getmininginfo`, `getblockhash`, `getblock` |
| `pool` | reference pool (`contrib/testnet/pool/`) | `127.0.0.1:3334/stats` (stratum), `127.0.0.1:5100/metrics` (web) |
| `faucet` | reference faucet (`contrib/testnet/faucet/app.py`) | `127.0.0.1:5000/status` |

The pool's `/stats` endpoint is defined in
[`contrib/testnet/pool/src/stratum/main.ts`](../pool/src/stratum/main.ts)
and the Prometheus `/metrics` endpoint in
[`contrib/testnet/pool/src/web/routes/metrics.ts`](../pool/src/web/routes/metrics.ts).
The faucet's `/status` endpoint is in
[`contrib/testnet/faucet/app.py`](../faucet/app.py).

**TODO (pool):** there is no aggregated "blocks_found_24h" field on
`/stats`; the exporter reads `b3chain_pool_blocks_24h` from the web
service's `/metrics` instead. If the web service is also down, that
field is `null`. A consolidated `pool/stats.json` would let us collapse
the two reads.

**TODO (faucet):** the faucet does not currently advertise its
hot-wallet address over `/status`, so `faucet.address` is always
`null`. Add `faucet_address` to the faucet's status payload to populate
it automatically.

## Install (seed1)

The script has no third-party Python dependencies. Just put it under
`/opt/`, copy the example config, and enable the timer.

```bash
sudo mkdir -p /opt/b3chain-status
sudo install -m 0755 status-monitor.py /opt/b3chain-status/

sudo cp config.example.ini /etc/b3chain-status.conf
sudo $EDITOR /etc/b3chain-status.conf      # set rpcpassword_file / endpoints
sudo chown root:root /etc/b3chain-status.conf
sudo chmod 0640 /etc/b3chain-status.conf

# Make sure the deploy user can write the output file. The default
# /var/www/b3chain is owned deploy:www-data with the setgid bit set
# already (see the git-push-policy.mdc website deploy notes).
ls -ld /var/www/b3chain    # should show "drwxrwsr-x deploy www-data"

sudo install -m 0644 systemd/b3chain-status.service /etc/systemd/system/
sudo install -m 0644 systemd/b3chain-status.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now b3chain-status.timer
```

Verify:

```bash
sudo systemctl list-timers b3chain-status.timer
sudo systemctl status b3chain-status.service --no-pager
sudo journalctl -u b3chain-status.service -n 20 --no-pager
cat /var/www/b3chain/testnet-status.json | head -n 40
curl -s https://b3chain.org/testnet-status.json | jq .generated_at
```

### Alternative: cron

If the operator prefers cron over systemd:

```
* * * * * deploy /usr/bin/python3 /opt/b3chain-status/status-monitor.py --config /etc/b3chain-status.conf >> /var/log/b3chain-status.log 2>&1
```

(Logging to a file under `/var/log` keeps `journalctl` clean. Make sure
the file exists and is writable: `sudo install -m 0644 -o deploy -g
deploy /dev/null /var/log/b3chain-status.log`.)

## Debugging locally

Run once and print to stdout — no file written, no privileges required
beyond reading the node's RPC cookie:

```bash
python3 status-monitor.py --config /tmp/test.conf --print --verbose
```

A minimal `/tmp/test.conf`:

```ini
[node]
rpcuser     = b3chain
rpcpassword = <YOUR_RPC_PASSWORD>

[pool]
stratum_stats_url =
web_metrics_url   =
public_url        = stratum+tcp://127.0.0.1:3333

[faucet]
status_url =

[output]
path = /tmp/testnet-status.json
```

(Empty `stratum_stats_url` / `web_metrics_url` / `faucet.status_url`
just leave those subtrees as their "offline" defaults — useful when
debugging from a workstation that does not have the pool / faucet
running locally.)

## Why Python stdlib only

We deliberately keep this script third-party-dependency-free so it
runs on every seed host (and on a debugging laptop) without needing a
virtualenv or pip install. The total surface area is ~300 lines.
`requests` would be slightly nicer than `urllib.request`, but is not
worth the install footprint.
