# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license.
"""
Test 8 -- Live pool reachability probe.

Opens a TCP socket to pool.b3chain.org:3333, sends a single
mining.subscribe line, waits up to 5 seconds for any line back, and
asserts the response is a JSON object containing a "result" field.

This is a smoke test only: it does NOT mine, does NOT submit shares,
and does NOT keep the connection open. It's the cheapest possible
"is the pool alive and speaking Stratum V1" check.
"""

from __future__ import annotations

import json
import socket
import sys
import time
from typing import Optional, Tuple

LIVE_HOST = "pool.b3chain.org"
LIVE_PORT = 3333
TIMEOUT_S = 5.0


def run_live_pool_probe(emit) -> Tuple[bool, str]:
    """Connect, subscribe, read one line, validate. Returns (ok, metric)."""
    try:
        emit(f"  resolving {LIVE_HOST}...")
        addr = socket.gethostbyname(LIVE_HOST)
        emit(f"  {LIVE_HOST} -> {addr}")
    except OSError as e:
        emit(f"SKIP: DNS lookup failed: {e}")
        return False, f"skipped: DNS failed"

    t0 = time.time()
    try:
        s = socket.create_connection((LIVE_HOST, LIVE_PORT), timeout=TIMEOUT_S)
    except (OSError, socket.timeout) as e:
        emit(f"FAIL: TCP connect failed: {e}")
        return False, f"unreachable: {e}"

    connect_ms = int((time.time() - t0) * 1000)
    emit(f"  connected to {addr}:{LIVE_PORT} in {connect_ms}ms")

    rtt_ms = -1
    response_line = ""
    ok = False
    try:
        s.settimeout(TIMEOUT_S)
        request = (
            '{"id":1,"method":"mining.subscribe",'
            '"params":["b3chain-test-ui-probe/0.1"]}\n'
        )
        send_t = time.time()
        s.sendall(request.encode("utf-8"))
        emit("  sent: mining.subscribe")

        # Read until we see a newline-terminated response or timeout.
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                emit("FAIL: server closed connection without response")
                return False, "no response"
            buf += chunk
        rtt_ms = int((time.time() - send_t) * 1000)
        line, _, _ = buf.decode("utf-8", errors="replace").partition("\n")
        response_line = line.strip()
        emit(f"  recv: {response_line[:200]}{'...' if len(response_line) > 200 else ''}")

        # Parse JSON-RPC result.
        try:
            obj = json.loads(response_line)
        except ValueError as e:
            emit(f"FAIL: response is not JSON: {e}")
            return False, "non-json response"

        if obj.get("error"):
            emit(f"FAIL: server error: {obj['error']}")
            return False, f"server error: {obj['error']}"

        result = obj.get("result")
        if not isinstance(result, list) or len(result) < 2:
            emit(f"FAIL: result missing or wrong shape: {result}")
            return False, "bad result shape"

        # Stratum V1 mining.subscribe returns [subscriptions, extranonce1, extranonce2_size].
        ok = True
        emit(f"  PASS: subscribe responded in {rtt_ms}ms")
    except (OSError, socket.timeout) as e:
        emit(f"FAIL: socket error: {e}")
        return False, f"socket error: {e}"
    finally:
        try:
            s.close()
        except OSError:
            pass

    metric = f"subscribe ok {rtt_ms}ms" if ok else "fail"
    return ok, metric


def _cli_emit(line: str) -> None:
    print(line, flush=True)


if __name__ == "__main__":
    ok, metric = run_live_pool_probe(_cli_emit)
    skipped = metric.startswith("skipped")
    if ok:
        verdict = "PASS"
        rc = 0
    elif skipped:
        verdict = "SKIP"
        rc = 2
    else:
        verdict = "FAIL"
        rc = 1
    print(f"live_pool -> {verdict} ({metric})")
    sys.exit(rc)
