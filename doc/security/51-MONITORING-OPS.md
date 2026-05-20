# 51-attack monitoring — operator deployment guide

`contrib/monitoring/51attack-watch.py` is a long-running poller that
watches an operator-controlled `b3chaind` for every early-warning
signal enumerated in
[`RESPONSE-RUNBOOK-51ATTACK.md`](RESPONSE-RUNBOOK-51ATTACK.md) §0 and
emits structured JSONL alerts to stdout (and optionally to a webhook).
It is the in-house deliverable for SECURITY-ROADMAP §9 ("continuous
51%-attack monitoring").

This document covers operator deployment.  The watcher itself is
self-documented (`python3 contrib/monitoring/51attack-watch.py
--help`); the algorithm rationale lives in the docstring at the top of
the script.

## What it watches

| Signal | Data source | Default threshold | Mitigation / runbook reference |
|---|---|---|---|
| `deep_fork` | RPC `getchaintips` | branchlen ≥ 6 on a non-active tip | F-2 (cheap double-spend), M-3 (LWMA-3 retargeting) |
| `long_reorg` | RPC `getchaintips` | branchlen ≥ 50 on a non-active tip | RUNBOOK §0 trigger #1 (long deep reorg, depth > 50); M-4 + M-14 |
| `hashrate_collapse` | RPC `getnetworkhashps N` | current ≤ 50% of recent peak over last 100 blocks | F-3 (bootstrap-window risk), M-3 + M-13 |
| `hashrate_sustained_drop` | RPC `getnetworkhashps 144`, wall-clock | hps ≤ 70% of trailing 24h peak, sustained ≥ 1h | RUNBOOK §0 trigger #4 (>30% drop sustained >1h) |
| `near_reorg_cap` | RPC `getblockchaininfo` + `getblockheader` walk | reorg depth ≥ 100 (= ½ of `consensus.max_reorg_depth`) | M-4 (reorg-depth cap) |
| `finalized_drift_source_flip` | RPC `getfinalizedblockhash` | source changed (`operator` ⇄ `max_reorg_depth`) | M-14; informational (operator just ran `finalizeblock`/`unfinalizeblock`) |
| `finalized_drift_operator_change` | RPC `getfinalizedblockhash` | source stayed `operator` but hash changed | M-14; warning (re-finalize without unfinalize) |
| `finalized_drift_horizon_stall` | RPC `getfinalizedblockhash` + tip height | implicit M-4 horizon stuck while tip advanced for N polls | M-14; tip-stall indicator |
| `deep_reorg_log` | `debug.log` tail | any line matching `deep-reorg-attempt` | RUNBOOK §0 trigger #2; M-4 fired (consider M-14) |
| `pow_budget_storm` | `debug.log` tail | > 100 `b3pow-budget-exceeded` lines / hour | RUNBOOK §0 trigger #3; D1/D2/D3 verifier-DoS defenses |
| `rpc_down` | (housekeeping) | RPC call raised `RpcUnavailable` | not a chain-level event; check b3chaind / cookie |

All thresholds are CLI-configurable (see `--help`); environment
variables prefixed `WATCH_` are NOT used — pass flags via the systemd
unit's `ExecStart` line.

Notes:

- `hashrate_collapse` keys its sliding window on **block height**, so a
  host clock-jump or NTP step does not desync it.
- `hashrate_sustained_drop` keys on **wall-clock** (per the runbook's
  ">1 hour" semantic).  A large NTP step can transiently mis-fire the
  warning band, but recovers within the next sustained-window once
  fresh samples arrive.
- `deep_reorg_log` and `pow_budget_storm` both depend on the log
  tailer; see "Log-tail prerequisites" below.

## Log-tail prerequisites

`deep_reorg_log` and `pow_budget_storm` work by tailing the b3chaind
`debug.log`.  Three things must be true:

1. The watcher process can `open()` the file for reading.  In the
   systemd unit below this is granted via `ReadOnlyPaths=` on the
   datadir, which already covers `debug.log` inside that directory.
2. The watcher and b3chaind run on the same host.  Cross-host log
   shipping is out of scope; pass `--no-log-tail` if the watcher
   runs off-host and rely on log-aggregator alerts upstream.
3. The default log path is `<datadir>/<chain-subdir>/debug.log`.
   Override with `--debug-log /custom/path` if your b3chaind writes
   elsewhere.

If the file does not exist at startup the watcher logs a single
stderr warning and continues with the log-tail detectors silenced;
the RPC detectors keep running.  The watcher does NOT replay log
history at startup — it seeks to EOF, so existing
`deep-reorg-attempt` lines from before the daemon started are NOT
re-paged.

The tailer is inode-aware: when logrotate renames `debug.log` to
`debug.log.1` and creates a new empty file, the next poll detects
the inode change, drains the rotated file, and reopens the new one.
Out-of-band manual `mv` + `touch` works the same way.

## Output format

One JSONL line per alert, e.g.:

```json
{"branchlen":12,"kind":"deep_fork","message":"non-active tip 4b3f758b3060... at branchlen=12 (>= 6)","severity":"warning","source":"51attack-watch","status":"valid-fork","tip_hash":"4b3f758b306086eca0a95c68020ab74cb87c652b1788780fa3235306bb3d4006","tip_height":12345,"ts":1747688400}
```

Fields common to every alert:

- `kind`        — one of: `deep_fork`, `long_reorg`,
                  `hashrate_collapse`, `hashrate_sustained_drop`,
                  `near_reorg_cap`, `finalized_drift_source_flip`,
                  `finalized_drift_operator_change`,
                  `finalized_drift_horizon_stall`, `deep_reorg_log`,
                  `pow_budget_storm`, `rpc_down`
- `severity`    — `info` / `warning` / `critical`
- `message`     — human-readable one-liner
- `ts`          — emit time (UNIX seconds)
- `source`      — always `"51attack-watch"`

Plus signal-specific fields documented in the script's docstring.

## Quick start — one-shot smoke test

Useful to verify the auth + connectivity loop on a fresh deploy:

```sh
# Cookie-auth (the b3chaind default), mainnet
python3 contrib/monitoring/51attack-watch.py \
    --rpc-port 8532 \
    --datadir /var/lib/b3chain/.b3chain \
    --chain main \
    --one-shot
```

Exit code 0 + no JSONL output to stdout means "no alerts fired" (i.e.
the chain is healthy at this instant).  An `rpc_down` JSON line means
the cookie path or port was wrong.

## Systemd unit (seed1 example)

`/etc/systemd/system/b3chain-51watch.service`:

```ini
[Unit]
Description=B3Chain 51%-attack early-warning monitor
After=network-online.target b3chaind.service
Wants=network-online.target
Requires=b3chaind.service

[Service]
Type=simple
User=deploy
Group=deploy

# JSONL alerts are captured by journald (journalctl -u b3chain-51watch),
# AND mirrored to a rotated logfile that downstream log shippers
# (Loki / CloudWatch / etc.) can tail.
Environment=PYTHONUNBUFFERED=1
# Webhook -- comment out the next line to disable.  Validated at
# startup; the unit refuses to start if the URL is malformed.
Environment=WEBHOOK_URL=https://pagerduty.example.com/services/XXX/integrations/YYY

ExecStart=/usr/bin/python3 /opt/b3chain/contrib/monitoring/51attack-watch.py \
    --rpc-port 8532 \
    --datadir /var/lib/b3chain/.b3chain \
    --chain main \
    --interval 30 \
    --dedup-window 300 \
    --long-reorg-depth 50 \
    --pow-budget-rate 100 \
    --pow-budget-window 3600 \
    --hashrate-sustained-drop 0.70 \
    --hashrate-sustained-window 3600

StandardOutput=append:/var/log/b3chain/51watch.jsonl
StandardError=journal
Restart=on-failure
RestartSec=15s

# Hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/var/log/b3chain
# Read-only access to the cookie AND to debug.log (needed for the
# deep_reorg_log + pow_budget_storm detectors).  The datadir entry
# covers both since debug.log lives at <datadir>/<chain>/debug.log.
ReadOnlyPaths=/var/lib/b3chain/.b3chain

[Install]
WantedBy=multi-user.target
```

Enable + start:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now b3chain-51watch.service
sudo systemctl status b3chain-51watch.service
journalctl -u b3chain-51watch -f
```

Log rotation (`/etc/logrotate.d/b3chain-51watch`):

```
/var/log/b3chain/51watch.jsonl {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 0640 deploy deploy
    postrotate
        systemctl reload b3chain-51watch.service >/dev/null 2>&1 || true
    endscript
}
```

## Webhook compatibility

Each alert is POSTed as `application/json`.  The body is the full
alert JSON — every field exposed by the detector, plus `ts` /
`source`.  This is directly compatible with:

- **PagerDuty Events API v2** — set `WEBHOOK_URL` to the integration
  URL.  The alert's `severity` field maps cleanly to PD's
  `warning` / `critical`.
- **Slack incoming webhook** — the `message` field renders as the body;
  the rest of the JSON is visible in the "context" section.
- **Generic JSON sinks** (Loki, ElasticSearch, custom incident bus) —
  one alert per HTTP request, no batching.

Webhook delivery failures (5xx, DNS, timeout) are **logged to stderr
and swallowed** — the JSONL alert is still on stdout / in
journald / in the rotated logfile, which is the authoritative sink.
The script will not exit on webhook failure.

## Expected alert volume

On a healthy mainnet running at 4-week parity hashrate, the watcher is
silent except for the normal startup banner (single stderr line) and
should produce **zero `deep_fork` alerts per month** under standard
network conditions.  Two short-lived natural reorgs of depth 1-2 per
week are typical; they will not trigger any of the configured
thresholds.

Steady-state expectation:

| Signal | Healthy mainnet | Healthy testnet | What "noisy" looks like |
|---|---|---|---|
| `deep_fork` (≥ 6 blocks, non-active tip) | 0 / month | < 1 / month | network partition; investigate |
| `long_reorg` (≥ 50 blocks, non-active tip) | 0 / month | 0 / month | runbook §0 trigger #1; an attacker is staging a deep reorg |
| `hashrate_collapse` (≤ 50% of 100-block peak) | 0 / month | rare during bootstrap | imminent reorg attempt or major operator outage |
| `hashrate_sustained_drop` (≤ 70% of 24h peak for ≥ 1h) | 0 / month | rare during bootstrap | runbook §0 trigger #4; coordinated drop-out or region outage |
| `near_reorg_cap` (≥ 100 blocks) | 0 / month | 0 / month | active attack; trigger RESPONSE-RUNBOOK |
| `finalized_drift_source_flip` | 0 / month except after operator action | same | someone with RPC access ran `finalizeblock` / `unfinalizeblock` |
| `finalized_drift_operator_change` | 0 / month | 0 / month | re-finalize without unfinalize — confirm out-of-band who did it |
| `finalized_drift_horizon_stall` | 0 / month | 0 / month | tip stalled vs M-4 horizon; b3chaind is stuck |
| `deep_reorg_log` (any `deep-reorg-attempt`) | 0 / month | 0 / month | runbook §0 trigger #2; M-4 cap fired against a peer |
| `pow_budget_storm` (> 100 `b3pow-budget-exceeded` / h) | 0 / month | 0 / month | runbook §0 trigger #3; verifier-DoS storm |
| `rpc_down` | 0 / month | 0 / month | b3chaind crash, host outage, or auth misconfig |

If you start seeing more than a handful of alerts per week with
identical signatures, raise the dedup window (`--dedup-window
600` = 10 min) or the per-signal threshold; the defaults are tuned for
seed1's mainnet hashrate profile and will need recalibration for
operators running on a low-hashrate testnet.

## Integration with the RESPONSE-RUNBOOK

Each alert kind maps to a specific section of
[`RESPONSE-RUNBOOK-51ATTACK.md`](RESPONSE-RUNBOOK-51ATTACK.md):

| Alert kind | Runbook §0 trigger | Runbook recovery section |
|---|---|---|
| `deep_fork` | (precursor to trigger #1) | §3 Steady-state reorg playbook |
| `long_reorg` | #1 (long deep reorg, depth > 50) | §3 + §3.0a M-14 `finalizeblock` |
| `deep_reorg_log` | #2 (`BLOCK_DEEP_REORG` rejection) | §3 + §3.0a M-14 `finalizeblock` |
| `pow_budget_storm` | #3 (`BLOCK_POW_BUDGET` storm > 100/h) | §3 + §5 Eclipse/Sybil playbook |
| `hashrate_collapse` | (precursor to trigger #4) | §4 Hashrate collapse playbook |
| `hashrate_sustained_drop` | #4 (>30% drop sustained >1h) | §4 Hashrate collapse playbook |
| `near_reorg_cap` | (half-armed; #1 will fire later) | §3 + §3.1 Emergency checkpoint imminent |
| `finalized_drift_source_flip` | — (M-14 operator-action sanity) | §3.0a M-14 recovery — confirm action |
| `finalized_drift_operator_change` | — (M-14 operator-action sanity) | §3.0a — investigate who re-pinned |
| `finalized_drift_horizon_stall` | — (tip stall, not a §0 trigger) | §3.0a + check b3chaind health |
| `rpc_down` | — (not a chain-level event) | Check seed1 host + cookie auth |

The operator should not act on a single alert in isolation.  The
runbook explicitly requires confirming the signal against the
authoritative `b3chain-cli` view before initiating any response
action.

## Source

- `contrib/monitoring/51attack-watch.py` — the watcher itself.
- `doc/security/RESPONSE-RUNBOOK-51ATTACK.md` — incident playbook.
- `doc/security/B3POW-51-ATTACK-ANALYSIS.md` — threat model + the F-1
  through F-6 finding catalogue this monitoring is keyed off of.

## Live deployments

This section records boxes the watcher is **actually running on**, so an
on-call operator can reach the right unit fast.  Update on every deploy
or threshold re-tune.

### seed1 (`166.88.4.250`) — installed 2026-05-20, refreshed to runbook-§0 alerting same day

| Field | Value |
|---|---|
| Chain | `test` (testnet) |
| b3chaind RPC | `127.0.0.1:18534`, rpcuser auth (NOT cookie) |
| b3chaind datadir | `/var/lib/b3chain/.b3chain` (chain subdir is **`testnet3`**, Bitcoin-Core-legacy name) |
| Watcher path | `/opt/b3chain/b3chain/contrib/monitoring/51attack-watch.py` |
| Unit file | `/etc/systemd/system/b3chain-51watch.service` |
| Env file (secrets) | `/etc/b3chain/51watch.env` (root:root 0600) |
| Logrotate | `/etc/logrotate.d/b3chain-51watch` (daily, 30 rotations) |
| JSONL alert sink | `/var/log/b3chain/51watch.jsonl` |
| Webhook | none configured (JSONL-only) |
| Threshold flags | `--interval 30 --dedup-window 600 --hashrate-drop 0.30 --debug-log /var/lib/b3chain/.b3chain/testnet3/debug.log` |
| Source of truth (deploy) | `/opt/b3chain/b3chain/` (`git remote b3chain`, branch `b3chain-main`) |
| Updated via | `cd /opt/b3chain/b3chain && git fetch b3chain && git reset --hard b3chain/b3chain-main && sudo systemctl restart b3chain-51watch.service` |

Detector armed-status on seed1 (as of refresh):

| # | Detector | Status | Why |
|---|---|---|---|
| 1 | `deep_fork` | armed | RPC, no prerequisite |
| 2 | `long_reorg` | armed | RPC, no prerequisite |
| 3 | `hashrate_collapse` | armed | RPC, no prerequisite |
| 4 | `hashrate_sustained_drop` | armed | RPC, no prerequisite |
| 5 | `near_reorg_cap` | armed | RPC, no prerequisite |
| 6 | `finalized_drift_source_flip` | **dormant** | `getfinalizedblockhash` missing on pre-v1.1.3 `b3chaind`; auto-arms once b3chaind is upgraded + watcher restarted |
| 7 | `finalized_drift_operator_change` | **dormant** | same |
| 8 | `finalized_drift_horizon_stall` | **dormant** | same |
| 9 | `deep_reorg_log` | **silenced** | `deploy` user cannot read `/var/lib/b3chain/.b3chain/testnet3/debug.log` (0600 b3chain:b3chain); see "Log-tail perm gap" caveat |
| 10 | `pow_budget_storm` | **silenced** | same |
| - | `rpc_down` | armed | housekeeping |

5 of 10 detectors are live polling testnet; the other 5 require either a `b3chaind` upgrade or a one-time perm change to activate.  The watcher's startup banner in `journalctl -u b3chain-51watch` enumerates the current armed-set on every restart, so the operator always has a ground-truth view.

Notes for seed1:

- **`detect_finalized_drift` is dormant on this box** until `b3chaind`
  itself is upgraded to v1.1.3+.  The running binary does not expose
  `getfinalizedblockhash`, so the watcher gracefully disabled the
  three M-14 detectors for the lifetime of the process (single
  stderr log line, no `rpc_down` alert).  When `b3chaind` on seed1
  is upgraded, restart the watcher (`sudo systemctl restart
  b3chain-51watch.service`) and the M-14 detectors become active on
  the next poll.
- **b3chaind on seed1 is not systemd-managed**, so the watcher unit
  uses `Restart=on-failure` (no `Requires=b3chaind.service`).  If
  b3chaind blips, the watcher emits `rpc_down` JSONL alerts and
  recovers on its own when the RPC comes back.
- **Mainnet re-tune TODO**: when seed1 flips `chain=test` →
  `chain=main`, edit `ExecStart=` in the unit file to use
  `--chain main --rpc-port 8532 --dedup-window 300 --hashrate-drop
  0.50 --debug-log /var/lib/b3chain/.b3chain/debug.log`
  (mainnet has no chain subdir under the datadir), then
  `sudo systemctl daemon-reload && sudo systemctl restart
  b3chain-51watch.service`.

### Known operational caveats

- **Log-tail perm gap** (silences `deep_reorg_log` + `pow_budget_storm`
  on seed1).  `b3chaind` writes `debug.log` as `b3chain:b3chain 0600`,
  but the watcher runs as `deploy`, which is not in the `b3chain`
  group.  The unit already passes `--debug-log
  /var/lib/b3chain/.b3chain/testnet3/debug.log` so the watcher tries
  the right path; the `_LogTailer` catches `PermissionError` and logs
  a single stderr warning ("log tailer disabled: ... Permission
  denied"), then continues with the 5 RPC detectors armed.  Fix
  (one-time, no service-restart needed beyond the watcher):
  ```sh
  sudo usermod -aG b3chain deploy            # deploy joins b3chain group
  sudo setfacl -m g:b3chain:rX /var/lib/b3chain/.b3chain
  sudo setfacl -m g:b3chain:rX /var/lib/b3chain/.b3chain/testnet3
  sudo setfacl -m g:b3chain:r  /var/lib/b3chain/.b3chain/testnet3/debug.log
  sudo setfacl -d -m g:b3chain:r /var/lib/b3chain/.b3chain/testnet3   # inherit on rotation
  sudo systemctl restart b3chain-51watch.service                       # picks up new group
  ```
  The watcher's hardening directive `ReadOnlyPaths=/var/lib/b3chain/.b3chain`
  already permits the systemd-side read; only the Unix DAC perms are blocking.
- **rpcpassword visible in `/proc/<pid>/cmdline`**: systemd expands
  `${RPCPASSWORD}` from `EnvironmentFile=` into the `ExecStart=`
  command line before `exec(2)`, so the password is visible via `ps
  auxww`, `systemctl status`, and `/proc/<pid>/cmdline` to anyone with
  shell access on the host.  This is the same threat surface as
  `/etc/b3chain/b3chain.conf` (which is the source of truth for the
  password and is readable to anyone running b3chaind), so it is
  **not** a new escalation, but it is a documented hardening gap.
  Future work: add `--rpc-password-file PATH` support to the watcher
  so the unit can pass a path instead of inlining the value.
- **Webhook is disabled by default**: the env file ships with
  `WEBHOOK_URL=` commented out.  Until an incident bus URL is
  configured, alerts land in journald + the rotated JSONL logfile
  only.  Operators must tail one of those during high-risk windows.

### Seed-only nodes (`seed2 151.158.1.22`, `seed3 151.158.1.60`)

Watcher **not deployed**.  These boxes run b3chaind in seed-only mode
with no operator-action footprint, so monitoring there is low value.
The same install recipe (this document) would work if needed.
