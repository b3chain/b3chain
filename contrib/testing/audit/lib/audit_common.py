#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
Shared utilities for B3Chain Phase 11 audit scripts.

Provides:
  - find_binaries(): locate b3chaind / b3chain-cli
  - RegtestNode: spawn an isolated regtest node with a unique datadir / port
  - RpcClient: tiny JSON-RPC client (no external dependency)
  - AuditResult: counter + pretty printer with PASS / FAIL exit code
  - read_audit_id(): parse the audit ID(s) from the calling script's docstring
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from base64 import b64encode
from pathlib import Path

# ---------------------------------------------------------------------------
# Terminal colour
# ---------------------------------------------------------------------------

_USE_COLOUR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOUR else text

GREEN  = lambda s: _c("32", s)
RED    = lambda s: _c("31", s)
YELLOW = lambda s: _c("33", s)
BOLD   = lambda s: _c("1",  s)
DIM    = lambda s: _c("2",  s)


# ---------------------------------------------------------------------------
# Locate binaries
# ---------------------------------------------------------------------------

def repo_root() -> Path:
    """Return the b3chain repo root by walking up from this file."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "src" / "kernel" / "chainparams.cpp").is_file():
            return parent
    raise RuntimeError("Could not locate b3chain repo root from " + str(here))


def find_binaries() -> tuple[Path, Path]:
    """Locate b3chaind and b3chain-cli, honouring $BINDIR if set."""
    bindir_env = os.environ.get("BINDIR")
    candidates: list[Path] = []
    if bindir_env:
        candidates.append(Path(bindir_env))
    root = repo_root()
    candidates += [root / "build" / "bin", root / "build" / "src"]

    for d in candidates:
        b3chaind = d / "b3chaind"
        b3cli    = d / "b3chain-cli"
        if b3chaind.is_file() and b3cli.is_file():
            return b3chaind, b3cli
    raise FileNotFoundError(
        "Could not find b3chaind / b3chain-cli. "
        "Build the project or set BINDIR to the directory containing them."
    )


# ---------------------------------------------------------------------------
# Free-port allocation
# ---------------------------------------------------------------------------

def free_port() -> int:
    """Ask the OS for an unused TCP port."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ---------------------------------------------------------------------------
# Tiny JSON-RPC client (no python-bitcoinrpc dependency)
# ---------------------------------------------------------------------------

class RpcError(RuntimeError):
    def __init__(self, code: int, message: str):
        super().__init__(f"RPC error {code}: {message}")
        self.code = code
        self.message = message


class RpcClient:
    def __init__(self, host: str, port: int, user: str, password: str,
                 wallet: str | None = None, timeout: float = 30.0):
        self._base_url = f"http://{host}:{port}"
        self._wallet = wallet
        token = b64encode(f"{user}:{password}".encode()).decode()
        self._headers = {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
        }
        self._timeout = timeout
        self._id = 0

    @property
    def _url(self) -> str:
        if self._wallet is None:
            return self._base_url + "/"
        return self._base_url + f"/wallet/{self._wallet}"

    def for_wallet(self, wallet: str) -> "RpcClient":
        c = RpcClient.__new__(RpcClient)
        c._base_url = self._base_url
        c._wallet = wallet
        c._headers = self._headers
        c._timeout = self._timeout
        c._id = 0
        return c

    def call(self, method: str, *params):
        self._id += 1
        payload = json.dumps({
            "jsonrpc": "1.0",
            "id": str(self._id),
            "method": method,
            "params": list(params),
        }).encode()
        req = urllib.request.Request(self._url, data=payload, headers=self._headers)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = resp.read()
        except urllib.error.HTTPError as e:
            body = e.read()
        data = json.loads(body)
        if data.get("error"):
            err = data["error"]
            raise RpcError(err.get("code", -1), err.get("message", str(err)))
        return data["result"]

    def __getattr__(self, method: str):
        return lambda *a: self.call(method, *a)


# ---------------------------------------------------------------------------
# Regtest node lifecycle
# ---------------------------------------------------------------------------

