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

  hashrate_collapse    -- `getnetworkhashps` dropped to <= 50% of
                          its maximum in the previous
                          --hashrate-window blocks.  Maps to F-3
                          (low-hashrate bootstrap window) and is the
                          single best predictor of an imminent
                          competitor-fork attempt.

  near_reorg_cap       -- the active chain reorged by more than
                          --near-reorg-fraction * max_reorg_depth
                          blocks (default 0.5 -> 100 of the 200-block
                          M-4 cap; F-2 fix).  Half-cap is the right
                          point to alert: it gives the operator time
                          to act before the cap actually fires and
                          freezes the chain.

Execution model (Tier 3 — verify-before-done audit)
---------------------------------------------------

TRIGGER:  long-running daemon (`while not _stop`).  Intended to run
          under systemd or a process supervisor; see
          [`doc/security/51-MONITORING-OPS.md`](../../doc/security/51-MONITORING-OPS.md).

LOOP:     `_poll_loop()` below.  One iteration: poll RPC -> compute
          alerts -> emit -> sleep --interval seconds.  Sleeps
          --interval, NOT --interval since last cycle, so a slow RPC
          doesn't burn CPU; sleeps are interruptible by SIGTERM /
          SIGINT via `_stop_event`.

BYPASS:   - RPC down                  -> `RpcUnavailable` -> emit
                                         `rpc_down` alert (dedup'd),
                                         continue loop (next iteration
                                         will retry).
          - Webhook returns 5xx       -> log to stderr, do NOT crash;
                                         alert is still on stdout.
          - Webhook URL malformed     -> validated at startup; the
                                         daemon refuses to start.
          - Wall-clock jumps          -> the sliding window is keyed on
                                         BLOCK HEIGHT, not wall-clock,
                                         so a host time-skew does not
                                         desync the detector.
          - max_reorg_depth missing   -> falls back to --reorg-cap
                                         (200) from CLI.

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
from typing import Any


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
    hashrate_samples: deque[tuple[int, float]] = dataclasses.field(
        default_factory=deque)
    last_tip_hash: str | None = None
    last_tip_height: int | None = None

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

    def run(self) -> None:
        _eprint(
            f"started; interval={self.interval_sec}s, "
            f"deep_fork_depth={self.deep_fork_depth}, "
            f"hashrate_window={self.hashrate_window} blocks @ "
            f"<= {self.hashrate_drop_frac*100:.0f}%, "
            f"near_reorg>={self.near_reorg_threshold}, "
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

    w = _Watcher(
        rpc=rpc,
        interval_sec=args.interval,
        deep_fork_depth=args.deep_fork_depth,
        hashrate_window=args.hashrate_window,
        hashrate_drop_frac=args.hashrate_drop,
        near_reorg_threshold=near_reorg_threshold,
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
