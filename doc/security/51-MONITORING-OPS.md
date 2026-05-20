# 51-attack monitoring — operator deployment guide

`contrib/monitoring/51attack-watch.py` is a long-running poller that
watches an operator-controlled `b3chaind` for the three early-warning
signals enumerated in
[`RESPONSE-RUNBOOK-51ATTACK.md`](RESPONSE-RUNBOOK-51ATTACK.md) and
emits structured JSONL alerts to stdout (and optionally to a webhook).
It is the in-house deliverable for SECURITY-ROADMAP §9 ("continuous
51%-attack monitoring").

This document covers operator deployment.  The watcher itself is
self-documented (`python3 contrib/monitoring/51attack-watch.py
--help`); the algorithm rationale lives in the docstring at the top of
the script.

## What it watches

| Signal | RPC used | Default threshold | Mitigation reference |
|---|---|---|---|
| `deep_fork` | `getchaintips` | branchlen ≥ 6 on a non-active tip | F-2 (cheap double-spend), M-3 (LWMA-3 retargeting) |
| `hashrate_collapse` | `getnetworkhashps N` | current ≤ 50% of recent peak over last 100 blocks | F-3 (bootstrap-window risk), M-3 + M-13 |
| `near_reorg_cap` | `getblockchaininfo` + `getblockheader` walk | reorg depth ≥ 100 (= ½ of `consensus.max_reorg_depth`) | M-4 (reorg-depth cap) |

All thresholds are CLI-configurable.  The sliding window for the
hashrate-collapse detector is keyed on **block height**, not on
wall-clock time, so a host clock-jump or NTP step does not desync the
detector.

## Output format

One JSONL line per alert, e.g.:

```json
{"branchlen":12,"kind":"deep_fork","message":"non-active tip 4b3f758b3060... at branchlen=12 (>= 6)","severity":"warning","source":"51attack-watch","status":"valid-fork","tip_hash":"4b3f758b306086eca0a95c68020ab74cb87c652b1788780fa3235306bb3d4006","tip_height":12345,"ts":1747688400}
```

Fields common to every alert:

- `kind`        — `deep_fork` / `hashrate_collapse` / `near_reorg_cap`
                  / `rpc_down`
- `severity`    — `warning` / `critical`
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
    --dedup-window 300

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
# Read-only access to the cookie:
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
| `hashrate_collapse` (≤ 50% of 100-block peak) | 0 / month | rare during bootstrap | imminent reorg attempt or major operator outage |
| `near_reorg_cap` (≥ 100 blocks) | 0 / month | 0 / month | active attack; trigger RESPONSE-RUNBOOK |
| `rpc_down` | 0 / month | 0 / month | b3chaind crash, host outage, or auth misconfig |

If you start seeing more than a handful of alerts per week with
identical signatures, raise the dedup window (`--dedup-window
600` = 10 min) or the per-signal threshold; the defaults are tuned for
seed1's mainnet hashrate profile and will need recalibration for
operators running on a low-hashrate testnet.

## Integration with the RESPONSE-RUNBOOK

Each alert kind maps to a specific section of
[`RESPONSE-RUNBOOK-51ATTACK.md`](RESPONSE-RUNBOOK-51ATTACK.md):

| Alert | Runbook section |
|---|---|
| `deep_fork` | "Hashrate collapse playbook" + "Deep reorg playbook" |
| `hashrate_collapse` | "Hashrate collapse playbook" |
| `near_reorg_cap` | "Deep reorg playbook" (now half-armed; M-4 will fire at full cap) |
| `rpc_down` | Not a chain-level event; check seed1 health |

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

### seed1 (`166.88.4.250`) — installed 2026-05-20

| Field | Value |
|---|---|
| Chain | `test` (testnet) |
| b3chaind RPC | `127.0.0.1:18534`, rpcuser auth (NOT cookie) |
| Watcher path | `/opt/b3chain/b3chain/contrib/monitoring/51attack-watch.py` |
| Unit file | `/etc/systemd/system/b3chain-51watch.service` |
| Env file (secrets) | `/etc/b3chain/51watch.env` (root:root 0600) |
| Logrotate | `/etc/logrotate.d/b3chain-51watch` (daily, 30 rotations) |
| JSONL alert sink | `/var/log/b3chain/51watch.jsonl` |
| Webhook | none configured (JSONL-only) |
| Thresholds (testnet-tuned) | `--interval 30 --dedup-window 600 --hashrate-drop 0.30` |
| Source of truth (deploy) | `/opt/b3chain/b3chain/` (`git remote b3chain`, branch `b3chain-main`) |
| Updated via | `cd /opt/b3chain/b3chain && git fetch b3chain && git reset --hard b3chain/b3chain-main && sudo systemctl restart b3chain-51watch.service` |

Notes for seed1:

- **`detect_finalized_drift` is dormant on this box** until `b3chaind`
  itself is upgraded to v1.1.3+.  At install time the running binary
  did not expose `getfinalizedblockhash`, so the watcher gracefully
  disabled the M-14 horizon-stall detector for the lifetime of the
  process (single stderr log line, no `rpc_down` alert).  The three
  legacy detectors (`deep_fork`, `hashrate_collapse`, `near_reorg_cap`)
  remain fully armed.  When `b3chaind` on seed1 is upgraded, restart
  the watcher (`sudo systemctl restart b3chain-51watch.service`) and
  the drift detector becomes active on the next poll.
- **b3chaind on seed1 is not systemd-managed**, so the watcher unit
  uses `Restart=on-failure` (no `Requires=b3chaind.service`).  If
  b3chaind blips, the watcher emits `rpc_down` JSONL alerts and
  recovers on its own when the RPC comes back.
- **Mainnet re-tune TODO**: when seed1 flips `chain=test` →
  `chain=main`, edit `ExecStart=` in the unit file to use
  `--chain main --rpc-port 8532 --dedup-window 300 --hashrate-drop
  0.50`, then `sudo systemctl daemon-reload && sudo systemctl restart
  b3chain-51watch.service`.

### Known operational caveats

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
