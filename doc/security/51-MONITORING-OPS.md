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
| 6 | `finalized_drift_source_flip` | armed (since 2026-05-20 02:51 UTC) | `getfinalizedblockhash` available after b3chaind v1.1.3 cold-start (see "v1.1.3 cold-start narrative" below) |
| 7 | `finalized_drift_operator_change` | armed (since 2026-05-20 02:51 UTC) | same |
| 8 | `finalized_drift_horizon_stall` | armed (since 2026-05-20 02:51 UTC) | same |
| 9 | `deep_reorg_log` | armed (since 2026-05-20 01:04 UTC) | log-tail perm gap fixed via `usermod -aG b3chain deploy` + posix ACL on `testnet3/` (see Known operational caveats below); ACL was re-applied after the v1.1.3 cold-start recreated `testnet3/` |
| 10 | `pow_budget_storm` | armed (since 2026-05-20 01:04 UTC) | same |
| - | `rpc_down` | armed | housekeeping (validated 2026-05-20 02:31 UTC during the failed v30.2.0→v1.1.3 cutover: one alert fired correctly, 600 s dedup correctly suppressed re-fires) |

**10 of 10 detectors armed.**  The watcher's startup banner in `journalctl -u b3chain-51watch` enumerates the current armed-set on every restart, so the operator always has a ground-truth view (look for `log_tailer=on` and the absence of any `getfinalizedblockhash RPC unavailable` line).

Notes for seed1:

- **v1.1.3 cold-start narrative (the path that landed 10/10 armed).**
  The first v1.1.3 cutover attempt at 02:32 UTC failed because the
  new binary rejected the existing 8716-block testnet3 chain with
  `LoadBlockIndexGuts: nBits out of range:
  CBlockIndex(nHeight=216, hashBlock=3c4910412894...e2a00)` —
  the deliberate F-6 powlimit fix (`f-6_powlimit_code_fix` plan,
  B3PoW-Scratch v1.1.3) tightens `nBits` validation, so blocks
  produced under v30.2.0's looser rules are rejected under v1.1.3.
  The rollback contract executed cleanly (no datadir corruption
  because `LoadBlockIndexGuts` is read-only; v30.2.0 binaries
  re-installed; daemon back at block 8712 in 2 s; auto-stopped
  consumers `b3chain-explorer.service` + `electrs-testnet.service`
  restarted by hand; watcher emitted exactly one `rpc_down` JSONL
  alert at ts `1779244316`, dedup-suppressed thereafter).  The
  operator then chose path (b) "wipe + cold-start" from the
  decision tree.  Sequence: stop all 12 services, `rm -rf
  /var/lib/b3chain/.b3chain/testnet3`, install v1.1.3 binaries
  (md5 `5217d57b...` / `0a17225a...`), `systemctl start
  b3chaind-testnet.service`.  Daemon came up at block 0 in 2 s
  with `Difficulty: 0.007812...` (genesis target), 2 outbound peers
  initially, 4 within the first minute.  `getfinalizedblockhash`
  returned `{"hash": "", "height": -200, "source":
  "max_reorg_depth"}` — the expected "below reorg depth" sentinel
  at height 0.  `help finalizeblock` / `help unfinalizeblock` /
  `help parkblock` / `help unparkblock` all return the b3chain M-14
  help text (full RPC pin-management surface live).  ACL on the
  freshly-created `testnet3/` was re-applied because b3chaind
  recreated the dir with `drwx------ 0700` and dropped the Phase 1
  ACL; the recipe in "Known operational caveats" below is now
  documented as having TWO trigger conditions: first-time install
  AND any operation that recreates `testnet3/`.  Watcher restart
  banner at 02:51 UTC: `log_tailer=on`, no
  `getfinalizedblockhash RPC unavailable` line — **all 10 detectors
  armed**.  90 s soak clean (`NRestarts=0`, MemoryCurrent 13.2 MB).
  Backups retained on disk for the 24 h observation window before
  cleanup: `/var/lib/b3chain/.b3chain/testnet3.bak-pre-v113`
  (74 MB, 8716-block pre-cutover state),
  `/usr/local/bin/b3chaind.bak-v30.2.0-prev113`,
  `/usr/local/bin/b3chain-cli.bak-v30.2.0-prev113`.
