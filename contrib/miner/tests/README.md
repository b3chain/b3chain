# b3chain CPU miner — Windows test UI

A one-click PyQt6 application that runs the full CPU-miner test suite
on Windows and shows pass/fail/skip per test plus the live console
output of every run.

## Quick start

```bat
contrib\miner\tests\run_tests_ui.bat
```

The first launch creates a private virtualenv inside the `tests/`
directory and installs `PyQt6` + `blake3` into it (~1 minute).
Subsequent launches start instantly.

If `py -3` is not on PATH, the launcher falls back to `python` and
prints a helpful error if neither is available.

## What it tests

The UI runs nine tests, ordered fastest first so it fails early:

| # | Name | Runtime | Notes |
|---|---|---|---|
| 1 | Environment check                | <1s   | builtin: Python ≥ 3.9, `blake3` import, miner script exists |
| 2 | Helper unit tests                 | <1s   | 16 known-answer asserts on `parse_stratum_url`, `target_from_share_difficulty`, `network_difficulty_from_bits`, `build_coinbase_full`, `compute_merkle_root_from_branches`, `serialize_header` |
| 3 | Argparse mutex                    | <2s   | confirms `--stratum` and `--coinbaseaddr` are mutually exclusive (rc=2) |
| 4 | Benchmark                         | ~10s  | `b3chain-cpuminer.py --benchmark`; PASS at ≥ 200 kH/s |
| 5 | Mock-pool E2E                     | ~3s   | runs `test_pool_miner.py` (in-process Stratum mock + miner; 5 shares, BLAKE3d-verified) |
| 6 | JSONL re-derive                   | ~3s   | re-runs the mock pool, then re-hashes every share's `header_hex` from the JSONL log and asserts byte-equal to `pow_hash_le` |
| 7 | Solo regtest                      | ~30s  | spawns `b3chaind -regtest` in a temp datadir, mines 1 block, tears down. Auto-skipped if `b3chaind`/`b3chain-cli` is not on PATH |
| 8 | Live pool reachability            | <2s   | TCP-connects to `pool.b3chain.org:3333`, sends `mining.subscribe`, expects a JSON-RPC result within 5s. Auto-skipped on no internet |
| 9 | Local Docker pool stack (opt-in)  | 2-5m  | brings up Postgres via `docker compose`, runs `npm install / migrate / dev:daemon / dev:stratum`, mines 5 shares, then tears the whole stack down. Auto-skipped unless Docker Desktop is running and `npm` is on PATH |

Test 9 is gated behind a "Include slow tests" checkbox so it is **not**
included in **Run All** by default; you can still launch it from its
row's **Run** button.

## Capabilities and graceful skipping

A capability strip at the top shows which dependencies the box has:

* Python, `blake3`, `b3chain-cpuminer.py`, `test_pool_miner.py`
* `b3chaind`, `b3chain-cli` (only needed for tests 7 and 9)
* `docker` (with daemon running) and `npm` (only for test 9)
* DNS resolution + a TCP probe of `pool.b3chain.org:3333`
* The pool source tree at `contrib/testnet/pool` (only for test 9)

Tests whose prerequisites are missing are greyed out with a tooltip
explaining what is missing. Click **Recheck Env** after installing
something (e.g. starting Docker Desktop) to re-probe and unlock rows
without restarting the UI.

## Live output

The bottom pane is a monospace, dark-themed `QTextEdit` that streams
each test's stdout/stderr line by line. ANSI colour codes are stripped
on the way in so the pane stays readable. The view autoscrolls;
content can be selected and copied.

## Save Report

Click **Save Report** to write `report-YYYYMMDD-HHMMSS.json` plus a
parallel `report-YYYYMMDD-HHMMSS.md` next to the launcher. Each report
includes:

* host info (OS, Python version, blake3 version)
* the full capability set (with detail strings)
* per-test status, metric, duration, and a tail of the captured output
* an aggregate summary (pass / fail / skip / error / total runtime)

The Markdown rendering is suitable for pasting into email or chat.

## Cancellation and clean shutdown

* Each row has a **Stop** button that activates while the test is
  running. For subprocess tests this calls `QProcess.kill()` and
  results in an `ERROR` status.
* Closing the window mid-test kills the in-flight process and tears
  down any pool stack started by test 9 (`docker compose down`).
* Test 7's `b3chaind` is always shut down via `b3chain-cli stop` (or
  killed if the graceful stop hangs) on success, failure, or window
  close. Its temp datadir is wiped.

## Live mining dashboard (Mine button)

Click **Mine** in the toolbar (between **Recheck Env** and **Run All**)
to open a separate live-mining window. The dashboard runs
`b3chain-cpuminer.py` against a configurable Stratum V1 pool and shows
the full picture in real time:

* **Top bar** — pool URL combo box (with last-used dropdown), user,
  password, threads spin (defaults to `cpu_count - 1`), useragent,
  **Start** / **Stop**.
* **Status strip** — connection state, `extranonce1`, `extranonce2_size`,
  network difficulty, share difficulty, current job id.