class RegtestNode:
    """A single isolated regtest b3chaind."""

    def __init__(self, name: str = "node", workdir: Path | None = None,
                 extra_args: list[str] | None = None):
        self.name = name
        self.workdir = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix=f"b3audit_{name}_"))
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.p2p_port = free_port()
        self.rpc_port = free_port()
        self.rpc_user = "audit"
        self.rpc_password = "audit-" + str(os.getpid())
        self.extra_args = list(extra_args or [])
        self._proc: subprocess.Popen | None = None
        self._b3chaind, self._b3cli = find_binaries()
        self.rpc = RpcClient("127.0.0.1", self.rpc_port,
                             self.rpc_user, self.rpc_password)

    @property
    def datadir(self) -> Path:
        return self.workdir

    def start(self, wait_seconds: float = 30.0) -> "RegtestNode":
        cmd = [
            str(self._b3chaind),
            "-regtest",
            f"-datadir={self.workdir}",
            f"-port={self.p2p_port}",
            f"-rpcport={self.rpc_port}",
            f"-rpcuser={self.rpc_user}",
            f"-rpcpassword={self.rpc_password}",
            "-rpcbind=127.0.0.1",
            "-rpcallowip=127.0.0.0/8",
            f"-bind=127.0.0.1:{self.p2p_port}",
            "-listenonion=0", "-discover=0", "-dnsseed=0",
            "-fallbackfee=0.0001", "-maxtxfee=1",
        ] + self.extra_args
        # Capture stderr so we can show diagnostic logs when b3chaind
        # crashes during startup; pipe it into a file under the workdir.
        self._stderr_path = self.workdir / "b3chaind.stderr.log"
        self._stderr_fh = open(self._stderr_path, "w")
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=self._stderr_fh,
        )

        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            try:
                self.rpc.getblockchaininfo()
                return self
            except (RpcError, urllib.error.URLError, ConnectionError):
                if self._proc.poll() is not None:
                    # Surface the last few lines of b3chaind's stderr.
                    tail = ""
                    try:
                        with open(self._stderr_path, "r") as f:
                            tail = "".join(f.readlines()[-30:])
                    except Exception:
                        pass
                    raise RuntimeError(
                        f"{self.name}: b3chaind exited with code "
                        f"{self._proc.returncode}\n{tail}"
                    )
                time.sleep(0.25)
        raise TimeoutError(f"{self.name}: b3chaind did not respond within {wait_seconds}s")

    def connect_to(self, other: "RegtestNode") -> None:
        self.rpc.addnode(f"127.0.0.1:{other.p2p_port}", "add")

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            with contextlib.suppress(Exception):
                self.rpc.stop()
            try:
                self._proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
            self._proc = None

    def cleanup(self, *, keep_datadir: bool = False) -> None:
        self.stop()
        if not keep_datadir:
            shutil.rmtree(self.workdir, ignore_errors=True)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.cleanup()


# ---------------------------------------------------------------------------
# AuditResult — counters + pretty printer + exit-code helper
# ---------------------------------------------------------------------------

class AuditResult:
    def __init__(self, audit_id: str, title: str):
        self.audit_id = audit_id
        self.title = title
        self.checks: list[tuple[str, str, str]] = []   # (label, status, detail)
        self.passed = 0
        self.failed = 0
        self.t0 = time.time()
        print(BOLD(f"[{audit_id}] {title}"))
        print(DIM("=" * 72))

    def _add(self, label: str, status: str, detail: str = "") -> None:
        self.checks.append((label, status, detail))
        if status == "PASS":
            self.passed += 1
            print(f"  {GREEN('PASS')}  {label}" + (f"  {DIM(detail)}" if detail else ""))
        elif status == "FAIL":
            self.failed += 1
            print(f"  {RED('FAIL')}  {label}" + (f"  {detail}" if detail else ""))
        else:
            print(f"  {YELLOW('SKIP')}  {label}" + (f"  {DIM(detail)}" if detail else ""))

    def passed_check(self, label: str, detail: str = "") -> None:
        self._add(label, "PASS", detail)

    def failed_check(self, label: str, detail: str = "") -> None:
        self._add(label, "FAIL", detail)

    def skipped_check(self, label: str, detail: str = "") -> None:
        self._add(label, "SKIP", detail)

    def expect(self, condition: bool, label: str, detail: str = "") -> bool:
        if condition:
            self.passed_check(label, detail)
        else:
            self.failed_check(label, detail)
        return condition

    def expect_eq(self, actual, expected, label: str) -> bool:
        return self.expect(
            actual == expected, label,
            "" if actual == expected else f"got {actual!r}, expected {expected!r}",
        )

    def expect_raises(self, fn, expected_substring: str, label: str) -> bool:
        try:
            fn()
        except Exception as e:
            return self.expect(
                expected_substring in str(e), label,
                "" if expected_substring in str(e) else f"raised {e!r}",
            )
        return self.expect(False, label, "no exception raised")

    def finish(self) -> int:
        elapsed = time.time() - self.t0
        print(DIM("-" * 72))
        total = self.passed + self.failed
        if self.failed == 0 and self.passed > 0:
            verdict = GREEN("PASS")
            code = 0
        elif self.passed == 0 and self.failed == 0:
            verdict = YELLOW("EMPTY")
            code = 2
        else:
            verdict = RED("FAIL")
            code = 1
        print(f"  {self.passed}/{total} checks passed in {elapsed:.1f}s")
        print(BOLD(f"AUDIT RESULT: {verdict}  [{self.audit_id}]"))
        return code


# ---------------------------------------------------------------------------
# Convenience: mine helper that handles wallet creation
# ---------------------------------------------------------------------------

def ensure_wallet(node: RegtestNode, name: str = "audit") -> RpcClient:
    try:
        node.rpc.createwallet(name)
    except RpcError as e:
        if "already exists" not in e.message and "Database already exists" not in e.message:
            with contextlib.suppress(Exception):
                node.rpc.loadwallet(name)
    return node.rpc.for_wallet(name)


def mine_to(wallet_rpc: RpcClient, n: int) -> str:
    """Mine n blocks to a fresh address. Returns the address."""
    addr = wallet_rpc.getnewaddress()
    wallet_rpc.generatetoaddress(n, addr)
    return addr
