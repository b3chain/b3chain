#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
B3Chain 51%-attack monitoring daemon.

Long-running poller that watches an operator-controlled b3chaind for
the three early-warning signals enumerated in
[`doc/security/RESPONSE-RUNBOOK-51ATTACK.md`](../../doc/security/RESPONSE-RUNBOOK-51ATTACK.md)
and emits structured JSONL alerts (stdout + optional webhook).

SECURITY-ROADMAP §9 deliverable.

Signals
-------

The watcher emits one alert when any of the following becomes true,
re-emits the same alert when the signal recovers, and de-duplicates
identical alerts inside a sliding window (default 5 min) so a single
incident does not page the operator hundreds of times.

  deep_fork            -- `getchaintips` reports a non-active tip
                          whose `branchlen >= --deep-fork-depth`
                          (default 6 = 1 hour at 10 min spacing).
                          Maps to F-2 (cheap double-spend) and to the
                          first column of RESPONSE-RUNBOOK §"Hashrate
                          collapse" + §"Deep reorg".

  long_reorg           -- RUNBOOK §0 trigger #1.  Same getchaintips
                          shape as deep_fork but the threshold the
                          runbook actually names (default 50,
                          configurable via --long-reorg-depth).
                          Sits between deep_fork (>=6) and
                          near_reorg_cap (>=100); the 1:1 mapping
                          to the runbook row gives the war-room a
                          single grep to confirm trigger #1.

  hashrate_collapse    -- `getnetworkhashps` dropped to <= 50% of
                          its maximum in the previous
                          --hashrate-window blocks.  Maps to F-3
                          (low-hashrate bootstrap window) and is the
                          single best predictor of an imminent
                          competitor-fork attempt.  BLOCK-keyed
                          (clock-skew-immune).

  hashrate_sustained_drop -- RUNBOOK §0 trigger #4.  WALL-CLOCK
                          sibling of hashrate_collapse: alerts when
                          `getnetworkhashps 144` has stayed
                          <= --hashrate-sustained-drop * 24h-peak
                          for >= --hashrate-sustained-window seconds
                          (default 0.70 / 3600s = "70% / 1h",
                          mapping the runbook's ">30% drop sustained
                          >1h").

  near_reorg_cap       -- the active chain reorged by more than
                          --near-reorg-fraction * max_reorg_depth
                          blocks (default 0.5 -> 100 of the 200-block
                          M-4 cap; F-2 fix).  Half-cap is the right
                          point to alert: it gives the operator time
                          to act before the cap actually fires and
                          freezes the chain.

  finalized_drift_*    -- b3chain M-14: drift of the finalization
                          horizon from `getfinalizedblockhash`.  Three
                          sub-kinds:
                            _source_flip      -> operator just ran
                                                 finalizeblock or
                                                 unfinalizeblock.
                            _operator_change  -> operator re-finalized
                                                 at a different block
                                                 without first
                                                 unfinalizing.
                            _horizon_stall    -> implicit M-4 horizon
                                                 stuck while tip
                                                 advanced (= tip stall
                                                 vs cap drift).

  deep_reorg_log       -- RUNBOOK §0 trigger #2.  Tails the b3chaind
                          `debug.log` and alerts on any line
                          containing `deep-reorg-attempt` (the
                          Misbehaving() string from
                          src/net_processing.cpp).  Threshold = any;
                          severity = critical.  Recommended operator
                          response: invoke M-14 `finalizeblock` on
                          the last known-safe tip, see
                          RESPONSE-RUNBOOK §3.0a.

  pow_budget_storm     -- RUNBOOK §0 trigger #3.  Tails the b3chaind
                          `debug.log` for `b3pow-budget-exceeded`
                          lines and alerts when their count in the
                          trailing --pow-budget-window seconds
                          exceeds --pow-budget-rate (default
                          > 100 events / 3600 s).  This is the
                          verifier-DoS storm fingerprint.

Execution model (Tier 3 — verify-before-done audit)
---------------------------------------------------

TRIGGER:  long-running daemon (`_Watcher.run()`'s
          `while not _stop_event.is_set():` body).  Intended to run
          under systemd or a process supervisor; see
          [`doc/security/51-MONITORING-OPS.md`](../../doc/security/51-MONITORING-OPS.md).

LOOP:     `_Watcher.run()` -> `_Watcher.step()`.  `run()` is the
          explicit `while not _stop_event.is_set(): step();
          _stop_event.wait(interval)` body; `step()` is one cycle:
          poll RPC -> tail debug.log (if log tailer is on) ->
          compute alerts -> emit -> return.  The sleep uses
          `Event.wait(interval)` so SIGTERM / SIGINT returns early
          instead of waiting the full --interval seconds.  Sleeps
          are --interval, NOT --interval since last cycle, so a slow
          RPC doesn't burn CPU.  The log tailer reuses this same
          loop: _LogTailer.iter_new_lines() is invoked once per
          cycle and is non-blocking (reads whatever bytes the kernel
          has buffered since the previous call, returns).

BYPASS:   - RPC down                  -> `RpcUnavailable` -> emit
                                         `rpc_down` alert (dedup'd),
                                         continue loop (next iteration
                                         will retry).
          - Webhook returns 5xx       -> log to stderr, do NOT crash;
                                         alert is still on stdout.
          - Webhook URL malformed     -> validated at startup; the
                                         daemon refuses to start.
          - Wall-clock jumps          -> the BLOCK-keyed sliding
                                         window in hashrate_collapse
                                         is immune; the WALL-CLOCK
                                         sustained_drop sibling will
                                         transiently mis-fire on a
                                         large NTP step but recovers
                                         within the sustained-window.
          - max_reorg_depth missing   -> falls back to --reorg-cap
                                         (200) from CLI.
          - getfinalizedblockhash     -> `RpcUnavailable` -> log once
            RPC missing (older          to stderr and set
            b3chaind w/o M-14)          finalized_rpc_missing_logged;
                                        detect_finalized_drift becomes
                                        a no-op for the lifetime of
                                        this watcher process, the
                                        other detectors keep running.
          - --no-log-tail             -> log_tailer is None,
                                         detect_deep_reorg_log and
                                         detect_pow_budget_storm both
                                         skip; the other detectors
                                         keep running.
          - debug.log missing at      -> _LogTailer.__init__ raises
            startup                     FileNotFoundError; main() logs
                                        once to stderr and constructs
                                        the _Watcher with
                                        log_tailer=None.  Same effect
                                        as --no-log-tail.
          - debug.log rotated under   -> _LogTailer detects an inode
            us (logrotate, manual       change on the next poll,
            mv + touch)                 drains the old fd, reopens at
                                        EOF on the new file.  At most
                                        one poll's worth of writes is
                                        missed between the rotate and
                                        the next stat().
          - debug.log read raises     -> wrapped in
            mid-stream (perms,          `try / except`; lines we
            disk full, FS error)        already drained are still
                                        processed, the rest of the
                                        poll continues.

FAILURE:  - Alert fatigue             -> in-memory `_AlertDedup` keeps
                                         the last emit time per
                                         (kind, signature) tuple and
                                         silently suppresses repeats
                                         inside the dedup window.
          - Detector exception        -> caught around the per-detector
                                         call; logged to stderr; the
                                         daemon keeps running so a bug
                                         in one detector does not blind
                                         the operator to the others.
          - Log-tailer exception      -> wrapped around iter_new_lines()
                                         call AND around each of the
                                         two log-fed detectors; a
                                         broken tailer cannot blind
                                         the four RPC-fed detectors.

Configuration
-------------

Required:
  --rpc-port N            b3chaind RPC port
  --datadir PATH          b3chaind datadir (for cookie auth) OR
  --rpc-user / --rpc-password  fixed user/pass (less common)

Optional (env vars override CLI; CLI overrides defaults):
  WEBHOOK_URL=...         POST alerts here as `application/json`
                          (PagerDuty / Slack / generic JSON sink).
  WATCHER_NOCOLOR=1       force monochrome stdout banner.

See `--help` for the full flag list.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import signal
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from base64 import b64encode
from collections import deque
from pathlib import Path
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Defaults (tunable via CLI)
# ---------------------------------------------------------------------------

DEFAULT_INTERVAL_SEC      = 30.0
DEFAULT_DEEP_FORK_DEPTH   = 6        # blocks
DEFAULT_HASHRATE_WINDOW   = 100      # blocks
DEFAULT_HASHRATE_DROP     = 0.50     # fraction of recent peak
DEFAULT_REORG_CAP         = 200      # consensus.max_reorg_depth (M-4)
DEFAULT_NEAR_REORG_FRAC   = 0.50     # half-cap by default
DEFAULT_DEDUP_WINDOW_SEC  = 300.0    # 5 min
DEFAULT_HTTP_TIMEOUT_SEC  = 10.0
# b3chain M-14: detect_finalized_drift horizon-stall counter.  At the
# default --interval=30s, 5 polls = 2.5 min before the implicit M-4
# horizon being stuck (while tip advances) flags as a stall.
DEFAULT_FINALIZED_STALL_THRESHOLD = 5

# Runbook §0 alignment (this file's second pass; "runbook §0 alerting
# completion" plan).  The four runbook detection triggers map 1:1 to
# the four detectors gated on these defaults.
DEFAULT_LONG_REORG_DEPTH        = 50      # branchlen threshold
DEFAULT_POW_BUDGET_RATE         = 100     # events / hour
DEFAULT_POW_BUDGET_WINDOW_SEC   = 3600.0  # rolling 1h
DEFAULT_HASHRATE_SUSTAINED_DROP = 0.70    # alert when <= 70% of 24h peak
DEFAULT_HASHRATE_SUSTAINED_WIN  = 3600.0  # sustained for >= 1h
DEFAULT_WALLCLOCK_HPS_MAX_AGE   = 86400.0 # 24h peak window

# Log-line markers emitted by validation.cpp / net_processing.cpp.
# Verified against b3chain/src at plan time:
#   src/validation.cpp:4170      "b3pow-budget-exceeded"
#   src/validation.cpp:4806      "deep-reorg-attempt"
#   src/net_processing.cpp:1843  Misbehaving("b3pow-budget-exceeded")
#   src/net_processing.cpp:1850  Misbehaving("deep-reorg-attempt")
LOG_MARKER_DEEP_REORG  = "deep-reorg-attempt"
LOG_MARKER_POW_BUDGET  = "b3pow-budget-exceeded"


# ---------------------------------------------------------------------------
# Cooperative-stop event (set on SIGTERM / SIGINT)
# ---------------------------------------------------------------------------

_stop_event = threading.Event()


def _install_signal_handlers() -> None:
    def _handle(signum: int, _frame: Any) -> None:
        _eprint(f"caught signal {signum}; draining and exiting")
        _stop_event.set()
    # signal.signal must be called from the main thread.
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handle)
        except (ValueError, OSError):
            # E.g. running embedded in a host that already owns the
            # signal slot.  We'll fall back to the bare KeyboardInterrupt
            # path in `_poll_loop()`.
            pass


def _eprint(msg: str) -> None:
    print(f"[51attack-watch] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Minimal JSON-RPC client (cookie or user/pass)
# ---------------------------------------------------------------------------

class RpcUnavailable(RuntimeError):
    pass


class RpcClient:
    def __init__(self, host: str, port: int, auth_header: str,
                 timeout: float = DEFAULT_HTTP_TIMEOUT_SEC):
        self._url = f"http://{host}:{port}/"
        self._headers = {
            "Authorization": auth_header,
            "Content-Type": "application/json",
        }
        self._timeout = timeout
        self._id = 0

    def call(self, method: str, *params: Any) -> Any:
        self._id += 1
        payload = json.dumps({
            "jsonrpc": "1.0",
            "id": str(self._id),
            "method": method,
            "params": list(params),
        }).encode()
        req = urllib.request.Request(self._url, data=payload,
                                     headers=self._headers)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = resp.read()
        except urllib.error.HTTPError as e:
            body = e.read()
        except (urllib.error.URLError, ConnectionError,
                socket.timeout, OSError) as e:
            # b3chaind down, refused, dns dead, etc.  Treated by the
            # outer loop as a recoverable condition that triggers an
            # `rpc_down` alert and continues polling.
            raise RpcUnavailable(str(e)) from e
        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            raise RpcUnavailable(f"non-JSON RPC reply: {e}") from e
        if data.get("error"):
            err = data["error"]
            raise RpcUnavailable(
                f"rpc error {err.get('code', -1)}: {err.get('message', '?')}"
            )
        return data["result"]


def _cookie_auth(datadir: Path, chain: str) -> str:
    """
    Read the cookie file b3chaind drops on startup and turn it into
    a Basic auth header.  Mirrors Bitcoin Core's `-rpccookiefile`
    convention.

    The chain subdir matches `getblockchaininfo.chain` ("main",
    "test", "test4", "signet", "regtest").  We accept a literal
    "_default_" sentinel meaning "no chain subdir" -- that's the
    layout for mainnet, where the cookie lives directly in
    --datadir/.cookie.
    """
    chain_subdir = "" if chain in ("main", "_default_", "") else chain
    cookie_path = datadir / chain_subdir / ".cookie"
    if not cookie_path.is_file():
        raise FileNotFoundError(
            f"RPC cookie not found at {cookie_path}.  Pass --datadir "
            "pointing at b3chaind's datadir, or use --rpc-user / "
            "--rpc-password for fixed-credentials mode."
        )
    raw = cookie_path.read_text().strip()
    token = b64encode(raw.encode()).decode()
    return f"Basic {token}"


def _basic_auth(user: str, password: str) -> str:
    token = b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {token}"


# ---------------------------------------------------------------------------
# Alert dedup
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class _AlertKey:
    kind: str         # e.g. "deep_fork"
    signature: str    # e.g. tip hash, or fork-depth bucket


class _AlertDedup:
    """Suppresses repeats of the same (kind, signature) for `window` seconds."""

    def __init__(self, window_sec: float):
        self._window = window_sec
        self._last_emit: dict[tuple[str, str], float] = {}

    def should_emit(self, key: _AlertKey, now: float) -> bool:
        k = (key.kind, key.signature)
        last = self._last_emit.get(k)
        if last is not None and (now - last) < self._window:
            return False
        self._last_emit[k] = now
        # Garbage-collect anything that fell off the window so the
        # dict doesn't grow unbounded over weeks of uptime.
        stale = [kk for kk, t in self._last_emit.items()
                 if (now - t) > self._window]
        for kk in stale:
            self._last_emit.pop(kk, None)
        return True


# ---------------------------------------------------------------------------
# Log tailer (stdlib-only, inode-rotation aware)
# ---------------------------------------------------------------------------

class _LogTailer:
    """
    Tail `debug.log` from EOF, surface only NEW lines on each poll.

    Used by the runbook §0 trigger #2 (`deep-reorg-attempt`) and trigger
    #3 (`b3pow-budget-exceeded`) detectors.  Polling-driven (not
    inotify-driven) on purpose: the rest of the watcher is a single
    poll loop, and adding an inotify thread would break the "one
    detector failure cannot blind the others" invariant.

    Behaviour:
      - On `__init__` the file is opened, `seek(0, SEEK_END)` is called,
        and the inode (dev, ino) is recorded.  The watcher starts in
        "from now on" mode; we do NOT replay history at startup.
      - `iter_new_lines()` reads every byte appended since the last
        call and returns one alert-ready dict per `\n`-terminated line.
        A trailing partial line (no `\n` yet) is buffered until the
        next call -- this prevents splitting a `Misbehaving(...)` line
        between two polls.
      - Inode rotation (logrotate, manual `mv` + `touch`, etc.) is
        detected by stat'ing the path on every poll.  When inode
        changes we drain the old fd first (so we don't lose the tail of
        the rotated file), then reopen the new file from the start
        (logrotate creates an empty file, so "start" is also "EOF").
      - Any I/O failure (file vanished, permission denied) is caught
        by the caller pattern.  Same pattern as the other detectors.

    The class is intentionally small and pure-ish so the unit tests
    can drive it against a tempfile without needing the rest of the
    watcher.

    LOOP:    iter_new_lines() is called once per outer poll cycle in
             _Watcher.step().  No internal loop / no background thread.
    BYPASS:  - path is None (--no-log-tail)            -> caller skips us
             - path missing at startup                  -> __init__ raises
                                                           FileNotFoundError;
                                                           caller logs once
                                                           to stderr and
                                                           disables log tail
             - inode change                             -> drain old, reopen
             - permission denied mid-stream             -> ignored; next
                                                           poll re-tries
    """

    # Cap how many bytes we'll read in a single poll, so a runaway
    # b3chaind that suddenly dumps gigabytes of log can't OOM the
    # watcher.  4 MB is ~ 20k typical log lines; debug.log on a healthy
    # node grows ~ 100 KB/h.
    _MAX_READ_PER_POLL = 4 * 1024 * 1024

    def __init__(self, path: Path):
        self._path = Path(path)
        self._fh: Any | None = None
        self._inode: tuple[int, int] | None = None
        self._partial: str = ""
        self._open_at_end()

    def _open_at_end(self) -> None:
        # Open in text mode with errors='replace' so a half-written
        # multibyte character on a torn write doesn't kill the daemon.
        fh = self._path.open("r", encoding="utf-8", errors="replace")
        try:
            fh.seek(0, os.SEEK_END)
        except OSError:
            # File can't be seeked (e.g. a pipe substituted by the
            # test harness).  Read from the start instead.
            pass
        st = os.fstat(fh.fileno())
        self._fh = fh
        self._inode = (st.st_dev, st.st_ino)
        self._partial = ""

    def _stat_inode(self) -> tuple[int, int] | None:
        try:
            st = self._path.stat()
        except (FileNotFoundError, PermissionError):
            return None
        return (st.st_dev, st.st_ino)

    def _drain(self) -> list[str]:
        """Read up to _MAX_READ_PER_POLL bytes and return whole lines."""
        out: list[str] = []
        if self._fh is None:
            return out
        try:
            chunk = self._fh.read(self._MAX_READ_PER_POLL)
        except (OSError, ValueError):
            # ValueError = "I/O operation on closed file" if a rotate
            # raced with us.
            return out
        if not chunk:
            return out
        buf = self._partial + chunk
        # Split on '\n' so trailing partial line is preserved.
        parts = buf.split("\n")
        self._partial = parts[-1]
        out.extend(parts[:-1])
        return out

    def iter_new_lines(self) -> list[str]:
        """
        Return every newline-terminated line that has appeared since
        the previous call.  Handles inode rotation transparently.
        Never raises -- I/O failures are observable as an empty list
        and a warning to stderr on the *next* poll once a successful
        reopen happens.
        """
        lines: list[str] = []
        # 1. Drain whatever is already in the current fd.
        lines.extend(self._drain())

        # 2. Check for rotation.  If the file at `self._path` has a
        # different inode than the fd we're holding, the operator (or
        # logrotate) just rotated under us.  Drain a second time on the
        # OLD fd (to catch anything written between (1) and the rotate),
        # then reopen on the new file.
        new_inode = self._stat_inode()
        if new_inode is not None and new_inode != self._inode:
            try:
                lines.extend(self._drain())
            except Exception:  # noqa: BLE001 -- defensive
                pass
            try:
                if self._fh is not None:
                    self._fh.close()
            except OSError:
                pass
            try:
                self._open_at_end()
                # Logrotate creates the new file empty, so the next
                # _drain() returns nothing; that's fine.
            except (FileNotFoundError, PermissionError) as e:
                _eprint(f"log tailer: reopen after rotation failed ({e})")
                self._fh = None
                self._inode = None
        return lines

    def close(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None


# ---------------------------------------------------------------------------
# Detectors (each emits a list[dict] of structured alerts)
# ---------------------------------------------------------------------------

def detect_deep_fork(tips: list[dict], threshold: int) -> list[dict]:
    """
    Any non-active tip with branchlen >= threshold is reported.

    Maps to F-2 mitigation (deep-fork early-warning) and to the
    `getchaintips` row of doc/security/RESPONSE-RUNBOOK-51ATTACK.md.
    """
    out: list[dict] = []
    for t in tips:
        if t.get("status") == "active":
            continue
        branchlen = int(t.get("branchlen", 0))
        if branchlen >= threshold:
            out.append({
                "kind": "deep_fork",
                "tip_hash":   t.get("hash", ""),
                "tip_height": int(t.get("height", -1)),
                "branchlen":  branchlen,
                "status":     t.get("status", "unknown"),
                "severity":   ("critical" if branchlen >= threshold * 4
                               else "warning"),
                "message": (
                    f"non-active tip {t.get('hash', '?')[:12]}... at "
                    f"branchlen={branchlen} (>= {threshold})"
                ),
            })
    return out


def detect_long_reorg(tips: list[dict], threshold: int) -> list[dict]:
    """
    Runbook §0 trigger #1 ("long deep reorg, depth > 50, NOT yet at
    `max_reorg_depth=200` cap").

    Same `getchaintips` shape as `detect_deep_fork` but a wider
    threshold and a separate `kind` so the war-room sees a 1:1 mapping
    between the runbook row and the alert.

    Severity scales linearly:
      branchlen >= threshold              -> warning
      branchlen >= 2 * threshold          -> critical
    """
    out: list[dict] = []
    for t in tips:
        if t.get("status") == "active":
            continue
        branchlen = int(t.get("branchlen", 0))
        if branchlen >= threshold:
            severity = "critical" if branchlen >= threshold * 2 else "warning"
            out.append({
                "kind": "long_reorg",
                "tip_hash":   t.get("hash", ""),
                "tip_height": int(t.get("height", -1)),
                "branchlen":  branchlen,
                "status":     t.get("status", "unknown"),
                "threshold":  threshold,
                "severity":   severity,
                "message": (
                    f"non-active tip {t.get('hash', '?')[:12]}... at "
                    f"branchlen={branchlen} (>= long-reorg threshold "
                    f"{threshold}); consider M-14 finalizeblock"
                ),
            })
    return out


def detect_deep_reorg_log(lines: Iterable[str], now: float) -> list[dict]:
    """
    Runbook §0 trigger #2 (`BLOCK_DEEP_REORG` rejections in debug.log,
    threshold = any).

    Scans each new debug.log line for the LOG_MARKER_DEEP_REORG token
    (verified against `src/validation.cpp:4806` and
    `src/net_processing.cpp:1850`).  Returns one alert per matching
    line; the alert's dedup signature (set by the caller) is the sha1
    of the line so the SAME `Misbehaving("deep-reorg-attempt")` event
    is silenced inside the dedup window but a DIFFERENT one re-fires.

    The marker `deep-reorg-attempt` is unambiguous -- it only appears
    in those two source sites and never in any benign log line -- so a
    simple substring match is safe.  We deliberately do NOT try to
    parse the surrounding context (peer id, depth, etc.); the operator
    is going to `grep debug.log` anyway and the JSONL alert is just
    the war-room page.
    """
    out: list[dict] = []
    for line in lines:
        if LOG_MARKER_DEEP_REORG not in line:
            continue
        sig = hashlib.sha1(line.encode("utf-8", "replace")).hexdigest()[:16]
        out.append({
            "kind":      "deep_reorg_log",
            "severity":  "critical",
            "marker":    LOG_MARKER_DEEP_REORG,
            "line":      line.strip()[:512],  # cap log line length
            "signature": sig,
            "message": (
                "debug.log: deep-reorg-attempt rejection observed -- "
                "attacker tried to push a >max_reorg_depth reorg "
                "(see RESPONSE-RUNBOOK-51ATTACK.md §0 trigger #2)"
            ),
        })
    return out


def detect_pow_budget_storm(timestamps: deque[float],
                            threshold: int,
                            window_sec: float,
                            now: float) -> list[dict]:
    """
    Runbook §0 trigger #3 (mass `BLOCK_POW_BUDGET` rejections, > 100/h).

    `timestamps` is a deque of UNIX-seconds floats; the caller appends
    one entry per `b3pow-budget-exceeded` log line.  We trim entries
    older than `now - window_sec` first (cheap, since timestamps are
    appended in order) and then compare `len(timestamps)` to threshold.

    Severity:
      count > threshold        -> warning
      count > 4 * threshold    -> critical

    The caller is responsible for de-duplicating the alert per poll;
    we just return at most one alert per call.
    """
    cutoff = now - window_sec
    # Trim front (oldest); caller may rely on the side-effect.
    while timestamps and timestamps[0] < cutoff:
        timestamps.popleft()
    count = len(timestamps)
    if count <= threshold:
        return []
    severity = "critical" if count > threshold * 4 else "warning"
    bucket = (count // 50) * 50  # dedup-friendly bucket
    return [{
        "kind":          "pow_budget_storm",
        "count":         count,
        "threshold":     threshold,
        "window_sec":    window_sec,
        "rate_per_hour": count * 3600.0 / window_sec,
        "bucket":        bucket,
        "severity":      severity,
        "message": (
            f"debug.log: {count} b3pow-budget-exceeded rejections in "
            f"the last {int(window_sec)}s (> {threshold} threshold); "
            f"verifier DoS storm in progress"
        ),
    }]


def detect_hashrate_sustained_drop(
    samples: deque[tuple[float, float]],
    drop_frac: float,
    window_sec: float,
    now: float,
) -> list[dict]:
    """
    Runbook §0 trigger #4 ("sudden hashrate drop (>30%) sustained
    >1h", verified by block timestamps vs LWMA-3).

    `samples` is a wall-clock-keyed deque of `(unix_ts, hps)` pairs --
    one per poll cycle, trimmed by the caller to ~24h.

    Distinct from `detect_hashrate_collapse`, which is block-height-
    keyed (100-block window) and is the SECURITY-ROADMAP §9
    deliverable's tuned defaults.  This sibling is wall-clock-keyed
    because the runbook explicitly says "sustained > 1 hour".

    Alert fires when EVERY sample inside the trailing `window_sec`
    has `hps <= drop_frac * peak_over_24h`.  That is, the drop must
    be sustained for the whole window -- a single transient blip
    does not page.

    Severity:
      sustained >= window_sec        -> warning
      sustained >= 2 * window_sec    -> critical
    """
    if len(samples) < 2:
        return []
    peak = max(hps for _, hps in samples)
    if peak <= 0.0:
        return []
    threshold_hps = drop_frac * peak
    # Two-pass algorithm:
    #   1. Confirm EVERY sample inside the trailing window_sec is
    #      <= threshold (i.e. the drop is sustained for the whole
    #      configured window).  If any sample in the window is above
    #      the threshold, the drop is not sustained -- return [].
    #   2. To determine SEVERITY (warning vs critical), walk backwards
    #      from `now` and find the earliest contiguous run of
    #      below-threshold samples.  `sustained_for = now - earliest`.
    #      A drop sustained for >= 2 * window_sec is critical.
    window_start = now - window_sec
    seen_in_window = False
    for ts, hps in samples:
        if ts < window_start:
            continue
        seen_in_window = True
        if hps > threshold_hps:
            return []
    if not seen_in_window:
        return []
    # Find earliest contiguous below-threshold sample (severity input).
    earliest_under: float | None = None
    for ts, hps in samples:
        if hps > threshold_hps:
            earliest_under = None
            continue
        if earliest_under is None:
            earliest_under = ts
    if earliest_under is None:
        return []
    sustained_for = now - earliest_under
    if sustained_for < window_sec:
        return []
    latest_ts, latest_hps = samples[-1]
    ratio = latest_hps / peak if peak > 0 else 0.0
    severity = "critical" if sustained_for >= window_sec * 2 else "warning"
    return [{
        "kind":           "hashrate_sustained_drop",
        "sustained_sec":  sustained_for,
        "window_sec":     window_sec,
        "peak_hashps":    peak,
        "latest_hashps":  latest_hps,
        "drop_frac":      drop_frac,
        "ratio":          ratio,
        "severity":       severity,
        "message": (
            f"hashrate {latest_hps:.3e} ({ratio*100:.1f}% of 24h peak "
            f"{peak:.3e}) has stayed <= {drop_frac*100:.0f}% for "
            f"{int(sustained_for)}s (>= {int(window_sec)}s sustained "
            f"window)"
        ),
    }]


def detect_hashrate_collapse(samples: deque[tuple[int, float]],
                             drop_frac: float) -> list[dict]:
    """
    Returns one alert if the latest sample is <= `drop_frac` * max(window).

    `samples` is a (height, networkhashps) deque.  The window is the
    deque itself -- the caller maintains its length.  Block height is
    the abscissa so a wall-clock jump on the host machine cannot fake
    a collapse.
    """
    if len(samples) < 2:
        return []
    latest_height, latest_hps = samples[-1]
    peak_hps = max(hps for _, hps in samples)
    if peak_hps <= 0.0:
        return []
    ratio = latest_hps / peak_hps
    if ratio > drop_frac:
        return []
    return [{
        "kind": "hashrate_collapse",
        "window_blocks": len(samples),
        "peak_hashps":   peak_hps,
        "latest_hashps": latest_hps,
        "ratio":         ratio,
        "height":        latest_height,
        "severity":      ("critical" if ratio <= drop_frac * 0.5
                          else "warning"),
        "message": (
            f"network hashps={latest_hps:.3e} is {ratio*100:.1f}% of "
            f"recent peak {peak_hps:.3e} over last {len(samples)} blocks"
        ),
    }]


def detect_finalized_drift(prev_state: dict | None,
                           current: dict,
                           tip_height: int,
                           stale_threshold: int) -> list[dict]:
    """
    b3chain M-14: detect drift of the finalization horizon vs the tip.

    `current` is the dict returned by the `getfinalizedblockhash` RPC:
        {"hash": str, "height": int, "source": "operator" | "max_reorg_depth"}
    `prev_state` is what this detector returned last time as its
    "next prev state" -- a dict of the same shape plus a stale_count.
    `tip_height` is the current ActiveTip().nHeight.
    `stale_threshold` is how many consecutive polls the
    max_reorg_depth horizon can remain at the same height (while tip
    advances) before we alert.

    Three alert conditions:

      finalized_drift_source_flip      -- source changed since last
                                          poll (e.g. operator just ran
                                          `unfinalizeblock` -> source
                                          flipped from "operator" to
                                          "max_reorg_depth").  Info-
                                          severity; expected during
                                          legitimate operator action.

      finalized_drift_operator_change  -- source stayed "operator" but
                                          hash changed (= operator
                                          re-finalized at a different
                                          height).  Warning -- a
                                          re-finalize while watcher is
                                          live is unusual.

      finalized_drift_horizon_stall    -- source is "max_reorg_depth"
                                          and height did not advance
                                          for `stale_threshold`
                                          consecutive polls while
                                          `tip_height` did.  Warning;
                                          signals the tip is stuck
                                          (M-4 horizon = tip - cap).

    Pure function: no I/O; the caller maintains prev_state.
    """
    out: list[dict] = []
    src      = current.get("source", "")
    height   = int(current.get("height", -1))
    hash_str = current.get("hash", "")

    if prev_state is None:
        # First poll: nothing to compare against.
        return out

    prev_src      = prev_state.get("source", "")
    prev_height   = int(prev_state.get("height", -1))
    prev_hash     = prev_state.get("hash", "")

    if src != prev_src:
        out.append({
            "kind":         "finalized_drift_source_flip",
            "prev_source":  prev_src,
            "new_source":   src,
            "prev_hash":    prev_hash,
            "new_hash":     hash_str,
            "new_height":   height,
            "severity":     "info",
            "message": (
                f"finalization source changed: {prev_src!r} -> {src!r} "
                f"(height {prev_height} -> {height})"
            ),
        })
    elif src == "operator" and hash_str != prev_hash:
        out.append({
            "kind":         "finalized_drift_operator_change",
            "prev_hash":    prev_hash,
            "new_hash":     hash_str,
            "prev_height":  prev_height,
            "new_height":   height,
            "severity":     "warning",
            "message": (
                f"operator-finalized block changed without source flip: "
                f"{prev_hash[:12]}@{prev_height} -> {hash_str[:12]}@{height}"
            ),
        })

    # Horizon-stall check (only meaningful for the implicit M-4 case).
    if src == "max_reorg_depth":
        prev_tip = prev_state.get("tip_height_at_obs", -1)
        stale    = int(prev_state.get("stale_count", 0))
        if height == prev_height and tip_height > prev_tip and prev_tip >= 0:
            stale += 1
        else:
            stale = 0
        if stale >= stale_threshold:
            out.append({
                "kind":              "finalized_drift_horizon_stall",
                "height":            height,
                "tip_height":        tip_height,
                "stale_polls":       stale,
                "stale_threshold":   stale_threshold,
                "severity":          ("critical" if stale >= stale_threshold * 2
                                      else "warning"),
                "message": (
                    f"M-4 horizon stuck at height {height} for {stale} polls "
                    f"while tip advanced to {tip_height}"
                ),
            })
        # The caller will overwrite prev_state with our latest values; we
        # pass the updated stale_count back via a sentinel in the dict so
        # the caller doesn't have to know our internal accounting.
        current["__stale_count__"] = stale
    else:
        current["__stale_count__"] = 0
    current["__tip_height_at_obs__"] = tip_height
    return out


def detect_near_reorg_cap(prev_tip_hash: str | None,
                          new_tip_hash: str,
                          new_tip_height: int,
                          prev_tip_height: int | None,
                          common_ancestor_height: int | None,
                          near_threshold: int) -> list[dict]:
    """
    When the active tip changes such that the common ancestor is more
    than `near_threshold` blocks behind the previous tip, we are
    approaching the M-4 max_reorg_depth cap.
    """
    if prev_tip_hash is None or prev_tip_height is None:
        return []
    if new_tip_hash == prev_tip_hash:
        return []
    if common_ancestor_height is None:
        return []
    reorg_depth = prev_tip_height - common_ancestor_height
    if reorg_depth < near_threshold:
        return []
    return [{
        "kind": "near_reorg_cap",
        "prev_tip_hash":       prev_tip_hash,
        "new_tip_hash":        new_tip_hash,
        "prev_tip_height":     prev_tip_height,
        "new_tip_height":      new_tip_height,
        "common_ancestor":     common_ancestor_height,
        "reorg_depth":         reorg_depth,
        "near_threshold":      near_threshold,
        "severity":            "critical",
        "message": (
            f"chain reorged by {reorg_depth} blocks (>= half of M-4 cap, "
            f"common ancestor at height {common_ancestor_height})"
        ),
    }]


# ---------------------------------------------------------------------------
# Common-ancestor finder (server-side via getchaintips ancestors)
# ---------------------------------------------------------------------------

def _common_ancestor_height(rpc: RpcClient,
                            new_tip_hash: str,
                            prev_tip_hash: str) -> int | None:
    """
    Walk back from the longer of the two tips via getblockheader until
    we find a height shared by the other branch.  Best-effort: caps
    at 1024 hops to bound RPC cost.
    """
    try:
        new_h = rpc.call("getblockheader", new_tip_hash, True)
        prev_h = rpc.call("getblockheader", prev_tip_hash, True)
    except RpcUnavailable:
        return None
    if "height" not in new_h or "height" not in prev_h:
        return None
    cur_hash = new_tip_hash if new_h["height"] >= prev_h["height"] else prev_tip_hash
    cur_height = max(new_h["height"], prev_h["height"])
    target_branch_hash = prev_tip_hash if cur_hash == new_tip_hash else new_tip_hash

    seen: dict[int, str] = {}
    # Map all heights along the *other* branch first so we can detect
    # the shared ancestor in one pass.
    other_hash = target_branch_hash
    for _ in range(1024):
        try:
            h = rpc.call("getblockheader", other_hash, True)
        except RpcUnavailable:
            return None
        if "height" not in h:
            return None
        seen[h["height"]] = other_hash
        if h.get("previousblockhash") is None:
            break
        other_hash = h["previousblockhash"]

    for _ in range(1024):
        if cur_height in seen and seen[cur_height] == cur_hash:
            return cur_height
        try:
            h = rpc.call("getblockheader", cur_hash, True)
        except RpcUnavailable:
            return None
        if "previousblockhash" not in h:
            return None
        cur_hash = h["previousblockhash"]
        cur_height = h["height"] - 1
        if cur_height < 0:
            return None
    return None


# ---------------------------------------------------------------------------
# Webhook POST (best-effort; failures do NOT propagate)
# ---------------------------------------------------------------------------

def _post_webhook(url: str, payload: dict, timeout: float) -> None:
    """
    Best-effort JSON POST.  Any error (5xx, DNS, timeout) is logged to
    stderr and swallowed -- the alert is still on stdout, which is the
    authoritative sink.
    """
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status >= 500:
                _eprint(f"webhook returned {resp.status}; alert was "
                        f"still emitted to stdout")
    except urllib.error.HTTPError as e:
        _eprint(f"webhook HTTP {e.code}: {e.reason}; alert was still "
                f"emitted to stdout")
    except (urllib.error.URLError, socket.timeout, ConnectionError) as e:
        _eprint(f"webhook unreachable ({e}); alert was still emitted "
                f"to stdout")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class _Watcher:
    rpc: RpcClient
    interval_sec: float
    deep_fork_depth: int
    hashrate_window: int
    hashrate_drop_frac: float
    near_reorg_threshold: int
    dedup: _AlertDedup
    webhook_url: str | None
    http_timeout: float
    finalized_stall_threshold: int = 5
    # Runbook §0 alignment: long-reorg (trigger #1), pow-budget storm
    # (trigger #3), wall-clock sustained hashrate drop (trigger #4),
    # plus the log tailer that feeds the deep_reorg_log + pow_budget
    # detectors (triggers #2 + #3).
    long_reorg_depth: int = DEFAULT_LONG_REORG_DEPTH
    pow_budget_rate: int = DEFAULT_POW_BUDGET_RATE
    pow_budget_window_sec: float = DEFAULT_POW_BUDGET_WINDOW_SEC
    hashrate_sustained_drop_frac: float = DEFAULT_HASHRATE_SUSTAINED_DROP
    hashrate_sustained_window_sec: float = DEFAULT_HASHRATE_SUSTAINED_WIN
    wallclock_hps_max_age_sec: float = DEFAULT_WALLCLOCK_HPS_MAX_AGE
    log_tailer: _LogTailer | None = None
    pow_budget_events: deque[float] = dataclasses.field(default_factory=deque)
    wallclock_hps_samples: deque[tuple[float, float]] = dataclasses.field(
        default_factory=deque)
    hashrate_samples: deque[tuple[int, float]] = dataclasses.field(
        default_factory=deque)
    last_tip_hash: str | None = None
    last_tip_height: int | None = None
    # b3chain M-14: prior observation of `getfinalizedblockhash` so the
    # detect_finalized_drift detector can compare poll-to-poll.  Shape
    # matches what detect_finalized_drift returns via its `current`
    # mutation contract (see __stale_count__ / __tip_height_at_obs__).
    last_finalized_obs: dict | None = None
    # Set true once we've logged the "RPC not present" warning once;
    # used to avoid spamming stderr on every poll against an older node.
    finalized_rpc_missing_logged: bool = False

    def emit(self, alert: dict) -> None:
        """Print the alert as a JSONL line; optionally POST to webhook."""
        alert.setdefault("ts", int(time.time()))
        alert.setdefault("source", "51attack-watch")
        print(json.dumps(alert, separators=(",", ":"), sort_keys=True),
              flush=True)
        if self.webhook_url:
            _post_webhook(self.webhook_url, alert, self.http_timeout)

    def emit_dedup(self, alert: dict, key: _AlertKey, now: float) -> None:
        if not self.dedup.should_emit(key, now):
            return
        self.emit(alert)

    def step(self) -> None:
        """
        One iteration of the polling loop.  Catches RpcUnavailable so
        a node-down condition surfaces as an alert and the loop
        continues.  Catches any other Exception so a bug in one
        detector does not silence the others.
        """
        now = time.time()
        try:
            info = self.rpc.call("getblockchaininfo")
            tips = self.rpc.call("getchaintips")
            try:
                hps = float(self.rpc.call("getnetworkhashps",
                                          self.hashrate_window))
            except RpcUnavailable:
                hps = -1.0  # leave the sample unchanged this iter
        except RpcUnavailable as e:
            self.emit_dedup(
                {
                    "kind":     "rpc_down",
                    "severity": "warning",
                    "message":  f"b3chaind RPC unavailable: {e}",
                },
                _AlertKey(kind="rpc_down", signature="rpc_down"),
                now,
            )
            return

        # Detector 1: deep non-active forks.
        try:
            for a in detect_deep_fork(tips, self.deep_fork_depth):
                key = _AlertKey(kind="deep_fork",
                                signature=a["tip_hash"])
                self.emit_dedup(a, key, now)
        except Exception as e:
            _eprint(f"detect_deep_fork raised: {e}; continuing")

        # Detector 1b (RUNBOOK §0 trigger #1): long-reorg threshold
        # (default 50), sits between deep_fork (>=6) and near_reorg_cap
        # (>=100).  Same getchaintips data, different bucket.
        try:
            for a in detect_long_reorg(tips, self.long_reorg_depth):
                key = _AlertKey(kind="long_reorg",
                                signature=a["tip_hash"])
                self.emit_dedup(a, key, now)
        except Exception as e:
            _eprint(f"detect_long_reorg raised: {e}; continuing")

        # Detector 2: hashrate collapse (height-keyed sliding window).
        try:
            cur_height = int(info.get("blocks", -1))
            if hps > 0 and cur_height >= 0:
                # Replace any existing sample for this height (we may
                # re-poll within the same block during a fast loop).
                if self.hashrate_samples and \
                   self.hashrate_samples[-1][0] == cur_height:
                    self.hashrate_samples[-1] = (cur_height, hps)
                else:
                    self.hashrate_samples.append((cur_height, hps))
                # Trim to the window.
                while len(self.hashrate_samples) > self.hashrate_window:
                    self.hashrate_samples.popleft()
            for a in detect_hashrate_collapse(self.hashrate_samples,
                                              self.hashrate_drop_frac):
                # Dedup signature is the rounded ratio bucket so we
                # don't alert again unless the situation worsens (or
                # recovers and re-collapses).
                bucket = f"{a['ratio']:.1f}"
                key = _AlertKey(kind="hashrate_collapse", signature=bucket)
                self.emit_dedup(a, key, now)
        except Exception as e:
            _eprint(f"detect_hashrate_collapse raised: {e}; continuing")

        # Detector 2b (RUNBOOK §0 trigger #4): wall-clock sustained
        # hashrate drop (default <= 70% of 24h peak sustained >= 1h).
        # Distinct from Detector 2 above which is block-window keyed.
        try:
            if hps > 0:
                self.wallclock_hps_samples.append((now, hps))
            # Trim samples older than the configured 24h max age.
            wallclock_cutoff = now - self.wallclock_hps_max_age_sec
            while (self.wallclock_hps_samples
                   and self.wallclock_hps_samples[0][0] < wallclock_cutoff):
                self.wallclock_hps_samples.popleft()
            for a in detect_hashrate_sustained_drop(
                self.wallclock_hps_samples,
                self.hashrate_sustained_drop_frac,
                self.hashrate_sustained_window_sec,
                now,
            ):
                # Dedup signature: severity bucket so a single
                # sustained event doesn't re-page every poll, but a
                # warning -> critical transition does.
                key = _AlertKey(
                    kind="hashrate_sustained_drop",
                    signature=a["severity"],
                )
                self.emit_dedup(a, key, now)
        except Exception as e:
            _eprint(
                f"detect_hashrate_sustained_drop raised: {e}; continuing"
            )

        # Detector 3: near M-4 reorg cap.
        try:
            new_tip_hash = info.get("bestblockhash", "")
            new_tip_height = int(info.get("blocks", -1))
            if new_tip_hash and self.last_tip_hash \
               and new_tip_hash != self.last_tip_hash:
                common = _common_ancestor_height(
                    self.rpc, new_tip_hash, self.last_tip_hash
                )
                for a in detect_near_reorg_cap(
                    self.last_tip_hash, new_tip_hash,
                    new_tip_height, self.last_tip_height,
                    common, self.near_reorg_threshold,
                ):
                    sig = f"{a['common_ancestor']}-{a['new_tip_hash'][:12]}"
                    key = _AlertKey(kind="near_reorg_cap", signature=sig)
                    self.emit_dedup(a, key, now)
            if new_tip_hash:
                self.last_tip_hash = new_tip_hash
                self.last_tip_height = new_tip_height
        except Exception as e:
            _eprint(f"detect_near_reorg_cap raised: {e}; continuing")

        # Detector 4 (b3chain M-14): finalization-horizon drift.  Polls
        # the new `getfinalizedblockhash` RPC and compares to the prior
        # observation.  BYPASS path: an older b3chaind without the
        # M-14 RPC will return "Method not found" (RpcUnavailable);
        # we log once to stderr and silently skip the detector so the
        # daemon stays useful on mixed-version monitoring fleets.
        try:
            try:
                fin_obs = self.rpc.call("getfinalizedblockhash")
            except RpcUnavailable as e:
                if not self.finalized_rpc_missing_logged:
                    _eprint(
                        "getfinalizedblockhash RPC unavailable "
                        f"({e}); skipping detect_finalized_drift this "
                        "loop and on subsequent polls (older b3chaind?)"
                    )
                    self.finalized_rpc_missing_logged = True
                fin_obs = None
            if fin_obs is not None:
                tip_h = int(info.get("blocks", -1))
                for a in detect_finalized_drift(
                    self.last_finalized_obs, fin_obs, tip_h,
                    self.finalized_stall_threshold,
                ):
                    sig = f"{a['kind']}-{a.get('new_height', a.get('height', '?'))}"
                    key = _AlertKey(kind=a["kind"], signature=sig)
                    self.emit_dedup(a, key, now)
                # Persist for next iteration.  detect_finalized_drift
                # has annotated fin_obs in-place with the stale-counter
                # bookkeeping the next call needs.
                self.last_finalized_obs = {
                    "hash":               fin_obs.get("hash", ""),
                    "height":             int(fin_obs.get("height", -1)),
                    "source":             fin_obs.get("source", ""),
                    "stale_count":        fin_obs.get("__stale_count__", 0),
                    "tip_height_at_obs":  fin_obs.get(
                        "__tip_height_at_obs__", tip_h),
                }
        except Exception as e:
            _eprint(f"detect_finalized_drift raised: {e}; continuing")

        # Detectors 5 + 6 (RUNBOOK §0 triggers #2 + #3): debug.log
        # tail.  The tailer is None either because --no-log-tail was
        # passed or because the log file was missing at startup (the
        # constructor logged once and the watcher is running in
        # RPC-only mode).  Both bypass paths simply skip these
        # detectors, the other four keep running.
        if self.log_tailer is not None:
            try:
                new_lines = self.log_tailer.iter_new_lines()
            except Exception as e:
                _eprint(f"_LogTailer raised: {e}; continuing")
                new_lines = []
            # Detector 5: BLOCK_DEEP_REORG rejection lines (trigger #2,
            # threshold = any).
            try:
                for a in detect_deep_reorg_log(new_lines, now):
                    key = _AlertKey(kind="deep_reorg_log",
                                    signature=a["signature"])
                    self.emit_dedup(a, key, now)
            except Exception as e:
                _eprint(
                    f"detect_deep_reorg_log raised: {e}; continuing"
                )
            # Detector 6: BLOCK_POW_BUDGET storm (trigger #3, default
            # > 100 / hour).  Append timestamps THEN run the detector;
            # the detector itself trims stale entries past the window.
            try:
                for line in new_lines:
                    if LOG_MARKER_POW_BUDGET in line:
                        self.pow_budget_events.append(now)
                for a in detect_pow_budget_storm(
                    self.pow_budget_events,
                    self.pow_budget_rate,
                    self.pow_budget_window_sec,
                    now,
                ):
                    # Dedup signature is the rounded count bucket so
                    # a sustained storm doesn't repage every poll.
                    key = _AlertKey(
                        kind="pow_budget_storm",
                        signature=f"{a['bucket']}-{a['severity']}",
                    )
                    self.emit_dedup(a, key, now)
            except Exception as e:
                _eprint(
                    f"detect_pow_budget_storm raised: {e}; continuing"
                )

    def run(self) -> None:
        _eprint(
            f"started; interval={self.interval_sec}s, "
            f"deep_fork_depth={self.deep_fork_depth}, "
            f"long_reorg_depth={self.long_reorg_depth}, "
            f"hashrate_window={self.hashrate_window} blocks @ "
            f"<= {self.hashrate_drop_frac*100:.0f}%, "
            f"sustained_drop <= {self.hashrate_sustained_drop_frac*100:.0f}% "
            f"for {int(self.hashrate_sustained_window_sec)}s, "
            f"pow_budget_rate>{self.pow_budget_rate} "
            f"per {int(self.pow_budget_window_sec)}s, "
            f"near_reorg>={self.near_reorg_threshold}, "
            f"log_tailer={'on' if self.log_tailer is not None else 'OFF'}, "
            f"dedup={self.dedup._window:.0f}s"
        )
        # The polling LOOP.  Required by tiered-verification.mdc Tier 3:
        # this is the explicit `while True ...` body that the
        # comment-to-code map points at.
        while not _stop_event.is_set():
            self.step()
            # Sleeps are interruptible (Event.wait returns early when
            # _stop_event is set), so SIGTERM doesn't have to wait for
            # the full interval before the daemon exits.
            _stop_event.wait(self.interval_sec)
        _eprint("stop event observed; exiting")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--rpc-host", default="127.0.0.1")
    p.add_argument("--rpc-port", type=int, required=True,
                   help="b3chaind RPC port (mainnet 8532, testnet "
                        "18533, regtest -rpcport=...)")

    auth = p.add_mutually_exclusive_group(required=True)
    auth.add_argument("--datadir", type=Path, default=None,
                      help="b3chaind datadir; read RPC cookie "
                           "from <datadir>/<chain>/.cookie")
    auth.add_argument("--rpc-user", default=None,
                      help="fixed RPC user (must pair with --rpc-password)")
    p.add_argument("--rpc-password", default=None,
                   help="fixed RPC password (must pair with --rpc-user)")
    p.add_argument("--chain", default="main",
                   help="chain subdir for cookie auth: main / test / "
                        "test4 / signet / regtest (default: main)")

    p.add_argument("--interval", type=float, default=DEFAULT_INTERVAL_SEC,
                   help=f"poll interval in seconds "
                        f"(default {DEFAULT_INTERVAL_SEC:.0f})")
    p.add_argument("--deep-fork-depth", type=int,
                   default=DEFAULT_DEEP_FORK_DEPTH,
                   help=f"branchlen at which to alert on a non-active "
                        f"tip (default {DEFAULT_DEEP_FORK_DEPTH})")
    p.add_argument("--hashrate-window", type=int,
                   default=DEFAULT_HASHRATE_WINDOW,
                   help=f"sliding-window length in BLOCKS for the "
                        f"hashrate-collapse detector "
                        f"(default {DEFAULT_HASHRATE_WINDOW})")
    p.add_argument("--hashrate-drop", type=float,
                   default=DEFAULT_HASHRATE_DROP,
                   help=f"alert when latest hps falls to <= this "
                        f"fraction of the recent peak "
                        f"(default {DEFAULT_HASHRATE_DROP})")
    p.add_argument("--reorg-cap", type=int, default=DEFAULT_REORG_CAP,
                   help=f"consensus.max_reorg_depth (M-4); "
                        f"default {DEFAULT_REORG_CAP}")
    p.add_argument("--near-reorg-fraction", type=float,
                   default=DEFAULT_NEAR_REORG_FRAC,
                   help=f"fraction of --reorg-cap at which to alert "
                        f"(default {DEFAULT_NEAR_REORG_FRAC})")
    p.add_argument("--dedup-window", type=float,
                   default=DEFAULT_DEDUP_WINDOW_SEC,
                   help=f"silence repeats of the same (kind, "
                        f"signature) for this many seconds "
                        f"(default {DEFAULT_DEDUP_WINDOW_SEC:.0f})")
    p.add_argument("--http-timeout", type=float,
                   default=DEFAULT_HTTP_TIMEOUT_SEC,
                   help=f"RPC + webhook timeout in seconds "
                        f"(default {DEFAULT_HTTP_TIMEOUT_SEC:.0f})")
    p.add_argument("--finalized-stall-threshold", type=int,
                   default=DEFAULT_FINALIZED_STALL_THRESHOLD,
                   help=f"M-14 finalization horizon stall threshold "
                        f"in poll cycles (default "
                        f"{DEFAULT_FINALIZED_STALL_THRESHOLD})")
    # Runbook §0 alignment: triggers #1..#4 each have a dedicated flag.
    p.add_argument("--long-reorg-depth", type=int,
                   default=DEFAULT_LONG_REORG_DEPTH,
                   help=f"branchlen threshold for the long_reorg "
                        f"detector (RUNBOOK §0 trigger #1; default "
                        f"{DEFAULT_LONG_REORG_DEPTH}, sits between "
                        f"deep_fork=6 and near_reorg_cap=100)")
    p.add_argument("--debug-log", default=None,
                   help="path to b3chaind debug.log for log-tail "
                        "detectors (RUNBOOK §0 triggers #2 + #3); "
                        "defaults to <datadir>/<chain-subdir>/debug.log "
                        "when --datadir is used")
    p.add_argument("--no-log-tail", action="store_true",
                   help="disable the debug.log tailer entirely (use "
                        "when watcher runs off-host from b3chaind); "
                        "trigger #2 and #3 will be silenced")
    p.add_argument("--pow-budget-rate", type=int,
                   default=DEFAULT_POW_BUDGET_RATE,
                   help=f"alert when b3pow-budget-exceeded log-line "
                        f"count exceeds this in the trailing window "
                        f"(RUNBOOK §0 trigger #3; default "
                        f"{DEFAULT_POW_BUDGET_RATE})")
    p.add_argument("--pow-budget-window", type=float,
                   default=DEFAULT_POW_BUDGET_WINDOW_SEC,
                   help=f"trailing-window length in SECONDS for the "
                        f"pow_budget_storm detector (default "
                        f"{DEFAULT_POW_BUDGET_WINDOW_SEC:.0f})")
    p.add_argument("--hashrate-sustained-drop", type=float,
                   default=DEFAULT_HASHRATE_SUSTAINED_DROP,
                   help=f"alert when wall-clock hps stays <= this "
                        f"fraction of the 24h peak for the sustained "
                        f"window (RUNBOOK §0 trigger #4; default "
                        f"{DEFAULT_HASHRATE_SUSTAINED_DROP})")
    p.add_argument("--hashrate-sustained-window", type=float,
                   default=DEFAULT_HASHRATE_SUSTAINED_WIN,
                   help=f"how many SECONDS the drop must be sustained "
                        f"before alerting (default "
                        f"{DEFAULT_HASHRATE_SUSTAINED_WIN:.0f})")
    p.add_argument("--wallclock-hps-max-age", type=float,
                   default=DEFAULT_WALLCLOCK_HPS_MAX_AGE,
                   help=f"how many SECONDS of wall-clock hashrate "
                        f"history to retain for the sustained-drop "
                        f"peak calculation (default "
                        f"{DEFAULT_WALLCLOCK_HPS_MAX_AGE:.0f})")
    p.add_argument("--webhook-url", default=None,
                   help="POST every alert as JSON to this URL.  Env "
                        "var WEBHOOK_URL takes precedence if set.")
    p.add_argument("--one-shot", action="store_true",
                   help="run a single poll cycle and exit (smoke test)")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    # --rpc-user requires --rpc-password.
    if args.rpc_user is not None and args.rpc_password is None:
        _eprint("--rpc-user requires --rpc-password")
        return 2

    # Build auth header.
    if args.rpc_user is not None:
        auth_header = _basic_auth(args.rpc_user, args.rpc_password)
    else:
        try:
            auth_header = _cookie_auth(args.datadir, args.chain)
        except FileNotFoundError as e:
            _eprint(str(e))
            return 2

    rpc = RpcClient(args.rpc_host, args.rpc_port, auth_header,
                    timeout=args.http_timeout)

    # Validate webhook URL early so the daemon refuses to start with a
    # broken config rather than silently dropping every alert.
    webhook_url = os.environ.get("WEBHOOK_URL") or args.webhook_url
    if webhook_url is not None:
        if not (webhook_url.startswith("http://")
                or webhook_url.startswith("https://")):
            _eprint(f"refusing to start: WEBHOOK_URL {webhook_url!r} "
                    f"must start with http:// or https://")
            return 2

    near_reorg_threshold = max(
        1, int(args.reorg_cap * args.near_reorg_fraction)
    )

    # Resolve the debug.log path.  Three states:
    #   1. --no-log-tail            -> log_path = None  (skip detectors)
    #   2. --debug-log <path>       -> log_path = <path>
    #   3. neither + --datadir set  -> log_path = <datadir>/<chain>/debug.log
    log_path: Path | None = None
    if not args.no_log_tail:
        if args.debug_log is not None:
            log_path = Path(args.debug_log)
        elif args.datadir is not None:
            chain_subdir = (
                "" if args.chain in ("main", "_default_", "") else args.chain
            )
            log_path = Path(args.datadir) / chain_subdir / "debug.log"

    log_tailer: _LogTailer | None = None
    if log_path is not None:
        try:
            log_tailer = _LogTailer(log_path)
            _eprint(f"log tailer attached to {log_path}")
        except (FileNotFoundError, PermissionError) as e:
            _eprint(
                f"log tailer disabled: {e}; RUNBOOK §0 triggers "
                f"#2 + #3 will be silenced (pass --debug-log to "
                f"override or --no-log-tail to suppress this warning)"
            )

    w = _Watcher(
        rpc=rpc,
        interval_sec=args.interval,
        deep_fork_depth=args.deep_fork_depth,
        finalized_stall_threshold=args.finalized_stall_threshold,
        hashrate_window=args.hashrate_window,
        hashrate_drop_frac=args.hashrate_drop,
        near_reorg_threshold=near_reorg_threshold,
        long_reorg_depth=args.long_reorg_depth,
        pow_budget_rate=args.pow_budget_rate,
        pow_budget_window_sec=args.pow_budget_window,
        hashrate_sustained_drop_frac=args.hashrate_sustained_drop,
        hashrate_sustained_window_sec=args.hashrate_sustained_window,
        wallclock_hps_max_age_sec=args.wallclock_hps_max_age,
        log_tailer=log_tailer,
        dedup=_AlertDedup(args.dedup_window),
        webhook_url=webhook_url,
        http_timeout=args.http_timeout,
        hashrate_samples=deque(maxlen=args.hashrate_window),
    )

    _install_signal_handlers()

    if args.one_shot:
        w.step()
        return 0

    try:
        w.run()
    except KeyboardInterrupt:
        # In case the signal handler couldn't be installed (e.g. when
        # the daemon is hosted inside another runtime), fall back here.
        _eprint("KeyboardInterrupt; exiting")
    return 0


if __name__ == "__main__":
    sys.exit(main())
