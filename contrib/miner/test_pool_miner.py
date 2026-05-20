#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license.
"""
End-to-end test for b3chain-cpuminer.py pool mode.

Spins up a tiny mock Stratum V1 server in this process, points the
real miner at it, and validates:

  1. The handshake (subscribe + authorize) completes.
  2. mining.set_difficulty + mining.notify reach the miner.
  3. The miner finds and submits shares within the configured window.
  4. The JSONL log contains share_submit entries.
  5. For each submitted share, BLAKE3(BLAKE3(header_hex)) byte-matches
     the recorded pow_hash_le. (Reconstruction sanity check.)

Run:
  pip3 install blake3
  python3 contrib/miner/test_pool_miner.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time

import blake3


HERE = os.path.dirname(os.path.abspath(__file__))
MINER = os.path.join(HERE, "b3chain-cpuminer.py")


def _double_blake3(b: bytes) -> bytes:
    return blake3.blake3(blake3.blake3(b).digest()).digest()


def _serialize_header(version: int, prev_le: bytes, merkle_le: bytes,
                      ntime: int, bits: int, nonce: int) -> bytes:
    return (struct.pack("<i", version) + prev_le + merkle_le
            + struct.pack("<I", ntime) + struct.pack("<I", bits)
            + struct.pack("<I", nonce))


class MockStratumServer:
    """Single-connection Stratum V1 mock that accepts a few mining.submit calls.

    Pushes a set_difficulty + notify with deliberately easy parameters
    (bits=0x207fffff = regtest "diff 1", same as Bitcoin/Litecoin regtest)
    and a share difficulty of 0.0001 so a CPU finds shares within seconds.
    """

    EXTRANONCE1 = "deadbeef"
    EXTRANONCE2_SIZE = 4
    JOB_ID = "0000001"
    PREV_BE = "00" * 32
    COINB1 = bytes.fromhex(
        "01000000010000000000000000000000000000000000000000000000000000"
        "000000000000ffffffff10")  # tx version, vin count, prevout, scriptlen, BIP34 placeholder
    COINB2 = bytes.fromhex(
        "0a2f6233636861696e2fffffffff0100f9029500000000160014"
        "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef00000000")
    BRANCHES_BE: list[str] = []
    VERSION = 0x20000000
    BITS = 0x207fffff   # regtest: highest possible target -> shares are trivial
    SHARE_DIFFICULTY = 0.0001

    def __init__(self):
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.s.bind(("127.0.0.1", 0))
        self.s.listen(1)
        self.port = self.s.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.shares_received = 0
        self.shares_lock = threading.Lock()
        self.sock_client = None
        self.stop_evt = threading.Event()

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_evt.set()
        try:
            self.s.close()
        except OSError:
            pass

    def _serve(self):
        try:
            self.s.settimeout(15.0)
            conn, _ = self.s.accept()
        except OSError:
            return
        self.sock_client = conn
        conn.settimeout(15.0)
        buf = b""
        ntime = int(time.time())

        def send(obj):
            conn.sendall((json.dumps(obj, separators=(",", ":")) + "\n").encode())

        try:
            while not self.stop_evt.is_set():
                while b"\n" not in buf:
                    chunk = conn.recv(4096)
                    if not chunk:
                        return
                    buf += chunk
                idx = buf.index(b"\n")
                line, buf = buf[:idx], buf[idx + 1:]
                if not line.strip():
                    continue
                msg = json.loads(line)
                method = msg.get("method")
                msg_id = msg.get("id")
                if method == "mining.subscribe":
                    send({
                        "id": msg_id,
                        "result": [
                            [["mining.set_difficulty", "subid"],
                             ["mining.notify", "subid"]],
                            self.EXTRANONCE1,
                            self.EXTRANONCE2_SIZE,
                        ],
                        "error": None,
                    })
                elif method == "mining.authorize":
                    send({"id": msg_id, "result": True, "error": None})
                    send({"id": None, "method": "mining.set_difficulty",
                          "params": [self.SHARE_DIFFICULTY]})
                    send({"id": None, "method": "mining.notify", "params": [
                        self.JOB_ID,
                        self.PREV_BE,
                        self.COINB1.hex(),
                        self.COINB2.hex(),
                        self.BRANCHES_BE,
                        f"0x{self.VERSION:08x}",
                        f"0x{self.BITS:08x}",
                        f"0x{ntime:08x}",
                        True,  # clean_jobs
                    ]})
                elif method == "mining.submit":
                    with self.shares_lock:
                        self.shares_received += 1
                    send({"id": msg_id, "result": True, "error": None})
                else:
                    send({"id": msg_id, "result": True, "error": None})
        except (OSError, ValueError):
            return
        finally:
            try:
                conn.close()
            except OSError:
                pass


def _verify_jsonl(path: str) -> int:
    """Return number of share_submit entries that pass the BLAKE3d check."""
    submitted = 0
    verified = 0
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            try:
                obj = json.loads(raw)
            except ValueError:
                continue
            if obj.get("event") != "share_submit":
                continue
            submitted += 1
            header_hex = obj["header_hex"]
            pow_hex = obj["pow_hash_le"]
            recomputed = _double_blake3(bytes.fromhex(header_hex)).hex()
            if recomputed != pow_hex:
                print(f"  MISMATCH for share_seq={obj.get('share_seq')}:")
                print(f"    header   = {header_hex}")
                print(f"    expected = {pow_hex}")
                print(f"    got      = {recomputed}")
                continue
            verified += 1
    print(f"  share_submit JSONL entries: {submitted}; BLAKE3d verified: {verified}")
    return verified


def main() -> int:
    if not os.path.exists(MINER):
        print(f"ERROR: miner not found at {MINER}")
        return 1

    srv = MockStratumServer()
    srv.start()

    tmpfd, jsonl_path = tempfile.mkstemp(suffix=".jsonl")
    os.close(tmpfd)

    cmd = [
        sys.executable, MINER,
        "--stratum", f"stratum+tcp://127.0.0.1:{srv.port}",
        "--user", "test@b3chain.org.cpu1",
        "--pass", "x",
        "--threads", "1",
        "--max-attempts", "5",
        "--progress-interval", "100000",
        "--quiet-progress",
        "--json-log", jsonl_path,
    ]
    print("Running miner:")
    print("  " + " ".join(cmd))
    print()
    proc = subprocess.run(cmd, timeout=120,
                          stdout=sys.stdout, stderr=sys.stderr)
    print()
    print(f"miner exited with rc={proc.returncode}")

    srv.stop()
    time.sleep(0.5)

    print()
    print("Server-side received shares:", srv.shares_received)
    print("Verifying JSONL:")
    verified = _verify_jsonl(jsonl_path)

    ok = (proc.returncode == 0
          and srv.shares_received >= 5
          and verified >= 5)

    if ok:
        print()
        print("PASS: miner submitted 5 shares; JSONL BLAKE3d-verified.")
        os.unlink(jsonl_path)
        return 0
    else:
        print()
        print(f"FAIL: server={srv.shares_received} verified={verified} rc={proc.returncode}")
        print(f"JSONL retained at {jsonl_path}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