- **b3chaind on seed1 IS systemd-managed** as
  `b3chaind-testnet.service`, with the well-hardened directives
  documented above.  The watcher unit `b3chain-51watch.service`
  now carries `Requires=b3chaind-testnet.service` +
  `After=b3chaind-testnet.service` (added 2026-05-20 02:51 UTC),
  so the watcher follows the daemon's lifecycle: stopping b3chaind
  auto-stops the watcher (no spurious `rpc_down` alert storm),
  starting b3chaind auto-starts the watcher.  Both units are
  staged into [`contrib/init/b3chaind-testnet.service`](../../contrib/init/b3chaind-testnet.service)
  and [`contrib/init/b3chain-51watch.service`](../../contrib/init/b3chain-51watch.service)
  byte-for-byte matching seed1, so seed2/seed3 (or any future
  seed) can be brought up with the same posture by `cp`-ing both
  files into `/etc/systemd/system/`, `systemctl daemon-reload`,
  `systemctl enable --now`.
- **Mainnet re-tune TODO**: when seed1 flips `chain=test` →
  `chain=main`, edit `ExecStart=` in the unit file to use
  `--chain main --rpc-port 8532 --dedup-window 300 --hashrate-drop
  0.50 --debug-log /var/lib/b3chain/.b3chain/debug.log`
  (mainnet has no chain subdir under the datadir), then
  `sudo systemctl daemon-reload && sudo systemctl restart
  b3chain-51watch.service`.
