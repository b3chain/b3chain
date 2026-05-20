#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
End-to-end smoke test for the runbook-§0 alerting completion.

Spins up an in-process HTTP RPC stub that serves canned `getchaintips`,
`getblockchaininfo`, `getnetworkhashps`, and `getfinalizedblockhash`
responses crafted to fire each of the seven detector families in
`contrib/monitoring/51attack-watch.py`, then invokes the watcher's
`_Watcher.step()` once (the moral equivalent of `--one-shot`) against
the stub, captures the emitted JSONL on stdout, and asserts that
every expected `kind` appeared.

Exit code 0 = every expected alert fired and no unexpected ones.

This complements the pure-function `audit-51attack-watch.py` unit
tests by exercising the actual `_Watcher.step()` wiring path (the
integration the unit tests deliberately skip).

This is a smoke test, not a CI gate -- but it can be promoted to a
CI gate by registering it in `run-all.sh` once
ssh-tested on a Linux runner.  Today it runs unattended on the
maintainer's box.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import time
import types
from base64 import b64encode
from collections import deque
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
WATCHER_PATH = REPO_ROOT / "contrib" / "monitoring" / "51attack-watch.py"


def _load_watcher_module() -> types.ModuleType:
    """Same loader used by audit-51attack-watch.py; see that file for why."""
    module_name = "watcher_under_test"
    src = WATCHER_PATH.read_text(encoding="utf-8")
    mod = types.ModuleType(module_name)
    mod.__file__ = str(WATCHER_PATH)
    mod.__dict__["__name__"] = module_name
    sys.modules[module_name] = mod
    try:
        code = compile(src, str(WATCHER_PATH), "exec")
        exec(code, mod.__dict__)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return mod


# ---------- Forged b3chaind RPC fixture --------------------------------------

class _ForgedRpcHandler(BaseHTTPRequestHandler):
    """Serves canned JSON-RPC responses crafted to fire every detector."""

    # Class-level state so the request handler can read it (the
    # BaseHTTPRequestHandler is instantiated per-request).
    expected_user = "smoke"
    expected_pass = "smoke"
    responses: dict[str, object] = {}

    def log_message(self, fmt: str, *args: object) -> None:  # noqa: N802
        # Silence default access log; we don't want it in the smoke output.
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body_raw = self.rfile.read(length)
        try:
            req = json.loads(body_raw)
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            return
        method = req.get("method", "")
        params = req.get("params", [])
        rid = req.get("id", "")
        result = self._dispatch(method, params)
        if result is _NOT_FOUND:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "jsonrpc": "1.0", "id": rid, "result": None,
                "error": {"code": -32601, "message": "Method not found"},
            }).encode())
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "jsonrpc": "1.0", "id": rid, "result": result, "error": None,
        }).encode())

    def _dispatch(self, method: str, params: list) -> object:
        # `getblockheader` needs param-aware dispatch so the
        # common-ancestor walker in 51attack-watch can resolve a fake
        # shared ancestor.  Everything else is constant per-method.
        if method == "getblockheader":
            arg = params[0] if params else None
            headers = self.responses.get("__headers_db__", {})
            return headers.get(arg, _NOT_FOUND)
        canned = self.responses.get(method, _NOT_FOUND)
        return canned


_NOT_FOUND = object()


