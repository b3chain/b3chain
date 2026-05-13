#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
End-to-end block-validation comparison: bitcoind vs b3chaind.

For each daemon, mine 2016 regtest blocks (one full retarget period),
shut the node down cleanly, time how long a fresh `-reindex` takes from
the on-disk block files. This is the most defensible single number,
because it exercises the full validation path (deserialise, script,
PoW, merkle, UTXO update) rather than just hashing.

Outputs:
  - markdown table on stdout
  - results/block-validation-<host>-<ts>.json
  - exit 0 always (measurement)

Skips gracefully if either binary is missing.

Usage:
    python3 compare-block-validation.py
    python3 compare-block-validation.py --blocks 500
    BITCOIND=/path/to/bitcoind B3CHAIND=/path/to/b3chaind python3 ...
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
import json
from base64 import b64encode
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
from compare_common import CompareResult, write_result, md_table  # noqa: E402


def free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Daemon:
    """Tiny manager: spawn a regtest daemon, mine, restart with -reindex, time it."""

    def __init__(self, name: str, binary: str, cli_binary: str | None = None):
        self.name = name
        self.binary = binary
        self.cli_binary = cli_binary or binary.replace("d", "-cli", 1)
        self.workdir = Path(tempfile.mkdtemp(prefix=f"compare-validation-{name}-"))
        self.p2p_port = free_port()
        self.rpc_port = free_port()
        self.rpc_user = "compare"
        self.rpc_password = "compare-" + str(os.getpid())
        self._proc: subprocess.Popen | None = None
        token = b64encode(f"{self.rpc_user}:{self.rpc_password}".encode()).decode()
        self._auth = {"Authorization": f"Basic {token}",
                      "Content-Type": "application/json"}

    def _start(self, extra: list[str]) -> None:
        cmd = [
            self.binary, "-regtest",
            f"-datadir={self.workdir}",
            f"-port={self.p2p_port}",
            f"-rpcport={self.rpc_port}",
            f"-rpcuser={self.rpc_user}",
            f"-rpcpassword={self.rpc_password}",
            "-rpcbind=127.0.0.1", "-rpcallowip=127.0.0.0/8",
            f"-bind=127.0.0.1:{self.p2p_port}",
            "-listenonion=0", "-discover=0", "-dnsseed=0",
            "-fallbackfee=0.0001",
        ] + extra
        self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _wait_ready(self, timeout: float = 60.0) -> None:
        end = time.time() + timeout
        while time.time() < end:
            try:
                self.rpc("getblockchaininfo")
                return
            except Exception:
                if self._proc and self._proc.poll() is not None:
                    raise RuntimeError(f"{self.name}: exited early code={self._proc.returncode}")
                time.sleep(0.25)
        raise TimeoutError(f"{self.name}: not ready in {timeout}s")

    def rpc(self, method: str, *params, wallet: str | None = None):
        url = f"http://127.0.0.1:{self.rpc_port}/"
        if wallet:
            url += f"wallet/{wallet}"
        body = json.dumps({"jsonrpc": "1.0", "id": "c",
                           "method": method, "params": list(params)}).encode()
        req = urllib.request.Request(url, data=body, headers=self._auth)
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read())
        if data.get("error"):
            raise RuntimeError(f"{self.name}: rpc error {data['error']}")
        return data["result"]

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                self.rpc("stop")
            except Exception:
                pass
            try:
                self._proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
        self._proc = None

    def cleanup(self) -> None:
        self.stop()
        shutil.rmtree(self.workdir, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.cleanup()


def time_validation(name: str, binary: str, blocks: int) -> dict:
    """Mine blocks, shut down, restart with -reindex, measure wall time."""
    d = Daemon(name, binary)
    try:
        d._start([])
        d._wait_ready()

        # Mine to a fresh address.
        try:
            d.rpc("createwallet", "compare")
        except Exception:
            pass
        addr = d.rpc("getnewaddress", wallet="compare")
        # generatetoaddress is fastest; do it in chunks of 100 to keep RPC lively.
        n = blocks
        while n > 0:
            chunk = min(n, 100)
            d.rpc("generatetoaddress", chunk, addr, wallet="compare")
            n -= chunk
        info = d.rpc("getblockchaininfo")
        height_after_mine = info["blocks"]

        d.stop()

        # Restart with -reindex and measure wall time.
        t0 = time.perf_counter()
        d._start(["-reindex"])
        # Wait until height_after_mine reached again.
        end = t0 + 600
        ready_height = 0
        while time.perf_counter() < end:
            try:
                info = d.rpc("getblockchaininfo")
                ready_height = info["blocks"]
                if ready_height >= height_after_mine and info.get("verificationprogress", 0) > 0.999:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        elapsed = time.perf_counter() - t0
        return {
            "daemon":          name,
            "binary":          binary,
            "blocks":          blocks,
            "reindex_seconds": elapsed,
            "blocks_per_sec":  blocks / elapsed if elapsed else 0,
            "ready_height":    ready_height,
        }
    finally:
        d.cleanup()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--blocks", type=int, default=2016,
                    help="how many regtest blocks to mine + reindex (default: 2016)")
    args = ap.parse_args()

    bitcoind   = os.environ.get("BITCOIND")  or shutil.which("bitcoind")
    b3chaind   = os.environ.get("B3CHAIND")  or shutil.which("b3chaind")

    result = CompareResult(comparison="block-validation")
    result.notes.append(f"blocks: {args.blocks}")

    rows = []
    skipped = []

    for name, binary in (("bitcoind", bitcoind), ("b3chaind", b3chaind)):
        if not binary or not Path(binary).is_file():
            skipped.append(name)
            print(f"  skipping {name}: binary not found "
                  f"(set ${name.upper()} env var)")
            continue
        print(f"\n  measuring {name} ({binary})")
        try:
            row = time_validation(name, binary, args.blocks)
            rows.append(row)
            result.add_row(**row)
            print(f"    reindex {args.blocks} blocks in {row['reindex_seconds']:.2f}s "
                  f"({row['blocks_per_sec']:.1f} blocks/s)")
        except Exception as e:
            print(f"    error: {e}")

    if skipped:
        result.notes.append(f"skipped daemons: {', '.join(skipped)}")
    if not rows:
        print("\nno daemon successfully measured. Build bitcoind and b3chaind, "
              "or set $BITCOIND / $B3CHAIND.")
        return 0

    # Summary
    by_name = {r["daemon"]: r for r in rows}
    if "bitcoind" in by_name and "b3chaind" in by_name:
        a = by_name["bitcoind"]["reindex_seconds"]
        b = by_name["b3chaind"]["reindex_seconds"]
        result.summary["b3chaind_relative_to_bitcoind"] = b / a if a else None

    path = write_result(result)
    print(f"\n  wrote {path}")
    print()
    print(md_table(
        ["daemon", "blocks", "reindex (s)", "blocks/s"],
        [[r["daemon"], r["blocks"], f"{r['reindex_seconds']:.2f}",
          f"{r['blocks_per_sec']:.1f}"] for r in rows],
    ))
    if "b3chaind_relative_to_bitcoind" in result.summary:
        s = result.summary["b3chaind_relative_to_bitcoind"]
        print(f"\nb3chaind reindex vs bitcoind: {s:.2f}x "
              f"({'faster' if s < 1 else 'slower'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
