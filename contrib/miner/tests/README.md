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

## Architecture

```
b3chain/contrib/miner/tests/
  __init__.py
  test_ui.py               # PyQt6 MainWindow (entry point)
  test_definitions.py      # TestRegistry + TestCase subclasses + extractors
  capability_check.py      # CapabilityProbe
  helper_tests.py          # tests 2 + 6
  solo_regtest_runner.py   # test 7 b3chaind harness
  pool_stack_runner.py     # test 9 docker+npm orchestration
  live_pool_probe.py       # test 8 TCP smoke
  report_writer.py         # Save Report (JSON + Markdown)
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