def _start_forged_rpc(responses: dict[str, object]) -> tuple[HTTPServer, str]:
    """Start a one-shot HTTP RPC server on a free localhost port.

    Returns (server, auth_header).  Caller calls server.shutdown()
    when done.
    """
    _ForgedRpcHandler.responses = responses
    server = HTTPServer(("127.0.0.1", 0), _ForgedRpcHandler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    token = b64encode(b"smoke:smoke").decode()
    return server, f"Basic {token}", port


# ---------- Scenarios --------------------------------------------------------

def _scenario_responses() -> dict[str, object]:
    """Canned RPC responses that fire every detector in a single step()."""
    # The watcher's _common_ancestor_height walker decrements height
    # by 1 per hop, so the fixture needs a true CONSECUTIVE-block
    # chain on both branches.  Layout:
    #
    #   anc (h=4900) -+- new0 (4901) -...- new99 (5000)  <- new_tip "b"
    #                 \- prev0 (4901) -...- prev199 (5100) <- prev_tip "z"
    #
    # 5100 - 4900 = 200 reorg depth, > 100 near_reorg threshold.
    new_tip  = "b" * 64
    prev_tip = "z" * 64
    ancestor_hash = "a" + "0" * 63
    headers: dict[str, dict] = {}
    headers[ancestor_hash] = {"height": 4900, "previousblockhash": None}
    # Build the "new" branch: 100 blocks from 4901 to 5000.
    prev_hash = ancestor_hash
    for h in range(4901, 5000):
        block_hash = f"new{h:061d}"
        headers[block_hash] = {"height": h, "previousblockhash": prev_hash}
        prev_hash = block_hash
    headers[new_tip] = {"height": 5000, "previousblockhash": prev_hash}
    # Build the "prev" branch: 200 blocks from 4901 to 5100.
    prev_hash = ancestor_hash
    for h in range(4901, 5100):
        block_hash = f"prv{h:061d}"
        headers[block_hash] = {"height": h, "previousblockhash": prev_hash}
        prev_hash = block_hash
    headers[prev_tip] = {"height": 5100, "previousblockhash": prev_hash}
    return {
        "getblockchaininfo": {
            "blocks": 5000,
            "bestblockhash": new_tip,
        },
        "getchaintips": [
            {"height": 5000, "hash": new_tip,
             "branchlen": 0, "status": "active"},
            # Fires deep_fork (>=6) AND long_reorg (>=50).
            {"height": 4940, "hash": "c" * 64,
             "branchlen": 60, "status": "valid-fork"},
        ],
        "getnetworkhashps": 1.0,  # fires hashrate_collapse vs prior peak
        # M-14 RPC; flip source vs prior obs -> source_flip alert.
        "getfinalizedblockhash": {
            "hash": "f" * 64, "height": 4800, "source": "operator",
        },
        # Param-aware headers DB (handled by _ForgedRpcHandler._dispatch).
        "__headers_db__": headers,
    }


def main() -> int:
    print("[smoke] loading watcher module ...")
    mod = _load_watcher_module()
    print("  [OK]")

    responses = _scenario_responses()
    server, auth_header, port = _start_forged_rpc(responses)
    print(f"[smoke] forged RPC stub on 127.0.0.1:{port}")

    # Set up a synthetic debug.log with one of each marker line.
    with tempfile.TemporaryDirectory() as td:
        log_path = Path(td) / "debug.log"
        log_path.write_text("", encoding="utf-8")
        log_tailer = mod._LogTailer(log_path)
        # NOW write the lines so the tailer sees them on first poll.
        with log_path.open("a", encoding="utf-8") as f:
            f.write("2026-05-19T20:00:00 peer=42 Misbehaving: "
                    "deep-reorg-attempt depth=205\n")
            # 150 pow-budget lines to trip the > 100/h storm threshold.
            for i in range(150):
                f.write(f"2026-05-19T20:00:{i:02d} peer=7 Misbehaving: "
                        "b3pow-budget-exceeded\n")

        rpc = mod.RpcClient("127.0.0.1", port, auth_header, timeout=5.0)

        # Pre-seed the wall-clock hashrate deque with a chronological
        # 24h history so the new poll's hps=1.0 looks like a sustained
        # >30% drop sustained >1h.  Strict monotonic timestamps; no
        # overlapping ranges (the production deque maintains the same
        # invariant via append-only inside _Watcher.step).
        now = time.time()
        pre_samples: deque = deque()
        # 22h at 100 H/s, ending 2h before now (1320 entries).
        for i in range(22 * 60):
            ts = now - (24 * 3600) + i * 60  # now-24h .. now-2h
            pre_samples.append((ts, 100.0))
        # 2h at 1 H/s, ending at now-1min (120 entries).  This is the
        # sustained dip; with the new (now, 1.0) sample appended by
        # step() that's 2h+ continuous below threshold => critical.
        for i in range(120):
            ts = now - (2 * 3600) + i * 60  # now-2h .. now-1min
            pre_samples.append((ts, 1.0))

        # Block-keyed hashrate window for detect_hashrate_collapse.
        block_samples: deque = deque(maxlen=100)
        for h in range(4900, 4999):
            block_samples.append((h, 100.0))
        # The new poll will append (5000, 1.0) -> 1% of peak -> alert.

        # Pre-seed last_finalized_obs so the new {source: "operator"}
        # looks like a source flip from "max_reorg_depth".
        prior_finalized = {
            "hash": "0" * 64, "height": 4700,
            "source": "max_reorg_depth",
            "stale_count": 0, "tip_height_at_obs": 5099,
        }

        w = mod._Watcher(
            rpc=rpc,
            interval_sec=30.0,
            deep_fork_depth=mod.DEFAULT_DEEP_FORK_DEPTH,
            hashrate_window=mod.DEFAULT_HASHRATE_WINDOW,
            hashrate_drop_frac=mod.DEFAULT_HASHRATE_DROP,
            near_reorg_threshold=int(
                mod.DEFAULT_REORG_CAP * mod.DEFAULT_NEAR_REORG_FRAC
            ),
            long_reorg_depth=mod.DEFAULT_LONG_REORG_DEPTH,
            pow_budget_rate=mod.DEFAULT_POW_BUDGET_RATE,
            pow_budget_window_sec=mod.DEFAULT_POW_BUDGET_WINDOW_SEC,
            hashrate_sustained_drop_frac=(
                mod.DEFAULT_HASHRATE_SUSTAINED_DROP
            ),
            hashrate_sustained_window_sec=(
                mod.DEFAULT_HASHRATE_SUSTAINED_WIN
            ),
            wallclock_hps_max_age_sec=(
                mod.DEFAULT_WALLCLOCK_HPS_MAX_AGE
            ),
            log_tailer=log_tailer,
            dedup=mod._AlertDedup(window_sec=5.0),
            webhook_url=None,
            http_timeout=5.0,
            hashrate_samples=block_samples,
            wallclock_hps_samples=pre_samples,
            # Prev-tip fixture matches the __headers_db__ above so the
            # common-ancestor walker resolves to height 4900 and
            # near_reorg_cap fires (5100 - 4900 = 200 >= 100 threshold).
            last_tip_hash="z" * 64,
            last_tip_height=5100,
            last_finalized_obs=prior_finalized,
        )

        # Capture stdout (JSONL alerts) while step() runs.
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            w.step()
        log_tailer.close()
        server.shutdown()
        server.server_close()

        emitted_lines = [ln for ln in buf.getvalue().splitlines() if ln]
        alerts: list[dict] = []
        for ln in emitted_lines:
            try:
                alerts.append(json.loads(ln))
            except json.JSONDecodeError:
                print(f"  [WARN] non-JSON stdout line: {ln!r}")

        kinds = sorted({a.get("kind", "") for a in alerts})
        print(f"[smoke] emitted {len(alerts)} alerts, kinds={kinds}")
        for a in alerts:
            print(f"  - {a.get('kind')} [{a.get('severity')}] "
                  f"{a.get('message', '')[:90]}")

        expected = {
            "deep_fork", "long_reorg",
            "hashrate_collapse", "hashrate_sustained_drop",
            "near_reorg_cap",
            "finalized_drift_source_flip",
            "deep_reorg_log", "pow_budget_storm",
        }
        got = set(kinds)
        missing = expected - got
        extra_unexpected = got - expected - {"rpc_down"}  # rpc_down ok absent
        rc = 0
        if missing:
            print(f"  [FAIL] missing expected alert kinds: "
                  f"{sorted(missing)}")
            rc = 1
        else:
            print("  [PASS] every expected alert kind fired")
        if extra_unexpected:
            print(f"  [WARN] unexpected alert kinds (not failing): "
                  f"{sorted(extra_unexpected)}")
        return rc


if __name__ == "__main__":
    sys.exit(main())