- **v1.1.4 testnet powLimit divergence (2026-05-20 07:30 UTC,
  follow-up to the v1.1.3 cold-start above).**  The v1.1.3 cold-start
  landed all 10 detectors armed but produced **zero blocks in the
  next ~4 hours** -- the mining loop ran continuously but the F-6
  consensus floor (`powLimit = 0x1d7fffff`, designed for ~27 min/block
  on a single KU5P FPGA at 20 KH/s) is also the rough single-thread
  ballpark of B3PoW-Scratch on a 2-core commodity VPS (1 MB
  scratchpad random-reads are DRAM-bandwidth-bound, not
  CPU-frequency-bound).  At 27 min/block expected, the b3chain-cli
  default `-rpcclienttimeout=900` (15 min) fires before the daemon
  can finish, the miner script catches the "timeout reached" error,
  loops, and each new `generatetoaddress` discards the prior search
  -- so the chain never advanced past block 0.  This is **intended
  for mainnet** (closes the F-6 "tens-of-seconds" exploit window per
  `doc/security/B3POW-51-ATTACK-ANALYSIS.md` F-6), but unworkable
  for a developer-friendly testnet on commodity hardware.  The fix
  (commit `7b0ab6bf08`, `consensus(testnet): v1.1.4 powLimit
  divergence`): testnet `CTestNetParams` reverts to the **pre-F-6
  floor 0x1e01ffff** (4x easier than mainnet's 0x1d7fffff),
  `operating_pow_floor_bits` scales proportionally to `0x1dffff80`
  (still 2x stricter than testnet powLimit, same relationship
  mainnet has), and the testnet genesis was re-mined locally
  (Python+blake3, 2.1 s, 2.3M nonces, ~1.1 MH/s):
  ```
  CreateGenesisBlock(1739145601, 2275226, 0x1e01ffff, 1, 50*COIN)
  hashGenesisBlock = 8c61fcbc6249f2518010fabc1589f91d35378f48757ef97323e8cb401103ae64
  hashMerkleRoot   = 7637f54884268792762b66946b6c4f41fab550164d54f17741b7381dd586dbbb
  ```
  CMainParams, CTestNet4Params, CSignetParams, CRegTestParams are
  all **untouched** -- the F-6 tightening stays on the production
  chain.  Build: incremental cmake `--target bitcoind bitcoin-cli`
  on seed1, 74 s wallclock, new `b3chaind` md5
  `4c9ea0e7c76e096a0860d6918cf4af8c`, `b3chain-cli` unchanged
  (doesn't link chainparams).  Deploy: byte-for-byte same binary
  installed on seed1, seed2, seed3 (the latter two went directly
  from May-14 v30.2.0 binaries to v1.1.4 with no v1.1.3 in
  between -- they had the same pre-F-6 testnet genesis hash, so
  seed2/seed3 had been running their own pre-F-6 chain at height
  8716 the whole time, partitioned from seed1's v1.1.3 cold-started
  chain).  All three seeds now form a **full 4-peer mesh** at
  genesis `8c61fcbc6249...` on testnet3.  Tier-3 verification post
  cold-start (07:24 UTC): seed1 `getblockhash 0` matches, target
  `000001ffff...`, difficulty `0.001953` (exactly 4x easier than
  v1.1.3's `0.007812`), 4 peers, watcher's startup banner shows
  `log_tailer=on` and no `getfinalizedblockhash RPC unavailable`
  line.  Backups retained: `/usr/local/bin/b3chaind.bak-v113-prev114`
  + `b3chain-cli.bak-v113-prev114` on seed1, `.bak-v30.2.0` on
  seed2/seed3.  Miner also patched: `b3chain-testnet-miner.sh`
  ARGS now carries `-rpcclienttimeout=3600` so each
  `generatetoaddress` call gets 1 hour of patience instead of the
  default 15 min (saved as `.bak-prev114-timeout`); first block on
  this VPS at the relaxed floor is expected in the 20-90 min range
  (B3PoW-Scratch on commodity x86 single-thread is still memory-
  bound, just at ~4x easier difficulty).  **Open observation as of
  ~07:59 UTC**: ~25 min of continuous mining, still at block 0;
  `b3chaind` two `httpworker` threads at 70%+35% CPU confirming the
  daemon is actively searching, no consensus rejections in the log,
  just slower-than-expected hashrate.  If 60+ min passes with no
  block, the next step is to relax further (`0x1f00ffff` middle
  ground or `0x207fffff` regtest-easy testnet), but the chain is
  functioning -- this is purely a "first-block latency on commodity
  HW" question, not a correctness issue.
- **v1.1.5 testnet powLimit divergence (2026-05-21).**  v1.1.4 at
  `0x1e01ffff` did produce blocks (height 2 by ~2026-05-20 23:00 UTC)
  but at **~5-6 h/block** on seed1's commodity CPU, and the miner's
  `-rpcclienttimeout=3600` patch still produced hourly `"timeout
  reached"` errors because the client abandons the RPC while
  `b3chaind` keeps hashing (overlapping `httpworker` threads; see
  lesson #7).  The fix pairs two changes: (1) testnet
  `CTestNetParams.powLimit` relaxed to **`0x1f00ffff`** (~128× easier
  than v1.1.4, ~512× easier than mainnet F-6), with
  `operating_pow_floor_bits = 0x1effff80`; (2) canonical miner script
  `contrib/testnet/miner/b3chain-testnet-miner.sh` now passes
  **`-rpcclienttimeout=0`** (Bitcoin Core recommendation for mining
  RPCs).  Testnet genesis re-mined locally (Python+blake3, 0.1 s,
  111470 nonces):
  ```
  CreateGenesisBlock(1739145601, 111470, 0x1f00ffff, 1, 50*COIN)
  hashGenesisBlock = ebc117cd39760da3c8a3687484858e8ea2cfbc88990fb587957b4ba956a661c6
  hashMerkleRoot   = 6fefcc8f9ca9674e3948b2a74c381f8abb9f0e38349fad3d62794ed3895269dc
  ```
  CMainParams, CTestNet4Params, CSignetParams, CRegTestParams are
  **untouched**.  Deploy: coordinated wipe of `testnet3/` on seed1,
  seed2, seed3 + cold-start + full mesh verification.  Expected block
  time on seed1 CPU: **minutes**, not hours.

### Known operational caveats

- **Log-tail perm gap — RESOLVED on seed1 (2026-05-20)** (kept here as
  the canonical first-time-install recipe for future seed boxes,
  AND as the re-apply recipe whenever `testnet3/` is recreated —
  e.g. after `rm -rf testnet3 && systemctl start b3chaind-testnet`
  for a chain-rule-change cold start).  `b3chaind` writes
  `debug.log` as `b3chain:b3chain 0600`, so the `deploy`-run
  watcher needs explicit access.  The recipe below joins `deploy`
  to the `b3chain` group, installs `acl` if missing (Ubuntu 22.04
  doesn't ship it by default), and adds POSIX ACL entries so the
  rotated `debug.log` keeps the group-read bit.  Idempotent — safe
  to run any number of times:
  ```sh
  sudo apt-get install -y acl                # Ubuntu 22.04 omits acl by default
  sudo usermod -aG b3chain deploy
  sudo setfacl -m g:b3chain:rX /var/lib/b3chain
  sudo setfacl -m g:b3chain:rX /var/lib/b3chain/.b3chain
  sudo setfacl -m g:b3chain:rX /var/lib/b3chain/.b3chain/testnet3
  sudo setfacl -m g:b3chain:r  /var/lib/b3chain/.b3chain/testnet3/debug.log
  sudo setfacl -d -m g:b3chain:r /var/lib/b3chain/.b3chain/testnet3   # inherit on rotation
  sudo systemctl restart b3chain-51watch.service                       # picks up new group
  ```
  Acceptance test:
  ```sh
  sudo -u deploy test -r /var/lib/b3chain/.b3chain/testnet3/debug.log && echo OK
  sudo journalctl -u b3chain-51watch -n 5 | grep -q 'log tailer attached' && echo TAILER_OK
  ```
  The watcher's hardening directive `ReadOnlyPaths=/var/lib/b3chain/.b3chain`
  already permits the systemd-side read; only the Unix DAC perms were blocking.
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
