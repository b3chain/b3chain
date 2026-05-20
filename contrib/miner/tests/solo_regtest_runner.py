# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license.
"""
Test 7 -- Solo regtest mining.

Spawns b3chaind -regtest -daemon in a temp datadir, creates a fresh
wallet, runs the miner via subprocess, polls getblockcount until it
goes up by at least 1, then stops the daemon. Always runs cleanup
(b3chain-cli stop, then taskkill if necessary) so we never leave a
zombie b3chaind.exe.

Run via:
  python solo_regtest_runner.py
exits 0 on success, non-zero otherwise. Stdout is the streamable log.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from typing import Optional, Tuple

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
MINER_DIR = os.path.dirname(THIS_DIR)
MINER_SCRIPT = os.path.join(MINER_DIR, "b3chain-cpuminer.py")


def _which_any(*names: str) -> Optional[str]:
    for n in names:
        path = shutil.which(n)
        if path:
            return path
    return None


def _free_port_pair() -> Tuple[int, int]:
    """Pick two free localhost ports (P2P + RPC) for this regtest run.

    We re-bind to 127.0.0.1:0, read the assigned port, then close. There is a
    micro race window where the port could be re-claimed before b3chaind binds
    -- in practice this is rare on a developer box and b3chaind would simply
    fail to start, which we handle.
    """
    sa = socket.socket()
    sa.bind(("127.0.0.1", 0))
    sb = socket.socket()
    sb.bind(("127.0.0.1", 0))
    p1 = sa.getsockname()[1]
    p2 = sb.getsockname()[1]
    sa.close()
    sb.close()
    return p1, p2


def _stream_to(emit, prefix, fp):
    """Pump fp line by line into emit() prefixed for visual separation."""
    try:
        for raw in iter(fp.readline, ""):
            if not raw:
                break
            emit(f"  {prefix} | {raw.rstrip()}")
    except (OSError, ValueError):
        pass


def run_solo_regtest(emit) -> Tuple[bool, str]:
    """Bring up b3chaind -regtest, mine 1 block via the miner, tear down."""
    b3chaind = _which_any("b3chaind.exe", "b3chaind")
    cli = _which_any("b3chain-cli.exe", "b3chain-cli")
    if not b3chaind or not cli:
        emit("SKIP: b3chaind / b3chain-cli not on PATH")
        return False, "skipped (no binaries)"

    if not os.path.exists(MINER_SCRIPT):
        emit(f"FAIL: miner script missing at {MINER_SCRIPT}")
        return False, "miner missing"

    datadir = tempfile.mkdtemp(prefix="b3chain-regtest-")
    p2p_port, rpc_port = _free_port_pair()
    rpc_user = "regtest_user"
    rpc_pass = "regtest_pass"

    emit(f"  datadir = {datadir}")
    emit(f"  p2p={p2p_port} rpc={rpc_port}")

    daemon_cmd = [
        b3chaind, "-regtest",
        f"-datadir={datadir}",
        f"-port={p2p_port}",
        f"-rpcport={rpc_port}",
        f"-rpcuser={rpc_user}",
        f"-rpcpassword={rpc_pass}",
        "-rpcallowip=127.0.0.1",
        "-listen=0",
        "-discover=0",
        "-fallbackfee=0.0001",
        "-printtoconsole",
    ]

    daemon_proc = None
    miner_proc = None
    metric = ""
    ok = False
    try:
        emit("  starting b3chaind...")
        daemon_proc = subprocess.Popen(
            daemon_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        # Spawn a reader thread so the daemon's stdout doesn't block on a full pipe.
        threading.Thread(
            target=_stream_to,
            args=(emit, "b3chaind", daemon_proc.stdout),
            daemon=True,
            name="regtest-stdout",
        ).start()

        # Wait for RPC to become responsive via getblockchaininfo.
        deadline = time.time() + 30.0
        ready = False
        last_err = ""
        while time.time() < deadline:
            if daemon_proc.poll() is not None:
                emit(f"FAIL: b3chaind exited rc={daemon_proc.returncode}")
                return False, f"daemon exit {daemon_proc.returncode}"
            try:
                out = subprocess.run(
                    [cli, "-regtest",
                     f"-datadir={datadir}",
                     f"-rpcport={rpc_port}",
                     f"-rpcuser={rpc_user}",
                     f"-rpcpassword={rpc_pass}",
                     "getblockchaininfo"],
                    capture_output=True, text=True, timeout=4,
                )
                if out.returncode == 0:
                    ready = True
                    break
                last_err = out.stderr.strip()
            except subprocess.TimeoutExpired:
                last_err = "cli timeout"
            time.sleep(0.5)
        if not ready:
            emit(f"FAIL: b3chaind RPC never came up: {last_err}")
            return False, "rpc not ready"

        # Create a wallet and a coinbase address.
        emit("  creating wallet 'miner-test'...")
        cli_base = [cli, "-regtest",
                    f"-datadir={datadir}",
                    f"-rpcport={rpc_port}",
                    f"-rpcuser={rpc_user}",
                    f"-rpcpassword={rpc_pass}"]
        wallet_create = subprocess.run(
            cli_base + ["createwallet", "miner-test"],
            capture_output=True, text=True, timeout=10,
        )
        if wallet_create.returncode != 0:
            emit(f"FAIL: createwallet: {wallet_create.stderr.strip()}")
            return False, "createwallet failed"

        addr_proc = subprocess.run(
            cli_base + ["-rpcwallet=miner-test", "getnewaddress"],
            capture_output=True, text=True, timeout=10,
        )
        if addr_proc.returncode != 0:
            emit(f"FAIL: getnewaddress: {addr_proc.stderr.strip()}")
            return False, "getnewaddress failed"
        addr = addr_proc.stdout.strip()
        emit(f"  coinbase address: {addr}")

        # Capture starting block count.
        gbc = subprocess.run(
            cli_base + ["getblockcount"],
            capture_output=True, text=True, timeout=10,
        )
        start_height = int(gbc.stdout.strip() or "0")
        emit(f"  starting height: {start_height}")

        # Run the miner.
        miner_cmd = [
            sys.executable, MINER_SCRIPT,
            "-regtest",  # accepted by argparse via --regtest? -- actually the miner uses --regtest
        ]
        # The miner uses --regtest (long form) and --rpcuser/--rpcpassword.
        miner_cmd = [
            sys.executable, MINER_SCRIPT,
            "--regtest",
            "--rpcconnect=127.0.0.1",
            f"--rpcport={rpc_port}",
            f"--rpcuser={rpc_user}",
            f"--rpcpassword={rpc_pass}",
            f"--coinbaseaddr={addr}",
            "--threads=1",
        ]
        emit("  starting miner (will run until 1 block found, then we kill it)...")
        miner_proc = subprocess.Popen(
            miner_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        threading.Thread(
            target=_stream_to,
            args=(emit, "miner", miner_proc.stdout),
            daemon=True,
            name="miner-stdout",
        ).start()

        t0 = time.time()
        new_height = start_height
        deadline = t0 + 60.0
        while time.time() < deadline:
            if miner_proc.poll() is not None:
                # Miner exited unexpectedly. Sample height once more before failing.
                pass
            time.sleep(1.0)
            try:
                gbc = subprocess.run(
                    cli_base + ["getblockcount"],
                    capture_output=True, text=True, timeout=4,
                )
                if gbc.returncode == 0:
                    new_height = int(gbc.stdout.strip() or "0")
                    if new_height > start_height:
                        break
            except subprocess.TimeoutExpired:
                pass
        elapsed = time.time() - t0
        diff = new_height - start_height
        if diff >= 1:
            ok = True
            metric = f"{diff} block(s), {elapsed:.1f}s"
            emit(f"  PASS: mined {diff} block(s) in {elapsed:.1f}s "
                 f"(height {start_height} -> {new_height})")
        else:
            metric = f"0 blocks in {elapsed:.1f}s"
            emit(f"  FAIL: mined 0 blocks in {elapsed:.1f}s")
    except Exception as e:
        emit(f"FAIL: exception during solo regtest: {e}")
        metric = f"exception: {e}"
    finally:
        # ---- Cleanup: kill miner, stop daemon, wipe datadir ----
        if miner_proc is not None and miner_proc.poll() is None:
            emit("  stopping miner...")
            try:
                miner_proc.terminate()
                try:
                    miner_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    miner_proc.kill()
            except OSError:
                pass

        if daemon_proc is not None and daemon_proc.poll() is None:
            emit("  stopping b3chaind via 'b3chain-cli stop'...")
            try:
                subprocess.run(
                    [cli, "-regtest",
                     f"-datadir={datadir}",
                     f"-rpcport={rpc_port}",
                     f"-rpcuser={rpc_user}",
                     f"-rpcpassword={rpc_pass}",
                     "stop"],
                    capture_output=True, text=True, timeout=10,
                )
                try:
                    daemon_proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    emit("  b3chaind didn't stop, killing...")
                    daemon_proc.kill()
            except (OSError, subprocess.TimeoutExpired):
                try:
                    daemon_proc.kill()
                except OSError:
                    pass

        try:
            shutil.rmtree(datadir, ignore_errors=True)
        except OSError:
            pass

    return ok, metric


def _cli_emit(line: str) -> None:
    print(line, flush=True)


if __name__ == "__main__":
    ok, metric = run_solo_regtest(_cli_emit)
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
    print(f"solo_regtest -> {verdict} ({metric})")
    sys.exit(rc)
