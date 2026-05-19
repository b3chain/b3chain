# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license.
"""
Environment / capability detection for the test UI.

A CapabilityProbe enumerates everything a test might depend on
(python version, blake3, miner script, b3chaind/b3chain-cli, docker,
npm, internet, the live pool) and stores the results in a dict so
the UI can grey out tests with missing prereqs.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import os
import shutil
import socket
import subprocess
import sys
from typing import Optional


# ---------------------------------------------------------------------------
# Paths the UI needs to know about
# ---------------------------------------------------------------------------

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
MINER_DIR = os.path.dirname(THIS_DIR)
REPO_ROOT_GUESS = os.path.dirname(os.path.dirname(MINER_DIR))  # b3chain/

MINER_SCRIPT = os.path.join(MINER_DIR, "b3chain-cpuminer.py")
MOCK_TEST_SCRIPT = os.path.join(MINER_DIR, "test_pool_miner.py")
POOL_DIR = os.path.join(REPO_ROOT_GUESS, "contrib", "testnet", "pool")

# Optional GPU backend. The crate lives next to the CPU miner; the
# binary is produced by `cargo build --release` in
# contrib/miner/b3chain-gpuminer/. We probe both windows / unix exe
# names so the dashboard can offer a "Backend: GPU" option only when
# the build artifact actually exists.
GPU_MINER_DIR = os.path.join(MINER_DIR, "b3chain-gpuminer")
_GPU_EXE_NAMES = ("b3chain-gpuminer.exe", "b3chain-gpuminer")


def gpu_miner_binary_path() -> Optional[str]:
    """Return the path to a built b3chain-gpuminer binary, or None.

    Looks under <crate>/target/release/ first (the canonical Cargo
    layout) and falls back to <crate>/target/debug/ for development.
    """
    for sub in ("release", "debug"):
        for name in _GPU_EXE_NAMES:
            cand = os.path.join(GPU_MINER_DIR, "target", sub, name)
            if os.path.exists(cand):
                return cand
    return None

LIVE_POOL_HOST = "pool.b3chain.org"
LIVE_POOL_PORT = 3333


# ---------------------------------------------------------------------------
# Capability dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Capability:
    """One environment capability with present/absent + an explanatory detail."""
    key: str
    label: str
    present: bool
    detail: str = ""

    @property
    def status_text(self) -> str:
        return "OK" if self.present else "--"


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------


def _probe_python() -> Capability:
    v = sys.version_info
    ok = v >= (3, 9)
    return Capability(
        key="python",
        label="Python",
        present=ok,
        detail=f"{v.major}.{v.minor}.{v.micro}",
    )


def _probe_blake3() -> Capability:
    spec = importlib.util.find_spec("blake3")
    if spec is None:
        return Capability(key="blake3", label="blake3", present=False,
                          detail="not installed (pip install blake3)")
    try:
        import blake3 as _b3  # noqa: F401
        return Capability(key="blake3", label="blake3", present=True,
                          detail=getattr(_b3, "__version__", "unknown"))
    except Exception as e:  # pragma: no cover
        return Capability(key="blake3", label="blake3", present=False,
                          detail=f"import error: {e}")


def _probe_miner() -> Capability:
    if os.path.exists(MINER_SCRIPT):
        return Capability(key="miner", label="miner.py", present=True,
                          detail=MINER_SCRIPT)
    return Capability(key="miner", label="miner.py", present=False,
                      detail=f"not found at {MINER_SCRIPT}")


def _probe_mock_test() -> Capability:
    if os.path.exists(MOCK_TEST_SCRIPT):
        return Capability(key="mock_test", label="test_pool_miner.py",
                          present=True, detail=MOCK_TEST_SCRIPT)
    return Capability(key="mock_test", label="test_pool_miner.py",
                      present=False,
                      detail=f"not found at {MOCK_TEST_SCRIPT}")


def _which_any(*names: str) -> Optional[str]:
    for n in names:
        path = shutil.which(n)
        if path:
            return path
    return None


def _probe_b3chaind() -> Capability:
    # On Windows the binary is b3chaind.exe; on POSIX, b3chaind.
    path = _which_any("b3chaind.exe", "b3chaind")
    if not path:
        return Capability(key="b3chaind", label="b3chaind", present=False,
                          detail="not on PATH")
    return Capability(key="b3chaind", label="b3chaind", present=True,
                      detail=path)


def _probe_b3chain_cli() -> Capability:
    path = _which_any("b3chain-cli.exe", "b3chain-cli")
    if not path:
        return Capability(key="b3chain-cli", label="b3chain-cli",
                          present=False, detail="not on PATH")
    return Capability(key="b3chain-cli", label="b3chain-cli",
                      present=True, detail=path)


def _probe_docker() -> Capability:
    path = _which_any("docker.exe", "docker")
    if not path:
        return Capability(key="docker", label="docker", present=False,
                          detail="not on PATH (Docker Desktop required)")
    # Docker on PATH is necessary but not sufficient: the daemon must be running.
    try:
        out = subprocess.run([path, "info", "--format", "{{.ServerVersion}}"],
                             capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            return Capability(key="docker", label="docker", present=True,
                              detail=f"Server {out.stdout.strip()}")
        return Capability(key="docker", label="docker", present=False,
                          detail="daemon not running")
    except (subprocess.TimeoutExpired, OSError) as e:
        return Capability(key="docker", label="docker", present=False,
                          detail=f"info failed: {e}")


def _probe_npm() -> Capability:
    path = _which_any("npm.cmd", "npm.exe", "npm")
    if not path:
        return Capability(key="npm", label="npm", present=False,
                          detail="not on PATH")
    return Capability(key="npm", label="npm", present=True, detail=path)


def _probe_internet() -> Capability:
    """DNS-resolve the live pool. Cheap and reliable as an internet probe."""
    try:
        addr = socket.gethostbyname(LIVE_POOL_HOST)
        return Capability(key="internet", label="internet",
                          present=True, detail=f"{LIVE_POOL_HOST} -> {addr}")
    except (socket.gaierror, OSError) as e:
        return Capability(key="internet", label="internet",
                          present=False, detail=f"DNS failed: {e}")


def _probe_live_pool() -> Capability:
    """Open a TCP socket to pool.b3chain.org:3333. Quick reachability check."""
    try:
        with socket.create_connection((LIVE_POOL_HOST, LIVE_POOL_PORT),
                                      timeout=3.0) as s:
            s.settimeout(1.0)
            return Capability(key="live_pool", label="pool.b3chain.org:3333",
                              present=True,
                              detail=f"connected ({s.getpeername()[0]}:{LIVE_POOL_PORT})")
    except (OSError, socket.timeout) as e:
        return Capability(key="live_pool", label="pool.b3chain.org:3333",
                          present=False, detail=f"unreachable: {e}")


def _probe_pool_dir() -> Capability:
    """The Node.js pool source tree (for the local dev stack test)."""
    pkg_json = os.path.join(POOL_DIR, "package.json")
    if os.path.exists(pkg_json):
        return Capability(key="pool_src", label="pool source",
                          present=True, detail=POOL_DIR)
    return Capability(key="pool_src", label="pool source", present=False,
                      detail=f"not found at {POOL_DIR}")


# ---------------------------------------------------------------------------
# Main probe
# ---------------------------------------------------------------------------


class CapabilityProbe:
    """Aggregates all probes into a single dict the UI/tests can query."""

    PROBES = (
        _probe_python,
        _probe_blake3,
        _probe_miner,
        _probe_mock_test,
        _probe_b3chaind,
        _probe_b3chain_cli,
        _probe_docker,
        _probe_npm,
        _probe_internet,
        _probe_live_pool,
        _probe_pool_dir,
    )

    def __init__(self) -> None:
        self._caps: dict = {}
        self.refresh()

    def refresh(self) -> None:
        """Re-run every probe. Called from MainWindow.__init__ AND on Recheck."""
        self._caps = {}
        for fn in self.PROBES:
            try:
                cap = fn()
            except Exception as e:  # pragma: no cover -- probe should not crash UI
                cap = Capability(key=fn.__name__, label=fn.__name__,
                                 present=False, detail=f"probe error: {e}")
            self._caps[cap.key] = cap

    def __getitem__(self, key: str) -> Capability:
        return self._caps[key]

    def get(self, key: str) -> Optional[Capability]:
        return self._caps.get(key)

    def has(self, key: str) -> bool:
        cap = self._caps.get(key)
        return bool(cap and cap.present)

    def missing(self, keys) -> list:
        return [k for k in keys if not self.has(k)]

    def all(self) -> list:
        return list(self._caps.values())

    def as_dict(self) -> dict:
        return {k: dataclasses.asdict(v) for k, v in self._caps.items()}


if __name__ == "__main__":
    # CLI smoke test
    p = CapabilityProbe()
    for c in p.all():
        marker = "[OK]" if c.present else "[--]"
        print(f"  {marker} {c.label:24s} {c.detail}")
