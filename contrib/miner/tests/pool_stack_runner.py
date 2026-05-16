# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license.
"""
Test 9 -- Local Docker pool stack.

Brings up the full pool stack from contrib/testnet/pool/ and runs the
miner against it. Steps:

  1. Spawn b3chaind -regtest with a payouts wallet.
  2. docker compose -f docker-compose.dev.yml up -d   (postgres + mailpit).
  3. npm install (skipped if node_modules already exists).
  4. npm run migrate (idempotent).
  5. Generate a payout address from the wallet and write it to a
     temporary .env in a tmp pool config dir.
  6. Start b3chain-pool-daemon (npm run dev:daemon) AND
     b3chain-pool-stratum (npm run dev:stratum) as subprocesses,
     setting B3POOL_STRATUM_DEFAULT_DIFF=1 so a CPU finds shares fast.
  7. Wait for stratum to listen on :3333.
  8. Run the miner with --max-attempts 5 and assert 5 ACCEPTED shares.

Cleanup ALWAYS runs (even on Ctrl+C / UI close):

  - kill miner (terminate then kill if hung)
  - kill node processes for daemon + stratum (terminate, then taskkill on Windows)
  - b3chain-cli stop (graceful), then kill if not stopped
  - docker compose down

This runner is opt-in: the UI gates it behind a "Include slow tests" checkbox.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from typing import List, Optional, Tuple

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
MINER_DIR = os.path.dirname(THIS_DIR)
REPO_ROOT = os.path.dirname(os.path.dirname(MINER_DIR))
POOL_DIR = os.path.join(REPO_ROOT, "contrib", "testnet", "pool")
COMPOSE_FILE = os.path.join(POOL_DIR, "docker-compose.dev.yml")
MINER_SCRIPT = os.path.join(MINER_DIR, "b3chain-cpuminer.py")

DEFAULT_RPC_PORT = 18545
STRATUM_PORT = 3333


def _which_any(*names: str) -> Optional[str]:
    for n in names:
        path = shutil.which(n)
        if path:
            return path
    return None


def _stream_to(emit, prefix, fp):
    try:
        for raw in iter(fp.readline, ""):
            if not raw:
                break
            emit(f"  {prefix} | {raw.rstrip()}")
    except (OSError, ValueError):
        pass


def _wait_port(host: str, port: int, timeout_s: float) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except (OSError, socket.timeout):
            time.sleep(0.5)
    return False


def _kill_proc(p: Optional[subprocess.Popen], emit, name: str) -> None:
    if p is None or p.poll() is not None:
        return
    try:
        emit(f"  killing {name} (pid={p.pid})...")
        p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
    except OSError:
        pass


def run_pool_stack(emit) -> Tuple[bool, str]:
    docker = _which_any("docker.exe", "docker")
    npm = _which_any("npm.cmd", "npm.exe", "npm")
    b3chaind = _which_any("b3chaind.exe", "b3chaind")
    cli = _which_any("b3chain-cli.exe", "b3chain-cli")

    missing: List[str] = []
    if not docker:
        missing.append("docker")
    if not npm:
        missing.append("npm")
    if not b3chaind:
        missing.append("b3chaind")
    if not cli:
        missing.append("b3chain-cli")
    if not os.path.exists(COMPOSE_FILE):
        missing.append("pool source")
    if missing:
        emit(f"SKIP: missing {', '.join(missing)}")
        return False, f"skipped: missing {','.join(missing)}"

    # Confirm docker daemon is alive
    try:
        d = subprocess.run([docker, "info", "--format", "{{.ServerVersion}}"],
                           capture_output=True, text=True, timeout=10)
        if d.returncode != 0:
            emit("SKIP: docker daemon not running")
            return False, "skipped: docker daemon"
    except (subprocess.TimeoutExpired, OSError) as e:
        emit(f"SKIP: docker info failed: {e}")
        return False, "skipped: docker"

    datadir = tempfile.mkdtemp(prefix="b3chain-pool-stack-")
    rpc_user = "stack_user"
    rpc_pass = "stack_pass"
    p2p_port = DEFAULT_RPC_PORT - 1   # 18544 by convention; pick an unused-ish one

    daemon_proc: Optional[subprocess.Popen] = None
    pool_daemon_proc: Optional[subprocess.Popen] = None
    pool_stratum_proc: Optional[subprocess.Popen] = None
    miner_proc: Optional[subprocess.Popen] = None

    ok = False
    metric = ""
    cleanup_done = False

    def cleanup():
        nonlocal cleanup_done
        if cleanup_done:
            return
        cleanup_done = True
        # Kill the miner first.
        _kill_proc(miner_proc, emit, "miner")
        # Stop pool services.
        _kill_proc(pool_stratum_proc, emit, "pool-stratum")
        _kill_proc(pool_daemon_proc, emit, "pool-daemon")
        # docker compose down.
        try:
            emit("  docker compose down...")
            subprocess.run([docker, "compose", "-f", COMPOSE_FILE, "down"],
                           capture_output=True, text=True, timeout=60)
        except (subprocess.TimeoutExpired, OSError):
            pass
        # b3chain-cli stop.
        if daemon_proc and daemon_proc.poll() is None:
            try:
                emit("  b3chain-cli stop...")
                subprocess.run(
                    [cli, "-regtest",
                     f"-datadir={datadir}",
                     f"-rpcport={DEFAULT_RPC_PORT}",
                     f"-rpcuser={rpc_user}",
                     f"-rpcpassword={rpc_pass}",
                     "stop"],
                    capture_output=True, text=True, timeout=15,
                )
                try:
                    daemon_proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    daemon_proc.kill()
            except (subprocess.TimeoutExpired, OSError):
                try:
                    daemon_proc.kill()
                except OSError:
                    pass
        try:
            shutil.rmtree(datadir, ignore_errors=True)
        except OSError:
            pass

    try:
        # ---- 1. Spawn b3chaind -regtest -wallet=pool-payouts ----
        emit("  starting b3chaind -regtest...")
        daemon_cmd = [
            b3chaind, "-regtest",
            f"-datadir={datadir}",
            f"-port={p2p_port}",
            f"-rpcport={DEFAULT_RPC_PORT}",
            f"-rpcuser={rpc_user}",
            f"-rpcpassword={rpc_pass}",
            "-rpcallowip=127.0.0.1",
            "-listen=0",
            "-discover=0",
            "-fallbackfee=0.0001",
            "-printtoconsole",
        ]
        daemon_proc = subprocess.Popen(
            daemon_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        threading.Thread(target=_stream_to,
                         args=(emit, "b3chaind", daemon_proc.stdout),
                         daemon=True, name="b3chaind-stdout").start()

        # Wait for RPC.
        cli_base = [cli, "-regtest",
                    f"-datadir={datadir}",
                    f"-rpcport={DEFAULT_RPC_PORT}",
                    f"-rpcuser={rpc_user}",
                    f"-rpcpassword={rpc_pass}"]
        ready = False
        for _ in range(60):
            if daemon_proc.poll() is not None:
                emit(f"FAIL: b3chaind exited rc={daemon_proc.returncode}")
                return False, f"daemon exit {daemon_proc.returncode}"
            try:
                out = subprocess.run(cli_base + ["getblockchaininfo"],
                                     capture_output=True, text=True, timeout=4)
                if out.returncode == 0:
                    ready = True
                    break
            except subprocess.TimeoutExpired:
                pass
            time.sleep(0.5)
        if not ready:
            emit("FAIL: b3chaind RPC never came up")
            return False, "rpc not ready"

        # Create payouts wallet, get a payout address.
        subprocess.run(cli_base + ["createwallet", "pool-payouts"],
                       capture_output=True, text=True, timeout=10)
        addr_proc = subprocess.run(
            cli_base + ["-rpcwallet=pool-payouts", "getnewaddress"],
            capture_output=True, text=True, timeout=10,
        )
        if addr_proc.returncode != 0:
            emit(f"FAIL: getnewaddress: {addr_proc.stderr.strip()}")
            return False, "getnewaddress failed"
        payout_addr = addr_proc.stdout.strip()
        emit(f"  payout address: {payout_addr}")

        # ---- 2. docker compose up postgres ----
        emit("  docker compose up -d (postgres + mailpit)...")
        up = subprocess.run(
            [docker, "compose", "-f", COMPOSE_FILE, "up", "-d"],
            capture_output=True, text=True, timeout=120,
        )
        if up.returncode != 0:
            emit(f"FAIL: docker compose up: {up.stderr.strip()}")
            return False, "docker compose up failed"

        # Wait for postgres to be ready.
        if not _wait_port("127.0.0.1", 5432, timeout_s=60):
            emit("FAIL: postgres :5432 not reachable")
            return False, "postgres not ready"

        # ---- 3. npm install (only if needed) ----
        node_modules = os.path.join(POOL_DIR, "node_modules")
        if not os.path.isdir(node_modules):
            emit("  npm install (first run, this takes a while)...")
            ni = subprocess.run([npm, "install"],
                                cwd=POOL_DIR, capture_output=True,
                                text=True, timeout=600)
            if ni.returncode != 0:
                emit(f"FAIL: npm install: {ni.stderr.strip()[-500:]}")
                return False, "npm install failed"
        else:
            emit("  npm install: skipping (node_modules present)")

        # ---- 4. Build the env for the pool services ----
        env = os.environ.copy()
        env.update({
            "B3POOL_NETWORK": "regtest",
            "B3POOL_RPC_HOST": "127.0.0.1",
            "B3POOL_RPC_PORT": str(DEFAULT_RPC_PORT),
            "B3POOL_RPC_USER": rpc_user,
            "B3POOL_RPC_PASSWORD": rpc_pass,
            "B3POOL_PAYOUT_WALLET": "pool-payouts",
            "B3POOL_PAYOUT_ADDRESS": payout_addr,
            "B3POOL_DB_URL":
                "postgres://b3chain_pool:dev@127.0.0.1:5432/b3chain_pool",
            "B3POOL_STRATUM_BIND": "127.0.0.1",
            "B3POOL_STRATUM_PORT": str(STRATUM_PORT),
            "B3POOL_STRATUM_DEFAULT_DIFF": "1",
            "B3POOL_COOKIE_SECRET": "stack-test-cookie-secret-32bytes",
            "B3POOL_LOG_LEVEL": "info",
        })

        # ---- 5. Migrate ----
        emit("  npm run migrate...")
        mig = subprocess.run([npm, "run", "migrate"],
                             cwd=POOL_DIR, env=env, capture_output=True,
                             text=True, timeout=120)
        if mig.returncode != 0:
            emit(f"FAIL: migrate: {mig.stderr.strip()[-500:]}")
            return False, "migrate failed"

        # ---- 6. Start the pool daemon + stratum services ----
        emit("  starting b3chain-pool-daemon (npm run dev:daemon)...")
        pool_daemon_proc = subprocess.Popen(
            [npm, "run", "dev:daemon"], cwd=POOL_DIR, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        threading.Thread(target=_stream_to,
                         args=(emit, "pool-daemon", pool_daemon_proc.stdout),
                         daemon=True, name="pool-daemon-stdout").start()

        emit("  starting b3chain-pool-stratum (npm run dev:stratum)...")
        pool_stratum_proc = subprocess.Popen(
            [npm, "run", "dev:stratum"], cwd=POOL_DIR, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        threading.Thread(target=_stream_to,
                         args=(emit, "pool-stratum", pool_stratum_proc.stdout),
                         daemon=True, name="pool-stratum-stdout").start()

        # ---- 7. Wait for stratum :3333 ----
        emit(f"  waiting for stratum on :{STRATUM_PORT}...")
        if not _wait_port("127.0.0.1", STRATUM_PORT, timeout_s=60):
            emit(f"FAIL: stratum :{STRATUM_PORT} not reachable in 60s")
            return False, "stratum never came up"
        emit("  stratum is listening")

        # Give it a beat to finish setting up jobs.
        time.sleep(2.0)

        # ---- 8. Run the miner ----
        emit("  starting miner --max-attempts 5...")
        miner_cmd = [
            sys.executable, MINER_SCRIPT,
            "--stratum", f"stratum+tcp://127.0.0.1:{STRATUM_PORT}",
            "--user", "stack@b3chain.org.cpu1",
            "--pass", "x",
            "--threads", "1",
            "--max-attempts", "5",
            "--quiet-progress",
            "--progress-interval", "100000",
        ]
        miner_proc = subprocess.Popen(
            miner_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        accepted = 0
        captured: List[str] = []
        try:
            for raw in iter(miner_proc.stdout.readline, ""):
                if not raw:
                    break
                line = raw.rstrip()
                captured.append(line)
                emit(f"  miner | {line}")
                if "ACCEPTED" in line and "share=#" in line:
                    accepted += 1
                    if accepted >= 5:
                        break
        except (OSError, ValueError):
            pass
        # Make sure miner gets cleaned up regardless of how we exited the loop.
        _kill_proc(miner_proc, emit, "miner")

        if accepted >= 5:
            ok = True
            metric = f"{accepted}/5 shares ACCEPTED"
            emit(f"  PASS: {metric}")
        else:
            metric = f"{accepted}/5 shares (failed)"
            emit(f"  FAIL: only {accepted} share(s) accepted before exit")
    except Exception as e:
        emit(f"FAIL: exception in pool stack runner: {e}")
        metric = f"exception: {e}"
    finally:
        cleanup()

    return ok, metric


def _cli_emit(line: str) -> None:
    print(line, flush=True)


if __name__ == "__main__":
    ok, metric = run_pool_stack(_cli_emit)
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
    print(f"pool_stack -> {verdict} ({metric})")
    sys.exit(rc)