* **Stats cards** — large hashrate readout (smoothed over a 5 s rolling
  window so per-thread emit-timing jitter doesn't ripple the display),
  submitted / accepted (with acceptance %), rejected, total attempts,
  blocks found.
* **Hashrate chart** — rolling 5-minute polyline (custom QWidget, no
  extra dependencies) with a "now" marker and auto-rescaled y-axis.
* **Last share panel** — every field of the most recent submission
  (job, ntime, nonce, extranonces, PoW LE/BE, share target, network
  difficulty, RTT, block-hash, header hex, server error if any).
* **Per-thread table** — rate, accumulated attempts, best PoW (BE) per
  worker.
* **Recent shares table** — last 200 shares with seq, job, status,
  RTT, share-difficulty and block flag (rows are colour-coded ACCEPTED
  / REJECTED).
* **Tabs** — Raw stdout (every line the miner prints, dark monospace)
  and JSONL events (the canonical structured stream the dashboard
  parses).
* **Footer** — runtime, shares/min, average hashrate, best PoW so far,
  **Save Session** and **Open Log** buttons.

The dashboard talks to the miner through `--json-log <tmp>`; a 250 ms
`QTimer` polls the file via a stateful `JSONLTail` (`mining_parsers.py`)
that tracks the byte offset and a partial-line buffer, so mid-write
lines are never split or double-read. All UI updates happen on the GUI
thread via typed Qt signals. The miner subprocess inherits a clean
environment with `PYTHONUNBUFFERED=1`.

### Save Session

Click **Save Session** while a run is in progress (or just after
**Stop**) to pick a parent directory; the dashboard creates a
`mining-session-YYYYMMDD-HHMMSS/` subfolder containing:

```
mining-session-20260516-031455/
  miner-stdout.log         # full raw dump (per-share, progress, banners)
  shares.jsonl             # canonical structured stream (preserved as-is)
  session-summary.json     # UI's aggregated stats snapshot
  session-summary.md       # readable rendering
```

`session-summary.json` shape:

```json
{
  "ts": "2026-05-16T03:14:55Z",
  "host": {"os": "Windows 10", "machine": "AMD64", "python": "3.12.4"},
  "config": {"host": "pool.b3chain.org", "port": 3333,
             "use_tls": false, "user": "...", "useragent": "..."},
  "extranonce1": "deadbeef",
  "extranonce2_size": 4,
  "runtime_s": 222.4,
  "totals": {"submitted": 42, "accepted": 41, "rejected": 1, "blocks": 0,
             "accept_rate": 0.9762, "attempts": 7423981234,
             "current_hashrate_hps": 1812345.6,
             "avg_hashrate_hps": 1801234.0,
             "best_pow_be": "0000000a..."},
  "network": {"difficulty": 1.0, "target_be": "00000000ffff..."},
  "share":   {"difficulty": 1024.0, "target_be": "..."},
  "current_job": "0001a3",
  "per_thread": [
    {"id": 0, "rate_hps": 1820000, "attempts": 954000000,
     "best_pow_be": "...", "job_id": "0001a3"}
  ],
  "last_share": { "...": "every field of the last share submission" },
  "disconnect_reason": ""
}
```

The Markdown rendering is suitable for pasting into email or chat.
Persisted UI state lives in `tests/.miner_settings.json` (gitignored)
and remembers the last 8 pool URLs, the user, threads and useragent.

### Tier-3 verification

`tests/verify_dashboard.py` runs three offscreen suites:

```bat
python tests\verify_dashboard.py
```

* **Suite A** — JSONLTail unit tests (offset, partial line, garbage
  line, truncation reset).
* **Suite B** — drives `MiningRunner` against the in-process
  `MockStratumServer` and asserts subscribed/authorized/progress/share
  signals fire and that the JSONL temp file ends up on disk.
* **Suite C** — opens `MiningDashboard`, starts a real miner, then
  closes the window mid-mine and asserts the runner is no longer
  running and that the temp JSONL file was cleaned up.

> **Windows note.** `QProcess.terminate()` on Windows bypasses Python's
> `signal.SIGTERM` handler, so the miner's own `summary` JSONL event
> may not fire after **Stop**. The dashboard does **not** depend on
> that event — all session totals are derived from `share` events as
> they arrive, so Save Session is correct regardless.

## Architecture

```
b3chain/contrib/miner/tests/
  __init__.py
  test_ui.py               # PyQt6 MainWindow (entry point) + Mine button
  test_definitions.py      # TestRegistry + TestCase subclasses + extractors
  capability_check.py      # CapabilityProbe
  helper_tests.py          # tests 2 + 6
  solo_regtest_runner.py   # test 7 b3chaind harness
  pool_stack_runner.py     # test 9 docker+npm orchestration
  live_pool_probe.py       # test 8 TCP smoke
  report_writer.py         # Save Report (JSON + Markdown)
  mining_dashboard.py      # MiningDashboard window + MiningRunner
  mining_parsers.py        # JSONLTail + Share/Progress/Notify dataclasses
  mining_state.py          # HashrateRing, ShareList, PerThreadStats
  hashrate_chart.py        # custom QWidget polyline chart
  verify_dashboard.py      # Tier-3 verification (offscreen Qt)
  run_tests_ui.bat         # double-click launcher (creates venv)
  requirements.txt         # PyQt6, blake3
```

The whole queue runs **serially**: tests 7 and 9 grab fixed ports
(RPC, Postgres, stratum), so running them in parallel with each other
or with the mock-pool tests would race.

## Troubleshooting

* **The window doesn't open:** run `run_tests_ui.bat` from a CMD
  prompt (instead of double-clicking) so you can see launcher errors.
  The most common issue on a fresh box is that no Python at all is
  installed; the launcher prints a clear message in that case.
* **Test 9 is greyed out even though Docker is installed:** open
  Docker Desktop and wait for the whale icon to be solid (i.e. the
  daemon is running), then click **Recheck Env**.
* **Test 7 is greyed out:** add the directory containing
  `b3chaind.exe` and `b3chain-cli.exe` to your `PATH` and click
  **Recheck Env**.
* **Reports go where?** They are written to the same directory as
  `run_tests_ui.bat` (i.e. `contrib/miner/tests/`).
