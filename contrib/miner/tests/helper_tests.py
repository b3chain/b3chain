# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license.
"""
In-process unit tests for the b3chain miner.

Two distinct entry points used by the UI:

  run_helper_unit_tests(emit) -- Test 2: imports the miner module
  directly and calls each helper with known-answer vectors.

  run_jsonl_rederive(emit) -- Test 6: spawns the existing mock pool
  (test_pool_miner.MockStratumServer) in-process, runs the real miner
  with --max-attempts 5 --json-log <tmp>, then re-hashes every
  recorded share's header_hex and asserts BLAKE3(BLAKE3) byte-equality
  with pow_hash_le.

Both functions take an `emit(line: str)` callback so the UI can stream
their output. They return a (passed: bool, metric: str) tuple.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from typing import Callable, List, Tuple

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
MINER_DIR = os.path.dirname(THIS_DIR)
MINER_SCRIPT = os.path.join(MINER_DIR, "b3chain-cpuminer.py")
MOCK_TEST_SCRIPT = os.path.join(MINER_DIR, "test_pool_miner.py")


def _import_miner_module():
    """Load b3chain-cpuminer.py as a module (it has a hyphen in its name)."""
    spec = importlib.util.spec_from_file_location("b3chain_cpuminer", MINER_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load miner module at {MINER_SCRIPT}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _import_mock_test_module():
    spec = importlib.util.spec_from_file_location("test_pool_miner", MOCK_TEST_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load mock test module at {MOCK_TEST_SCRIPT}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Test 2 -- Helper unit tests with known-answer vectors
# ---------------------------------------------------------------------------


def run_helper_unit_tests(emit: Callable[[str], None]) -> Tuple[bool, str]:
    """Test the miner's pool-mode helpers against known-answer vectors.

    Vectors:

      * parse_stratum_url -- accepts +tcp/+ssl/+tcp+ssl, rejects sv2.
      * target_from_share_difficulty -- D=1 -> POOL_DIFF1_TARGET; D=2 -> half;
        D=1024 mirrors the value the pool computes.
      * network_difficulty_from_bits -- bits=0x1d00ffff -> 1.0 exactly.
      * build_coinbase_full -- splice points are exactly between en1 and en2.
      * compute_merkle_root_from_branches -- with no branches, root == coinbase
        txid LE.
      * compute_merkle_root_from_branches -- 1-branch SHA256d(txid_le || br_le).
    """

    try:
        m = _import_miner_module()
    except Exception as e:
        emit(f"FAIL: cannot import miner: {e}")
        return False, f"import error: {e}"

    passes: List[str] = []
    fails: List[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        if ok:
            emit(f"  [PASS] {name}  {detail}")
            passes.append(name)
        else:
            emit(f"  [FAIL] {name}  {detail}")
            fails.append(name)

    # ---- parse_stratum_url ----
    try:
        host, port, tls = m.parse_stratum_url("stratum+tcp://pool.b3chain.org:3333")
        check("parse_stratum_url +tcp",
              host == "pool.b3chain.org" and port == 3333 and tls is False,
              f"-> {host}:{port} tls={tls}")
    except Exception as e:
        check("parse_stratum_url +tcp", False, str(e))

    try:
        host, port, tls = m.parse_stratum_url("stratum+ssl://x:1")
        check("parse_stratum_url +ssl",
              host == "x" and port == 1 and tls is True,
              f"-> {host}:{port} tls={tls}")
    except Exception as e:
        check("parse_stratum_url +ssl", False, str(e))

    try:
        host, port, tls = m.parse_stratum_url("stratum+tcp+ssl://x:1")
        check("parse_stratum_url +tcp+ssl",
              host == "x" and port == 1 and tls is True,
              f"-> {host}:{port} tls={tls}")
    except Exception as e:
        check("parse_stratum_url +tcp+ssl", False, str(e))

    try:
        host, port, tls = m.parse_stratum_url("127.0.0.1:3333")
        check("parse_stratum_url scheme-less",
              host == "127.0.0.1" and port == 3333 and tls is False,
              f"-> {host}:{port} tls={tls}")
    except Exception as e:
        check("parse_stratum_url scheme-less", False, str(e))

    try:
        m.parse_stratum_url("stratum2://x:1")
        check("parse_stratum_url rejects sv2", False, "did not raise")
    except ValueError as e:
        check("parse_stratum_url rejects sv2", True, "raised ValueError")
    except Exception as e:
        check("parse_stratum_url rejects sv2", False, f"wrong exc: {e}")

    # ---- target_from_share_difficulty ----
    POOL_DIFF1 = 0x00000000ffff0000000000000000000000000000000000000000000000000000
    check("POOL_DIFF1_TARGET constant",
          m.POOL_DIFF1_TARGET == POOL_DIFF1,
          f"= {m.POOL_DIFF1_TARGET:064x}")
    t1 = m.target_from_share_difficulty(1)
    check("target(diff=1) == POOL_DIFF1_TARGET",
          t1 == POOL_DIFF1, f"-> 0x{t1:064x}")
    t2 = m.target_from_share_difficulty(2)
    # exact: floor((POOL_DIFF1 * 1_000_000) // 2_000_000)
    exp_t2 = (POOL_DIFF1 * 1_000_000) // 2_000_000
    check("target(diff=2) == POOL_DIFF1/2 (with scaling)",
          t2 == exp_t2, f"-> 0x{t2:064x}")
    t1024 = m.target_from_share_difficulty(1024)
    exp_t1024 = (POOL_DIFF1 * 1_000_000) // (1024 * 1_000_000)
    check("target(diff=1024) matches scaled formula",
          t1024 == exp_t1024, f"-> 0x{t1024:064x}")

    # ---- network_difficulty_from_bits ----
    nd = m.network_difficulty_from_bits(0x1d00ffff)
    check("network_difficulty(bits=0x1d00ffff) ~= 1.0",
          abs(nd - 1.0) < 1e-9, f"-> {nd}")

    # ---- build_coinbase_full ----
    coinb1 = bytes.fromhex("aabbccdd")
    en1 = bytes.fromhex("11223344")
    en2 = bytes.fromhex("55667788")
    coinb2 = bytes.fromhex("ee")
    cb = m.build_coinbase_full(coinb1, en1, en2, coinb2)
    expected = bytes.fromhex("aabbccdd11223344556677880000".replace("0000", "")) + bytes.fromhex("ee")
    expected = coinb1 + en1 + en2 + coinb2
    check("build_coinbase_full splice order",
          cb == expected, f"-> {cb.hex()}")

    # ---- compute_merkle_root_from_branches ----
    # With no branches, root LE == coinbase txid LE.
    cb_txid_le = m.double_sha256(cb)
    root0 = m.compute_merkle_root_from_branches(cb_txid_le, [])
    check("merkle root (0 branches) == cb_txid_le",
          root0 == cb_txid_le, f"-> {root0.hex()}")

    # With one branch, root LE == double_sha256(cb_txid_le || br_le).
    branch_be = bytes.fromhex(
        "0102030405060708090a0b0c0d0e0f1011121314151617181920212223242526")
    br_le = branch_be[::-1]
    expected1 = m.double_sha256(cb_txid_le + br_le)
    root1 = m.compute_merkle_root_from_branches(cb_txid_le, [branch_be])
    check("merkle root (1 branch) == SHA256d(txid_le || br_le)",
          root1 == expected1, f"-> {root1.hex()}")

    # ---- serialize_header sanity (80 bytes, layout) ----
    hdr = m.serialize_header(
        version=0x20000000,
        prev_hash=b"\x11" * 32,
        merkle_root=b"\x22" * 32,
        timestamp=0x6643b257,
        bits=0x207fffff,
        nonce=0xdeadbeef,
    )
    check("serialize_header is 80 bytes",
          len(hdr) == 80, f"-> {len(hdr)}B")
    check("serialize_header version slice",
          hdr[0:4] == bytes.fromhex("00000020"), f"-> {hdr[0:4].hex()}")
    check("serialize_header nonce slice (LE)",
          hdr[76:80] == bytes.fromhex("efbeadde"),
          f"-> {hdr[76:80].hex()}")

    total = len(passes) + len(fails)
    metric = f"{len(passes)}/{total} asserts"
    if fails:
        emit(f"FAIL: {len(fails)} assertion(s) failed")
        return False, metric
    emit(f"PASS: {metric}")
    return True, metric


# ---------------------------------------------------------------------------
# Test 6 -- JSONL re-derivation
# ---------------------------------------------------------------------------


def run_jsonl_rederive(emit: Callable[[str], None]) -> Tuple[bool, str]:
    """Spin up the in-process mock pool, run the real miner with --max-attempts 5
    --json-log, then re-hash every recorded share's header and assert byte-equal.

    Mirrors test_pool_miner.py but exposes the verification step as a separate
    UI-runnable test so the operator can see it pass independently of the E2E.
    """
    try:
        import blake3
    except ImportError:
        emit("FAIL: blake3 not installed")
        return False, "blake3 missing"

    mt = _import_mock_test_module()

    srv = mt.MockStratumServer()
    srv.start()
    emit(f"  mock pool listening on 127.0.0.1:{srv.port}")

    fd, jsonl_path = tempfile.mkstemp(suffix=".jsonl",
                                      prefix="b3chain-rederive-")
    os.close(fd)

    cmd = [
        sys.executable, MINER_SCRIPT,
        "--stratum", f"stratum+tcp://127.0.0.1:{srv.port}",
        "--user", "rederive@b3chain.org.cpu1",
        "--pass", "x",
        "--threads", "1",
        "--max-attempts", "5",
        "--progress-interval", "100000",
        "--quiet-progress",
        "--json-log", jsonl_path,
    ]
    emit(f"  running miner: {' '.join(cmd[1:])}")

    try:
        proc = subprocess.run(cmd, timeout=120,
                              capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        srv.stop()
        emit("FAIL: miner timed out after 120s")
        return False, "timeout"
    finally:
        srv.stop()

    if proc.returncode != 0:
        emit(f"FAIL: miner exited rc={proc.returncode}")
        emit(proc.stderr.strip()[-500:])
        return False, f"miner rc={proc.returncode}"

    server_received = srv.shares_received
    emit(f"  server received {server_received} shares")

    submitted = 0
    verified = 0
    mismatches: List[int] = []
    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for raw in f:
                try:
                    obj = json.loads(raw)
                except ValueError:
                    continue
                if obj.get("event") != "share_submit":
                    continue
                submitted += 1
                seq = obj.get("share_seq")
                header = bytes.fromhex(obj["header_hex"])
                expected = obj["pow_hash_le"]
                got = blake3.blake3(blake3.blake3(header).digest()).digest().hex()
                if got == expected:
                    verified += 1
                else:
                    mismatches.append(seq)
                    emit(f"  MISMATCH share #{seq}:")
                    emit(f"    expected = {expected}")
                    emit(f"    got      = {got}")
    finally:
        try:
            os.unlink(jsonl_path)
        except OSError:
            pass

    emit(f"  share_submit JSONL entries: {submitted}; BLAKE3d verified: {verified}")
    metric = f"{verified}/{submitted} verified"
    ok = (server_received >= 5 and submitted >= 5 and verified == submitted
          and not mismatches)
    if ok:
        emit("PASS: every recorded share's header re-hashes to its pow_hash_le")
    else:
        emit(f"FAIL: server={server_received} submitted={submitted} verified={verified}")
    return ok, metric


# ---------------------------------------------------------------------------
# CLI entry points (so the UI can run these in a subprocess if it wants to)
# ---------------------------------------------------------------------------


def _cli_emit(line: str) -> None:
    print(line, flush=True)


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    rc = 0
    if which in ("all", "unit"):
        ok, metric = run_helper_unit_tests(_cli_emit)
        print(f"unit -> {'PASS' if ok else 'FAIL'} ({metric})")
        if not ok:
            rc = 1
    if which in ("all", "rederive"):
        ok, metric = run_jsonl_rederive(_cli_emit)
        print(f"rederive -> {'PASS' if ok else 'FAIL'} ({metric})")
        if not ok:
            rc = 1
    sys.exit(rc)
