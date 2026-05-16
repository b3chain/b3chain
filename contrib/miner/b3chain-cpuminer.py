#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
b3chain reference CPU miner

A simple CPU miner for b3chain that supports two modes:

  1. Solo mining via b3chaind getblocktemplate/submitblock RPC (BIP 22/23).
  2. Pool mining via Stratum V1 (the protocol pool.b3chain.org:3333 speaks --
     see contrib/testnet/pool/docs/STRATUM-PROTOCOL.md).

Both modes use double BLAKE3-256 proof-of-work.

In pool mode every share submitted to the pool is logged with byte-level
detail (job id, both extranonces, ntime, nonce, full coinbase tx, coinbase
txid, merkle root, 80-byte header, PoW hash LE+BE, block hash, share/network
targets, accepted/rejected status, RTT). Between shares, periodic
"best-hash-so-far" progress lines are emitted so the operator can see the
nonce search progressing. An optional --json-log file records every event
(connect, subscribed, authorized, set_difficulty, notify, progress,
share_submit, block_found, disconnect, summary) as one JSON object per line.

This miner is intended for:
  - Solo mining on regtest/testnet
  - Pool mining as a reference implementation for pool software developers
  - Verifying that the BLAKE3 PoW pipeline works end-to-end

It is NOT optimized for production mining. For mainnet mining, use a
dedicated miner with multi-threaded or GPU support.

Requirements:
  pip3 install blake3

Solo-mode usage:
  python3 b3chain-cpuminer.py --regtest --coinbaseaddr b3rt1q...

Pool-mode usage:
  python3 b3chain-cpuminer.py \
      --stratum stratum+tcp://pool.b3chain.org:3333 \
      --user alice@example.com.cpu1 --pass x \
      --threads 2 --json-log shares.jsonl

Solo mode flags:
  --rpcuser USER         RPC username (default: from cookie)
  --rpcpassword PASS     RPC password (default: from cookie)
  --rpcconnect HOST      RPC host (default: 127.0.0.1)
  --rpcport PORT         RPC port (default: 8534)
  --coinbaseaddr ADDR    Address for coinbase reward (required for solo)
  --coinbasemsg TEXT     Extra text in coinbase (optional, max 92 bytes)
  --datadir DIR          Data directory for cookie auth (default: ~/.b3chain)
  --regtest              Use regtest parameters (port 18545)
  --testnet              Use testnet parameters (port 18534)

Pool mode flags:
  --stratum URL          Pool URL, e.g. stratum+tcp://pool.b3chain.org:3333
  --user USER            Pool worker username, typically <email>.<worker>
  --pass PASS            Pool password (ignored by the pool, default "x")
  --useragent STRING     User-agent for mining.subscribe (default b3chain-cpuminer/1.0)
  --json-log PATH        Append-only JSONL file recording every share + event
  --quiet-progress       Suppress per-N-hash progress lines on stdout
  --progress-interval N  Internal-hash count between progress lines (default 1_000_000)
  --reconnect-delay SEC  Reconnect backoff base seconds (default 5; cap 60)
  --max-attempts N       Stop after N share submissions (0 = forever)

Common flags:
  --threads N            Number of mining threads (default: 1)
  --benchmark            Run a 10-second hash rate benchmark and exit
  --verbose              Print extra debug info
"""

import argparse
import base64
import dataclasses
import datetime as _dt
import http.client
import json
import os
import queue
import random
import signal
import socket
import ssl
import struct
import sys
import threading
import time
import hashlib
from typing import Any, List, Optional, Tuple

try:
    import blake3
except ImportError:
    print("ERROR: The 'blake3' Python package is required.")
    print("Install with: pip3 install blake3")
    sys.exit(1)


USER_AGENT_DEFAULT = "b3chain-cpuminer/1.0"

# Pool diff-1 target -- standard Bitcoin/Stratum convention.
# A share at difficulty D meets the share target when its PoW hash <=
# (POOL_DIFF1_TARGET / D). See contrib/testnet/pool/src/lib/difficulty-math.ts.
POOL_DIFF1_TARGET = 0x00000000ffff0000000000000000000000000000000000000000000000000000


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

def double_blake3(data: bytes) -> bytes:
    """Compute BLAKE3(BLAKE3(data)) -- b3chain PoW hash."""
    h1 = blake3.blake3(data).digest()
    return blake3.blake3(h1).digest()


def double_sha256(data: bytes) -> bytes:
    """Compute SHA256(SHA256(data)) -- used for block identity hash and merkle tree."""
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def uint256_from_hex_le(hex_str: str) -> bytes:
    """Convert a hex string (big-endian display) to 32 bytes little-endian."""
    return bytes.fromhex(hex_str)[::-1]


def ser_uint256_le(val: int) -> bytes:
    """Serialize a uint256 integer to 32 bytes little-endian."""
    return val.to_bytes(32, byteorder='little')


def target_from_nbits(nbits: int) -> int:
    """Convert compact nBits to a 256-bit target integer."""
    exp = nbits >> 24
    mant = nbits & 0x7fffff
    if exp <= 3:
        mant >>= 8 * (3 - exp)
    else:
        mant <<= 8 * (exp - 3)
    return mant


def serialize_header(version: int, prev_hash: bytes, merkle_root: bytes,
                     timestamp: int, bits: int, nonce: int) -> bytes:
    """Serialize an 80-byte block header."""
    header = struct.pack('<i', version)
    header += prev_hash      # 32 bytes, little-endian
    header += merkle_root    # 32 bytes, little-endian
    header += struct.pack('<I', timestamp)
    header += struct.pack('<I', bits)
    header += struct.pack('<I', nonce)
    return header


def varint_bytes(n: int) -> bytes:
    """Bitcoin-style compact size encoding (used to serialise tx counts)."""
    if n < 0xfd:
        return struct.pack('<B', n)
    if n <= 0xffff:
        return struct.pack('<BH', 0xfd, n)
    if n <= 0xffffffff:
        return struct.pack('<BI', 0xfe, n)
    return struct.pack('<BQ', 0xff, n)


def target_from_share_difficulty(share_diff: float) -> int:
    """shareTarget = floor(POOL_DIFF1_TARGET / shareDifficulty).

    Mirrors targetFromShareDifficulty() in
    contrib/testnet/pool/src/lib/difficulty-math.ts so the share target the
    miner computes is byte-identical to what the pool computes.
    """
    if share_diff is None or share_diff <= 0:
        return (1 << 256) - 1
    scale = 1_000_000
    scaled = int(share_diff * scale)
    if scaled <= 0:
        return (1 << 256) - 1
    return (POOL_DIFF1_TARGET * scale) // scaled


def network_difficulty_from_bits(bits: int) -> float:
    """Diff-1-units network difficulty corresponding to the given nBits."""
    target = target_from_nbits(bits)
    if target <= 0:
        return float("inf")
    scale = 10_000_000
    return ((POOL_DIFF1_TARGET * scale) // target) / scale


def parse_stratum_url(url: str) -> Tuple[str, int, bool]:
    """Parse stratum URL. Returns (host, port, use_tls).

    Accepts:
      stratum+tcp://host:port
      stratum+ssl://host:port    (TLS)
      stratum+tcp+ssl://host:port (TLS)
      host:port                  (plain TCP, no scheme)
    """
    use_tls = False
    raw = url.strip()
    if raw.startswith("stratum2://"):
        raise ValueError(
            "Stratum V2 (stratum2://) is not supported by this miner. "
            "Use the pool's V1 endpoint at stratum+tcp://...:3333."
        )
    if raw.startswith("stratum+tcp+ssl://") or raw.startswith("stratum+ssl://"):
        use_tls = True
        raw = raw.split("://", 1)[1]
    elif raw.startswith("stratum+tcp://"):
        raw = raw.split("://", 1)[1]
    elif "://" in raw:
        scheme = raw.split("://", 1)[0]
        raise ValueError(f"Unknown stratum URL scheme '{scheme}://' in {url!r}")
    if "/" in raw:
        raw = raw.split("/", 1)[0]
    if ":" not in raw:
        raise ValueError(f"Stratum URL missing port: {url!r}")
    host, port_s = raw.rsplit(":", 1)
    try:
        port = int(port_s)
    except ValueError as e:
        raise ValueError(f"Bad port in stratum URL {url!r}: {port_s}") from e
    if not host:
        raise ValueError(f"Stratum URL missing host: {url!r}")
    return host, port, use_tls


# ---------------------------------------------------------------------------
# Console / JSONL helpers (used by pool mode)
# ---------------------------------------------------------------------------


def utc_iso(now: float) -> str:
    """ISO-8601 UTC timestamp with millisecond precision."""
    d = _dt.datetime.fromtimestamp(now, tz=_dt.timezone.utc)
    ms = int((now - int(now)) * 1000)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def fmt_int(n: int) -> str:
    return f"{n:,}"


def fmt_hashrate(hps: float) -> str:
    if hps >= 1e12:
        return f"{hps/1e12:.2f} TH/s"
    if hps >= 1e9:
        return f"{hps/1e9:.2f} GH/s"
    if hps >= 1e6:
        return f"{hps/1e6:.2f} MH/s"
    if hps >= 1e3:
        return f"{hps/1e3:.2f} kH/s"
    return f"{hps:.0f} H/s"


def _wrap_hex(h: str, width: int = 64,
              indent: str = "                        ") -> str:
    """Wrap a long hex string into width-character lines for readable dumps."""
    if len(h) <= width:
        return h
    parts = [h[0:width]]
    i = width
    while i < len(h):
        parts.append(indent + h[i:i + width])
        i += width
    return "\n".join(parts)


def _json_default(o: Any) -> Any:
    if isinstance(o, bytes):
        return o.hex()
    if isinstance(o, (set, frozenset)):
        return list(o)
    if dataclasses.is_dataclass(o):
        return dataclasses.asdict(o)
    raise TypeError(f"Cannot JSON-serialise {type(o).__name__}")


class JsonlLogger:
    """Append-only JSONL logger.

    One JSON object per line, flushed after every emit. Thread-safe.
    Writes nothing if path is None, so callers can unconditionally emit().
    """

    def __init__(self, path: Optional[str]):
        self.path = path
        self.lock = threading.Lock()
        if path:
            self.fp = open(path, "a", buffering=1, encoding="utf-8")
        else:
            self.fp = None

    def emit(self, event: str, **fields: Any) -> None:
        if self.fp is None:
            return
        obj = {"ts": time.time(), "event": event}
        obj.update(fields)
        try:
            line = json.dumps(obj, separators=(",", ":"), default=_json_default)
        except (TypeError, ValueError):
            # Last-resort: stringify any remaining non-JSON values.
            safe = {k: (v if isinstance(v, (str, int, float, bool, list, dict, type(None))) else repr(v))
                    for k, v in obj.items()}
            line = json.dumps(safe, separators=(",", ":"))
        with self.lock:
            self.fp.write(line + "\n")
            self.fp.flush()

    def close(self) -> None:
        with self.lock:
            if self.fp is not None:
                try:
                    self.fp.close()
                finally:
                    self.fp = None


# ---------------------------------------------------------------------------
# RPC client
# ---------------------------------------------------------------------------

class RPCError(Exception):
    pass


class RPCClient:
    """Minimal JSON-RPC client for b3chaind."""

    def __init__(self, host, port, user, password):
        self.host = host
        self.port = port
        self.auth = f"{user}:{password}"
        self._id = 0

    def call(self, method, params=None):
        self._id += 1
        payload = json.dumps({
            "jsonrpc": "2.0",
            "id": self._id,
            "method": method,
            "params": params or [],
        })
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Basic " + __import__('base64').b64encode(
                self.auth.encode()).decode(),
        }
        conn = http.client.HTTPConnection(self.host, self.port, timeout=300)
        conn.request("POST", "/", payload, headers)
        resp = conn.getresponse()
        body = resp.read().decode()
        conn.close()

        if resp.status != 200:
            raise RPCError(f"HTTP {resp.status}: {body}")

        result = json.loads(body)
        if result.get("error"):
            raise RPCError(f"RPC error: {result['error']}")
        return result["result"]


def read_cookie(datadir: str) -> tuple:
    """Read RPC credentials from the .cookie file."""
    cookie_path = os.path.join(datadir, ".cookie")
    if not os.path.exists(cookie_path):
        # Try regtest/testnet subdirectories
        for subdir in ["regtest", "testnet3", "testnet4", "signet", ""]:
            path = os.path.join(datadir, subdir, ".cookie")
            if os.path.exists(path):
                cookie_path = path
                break
        else:
            return None, None

    with open(cookie_path, "r") as f:
        cookie = f.read().strip()
    user, password = cookie.split(":", 1)
    return user, password


# ---------------------------------------------------------------------------
# Block template processing
# ---------------------------------------------------------------------------

def build_coinbase_from_template(template: dict, coinbase_addr: str,
                                 coinbase_msg: str = "") -> bytes:
    """
    Build a coinbase transaction from a getblocktemplate response.

    For simplicity, this uses createrawtransaction-style construction.
    In production, a miner would build this more carefully with proper
    scriptSig and witness commitment.
    """
    # The template provides a full coinbasetxn if available
    if "coinbasetxn" in template:
        return bytes.fromhex(template["coinbasetxn"]["data"])
    # Otherwise we'd need to construct one -- for solo mining with
    # getblocktemplate, coinbasetxn should be provided when we request it
    raise RPCError("Template does not include coinbasetxn. "
                   "Ensure b3chaind is started with wallet support or "
                   "provide a mining address via -blocknotify.")


def build_merkle_root(coinbase_hash: bytes, tx_hashes: list) -> bytes:
    """Compute the merkle root from coinbase + transaction hashes."""
    hashes = [coinbase_hash] + tx_hashes
    while len(hashes) > 1:
        if len(hashes) % 2 != 0:
            hashes.append(hashes[-1])
        new_hashes = []
        for i in range(0, len(hashes), 2):
            new_hashes.append(double_sha256(hashes[i] + hashes[i + 1]))
        hashes = new_hashes
    return hashes[0]


def get_block_hex(header: bytes, txns_hex: list) -> str:
    """Assemble a full block from header and transaction hex strings."""
    # Compact size for tx count
    n = len(txns_hex)
    if n < 253:
        count = struct.pack('<B', n)
    elif n < 0x10000:
        count = struct.pack('<BH', 253, n)
    else:
        count = struct.pack('<BI', 254, n)

    block = header + count
    for tx_hex in txns_hex:
        block += bytes.fromhex(tx_hex)
    return block.hex()


# ---------------------------------------------------------------------------
# Pool mode: data structures
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class CurrentJob:
    """A snapshot of the current mining.notify job from the pool.

    Field formats follow the wire protocol (Stratum V1):
      - prev_hash_be_hex   : 64-hex chars, big-endian display order
                             (must be reversed to LE before insertion in the
                             80-byte header)
      - coinb1, coinb2     : raw bytes; the full coinbase tx is
                             coinb1 || extranonce1 || extranonce2 || coinb2
      - merkle_branches_be : list of 32-byte hashes, BE display order on the
                             wire; reverse each to LE before concatenation
      - version, bits, ntime: integers parsed from "0x..." hex on the wire
    """
    job_id: str
    prev_hash_be_hex: str
    coinb1: bytes
    coinb2: bytes
    merkle_branches_be: List[bytes]
    version: int
    bits: int
    ntime: int
    clean_jobs: bool
    received_at: float
    network_target: int
    network_difficulty: float


@dataclasses.dataclass
class Share:
    """A share that meets share difficulty and is about to be submitted."""
    seq: int
    job_id: str
    extranonce1_hex: str
    extranonce2_hex: str
    ntime: int
    nonce: int
    coinbase: bytes
    coinbase_txid_le: bytes
    merkle_root_le: bytes
    header: bytes               # 80 bytes
    pow_le: bytes               # BLAKE3(BLAKE3(header)), little-endian raw
    pow_int: int                # int.from_bytes(pow_le, "little")
    block_hash_le: bytes        # SHA256d(header), little-endian raw
    share_target: int
    share_difficulty: float
    network_target: int
    network_difficulty: float
    is_block: bool              # pow_int <= network_target
    found_at: float
    attempts_for_job: int
    thread_idx: int


def build_coinbase_full(coinb1: bytes, en1: bytes, en2: bytes, coinb2: bytes) -> bytes:
    """Splice the coinbase tx as the pool expects.

    Mirrors share-validator.ts:67 -- the pool pre-splits the coinbase into
    coinb1/coinb2 around an 8-byte placeholder so the miner can splice
    en1 || en2 between the halves.
    """
    return coinb1 + en1 + en2 + coinb2


def compute_merkle_root_from_branches(coinbase_txid_le: bytes,
                                      branches_be: List[bytes]) -> bytes:
    """Fold the coinbase txid (LE) with each merkle branch (BE on wire).

    Mirrors computeMerkleRoot() in share-validator.ts via the same
    branch reversal as job-manager.ts:243-251 (combineHashesBE).
    """
    cur = coinbase_txid_le
    for br_be in branches_be:
        cur = double_sha256(cur + br_be[::-1])
    return cur


# ---------------------------------------------------------------------------
# Pool mode: Stratum V1 client
# ---------------------------------------------------------------------------


class StratumDisconnected(Exception):
    """Raised when the Stratum TCP connection drops or fails handshake."""
    pass


class StratumPoolClient:
    """Stratum V1 client.

    Owns:
      * A TCP socket and a single dedicated reader thread that parses
        newline-delimited JSON-RPC messages and dispatches them by id
        (responses) or method (notifications).
      * A request id counter and a dict of pending response futures.
      * Mining state shared with workers under self.state_lock:
        extranonce1, extranonce2_size, share_difficulty, share_target,
        current_job, clean_epoch (incremented on every notify with
        clean_jobs=true AND on every (re)connect to invalidate stale
        en1 in worker threads).

    The reader-thread design mirrors the server-side framing in
    contrib/testnet/pool/src/stratum/client.ts (newline-delimited JSON
    with line accumulation across recv() boundaries).
    """

    def __init__(self,
                 host: str, port: int, use_tls: bool,
                 user: str, password: str, useragent: str,
                 logger: JsonlLogger,
                 default_diff: float = 1024.0,
                 verbose: bool = False):
        self.host = host
        self.port = port
        self.use_tls = use_tls
        self.user = user
        self.password = password
        self.useragent = useragent
        self.logger = logger
        self.verbose = verbose

        self.sock: Optional[socket.socket] = None
        self.sock_lock = threading.Lock()  # serialise writes
        self.recv_buf = b""
        self.reader_thread: Optional[threading.Thread] = None

        self._next_id = 1
        self._next_id_lock = threading.Lock()
        self._pending: dict = {}  # id -> (Event, [result, error, t0])
        self._pending_lock = threading.Lock()

        # Mining state shared with workers.
        self.state_lock = threading.Lock()
        self.extranonce1: bytes = b""
        self.extranonce2_size: int = 4
        self.share_difficulty: float = default_diff
        self.share_target: int = target_from_share_difficulty(default_diff)
        self.current_job: Optional[CurrentJob] = None
        # clean_epoch is bumped on every clean_jobs=true notify AND on every
        # (re)connect/handshake so workers spinning on a stale extranonce1
        # break out of their inner loops. See pool_mining_worker for the
        # in-loop epoch check.
        self.clean_epoch: int = 0

        self.connected = threading.Event()
        self.authorised = threading.Event()
        self.have_job = threading.Event()
        self.stopped = threading.Event()

        # Share submit counter (for share.seq) -- assigned when a worker
        # finds a share, BEFORE handing the Share to the submit serialiser.
        self.share_seq = 0
        self.share_seq_lock = threading.Lock()

        # Stats (for periodic console + final summary).
        self.shares_submitted = 0
        self.shares_accepted = 0
        self.shares_rejected = 0

    def alloc_share_seq(self) -> int:
        with self.share_seq_lock:
            self.share_seq += 1
            return self.share_seq

    def stop(self) -> None:
        self.stopped.set()
        self._teardown_socket()

    # ------------ outbound writes ------------

    def _next_request_id(self) -> int:
        with self._next_id_lock:
            self._next_id += 1
            return self._next_id

    def _send_obj(self, obj: dict) -> None:
        if self.sock is None:
            raise StratumDisconnected("not connected")
        line = (json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8")
        with self.sock_lock:
            try:
                self.sock.sendall(line)
            except OSError as e:
                raise StratumDisconnected(f"send failed: {e}") from e

    def _call(self, method: str, params: list, timeout: float = 30.0):
        """Send a JSON-RPC request; block until response or disconnect."""
        req_id = self._next_request_id()
        ev = threading.Event()
        slot: list = [None, None, time.time()]  # [result, error, t0]
        with self._pending_lock:
            self._pending[req_id] = (ev, slot)
        try:
            self._send_obj({"id": req_id, "method": method, "params": params})
        except StratumDisconnected:
            with self._pending_lock:
                self._pending.pop(req_id, None)
            raise
        if not ev.wait(timeout):
            with self._pending_lock:
                self._pending.pop(req_id, None)
            raise StratumDisconnected(f"timeout waiting for {method} response")
        result, error, _ = slot
        if error is not None and result is None:
            raise StratumDisconnected(f"{method} error: {error!r}")
        return result

    def submit_share(self, share: Share) -> Tuple[bool, Any, float, dict, Optional[dict]]:
        """Send mining.submit. Returns (accepted, error, rtt_ms, request, response).

        request is the dict actually written to the wire; response (if any) is
        {"id":..., "result":..., "error":...}. accepted is exactly result == True.
        """
        ntime_hex = f"{share.ntime:08x}"
        nonce_hex = f"{share.nonce:08x}"
        params = [self.user, share.job_id, share.extranonce2_hex,
                  ntime_hex, nonce_hex]
        req_id = self._next_request_id()
        req = {"id": req_id, "method": "mining.submit", "params": params}
        ev = threading.Event()
        slot: list = [None, None, time.time()]
        with self._pending_lock:
            self._pending[req_id] = (ev, slot)
        t0 = time.time()
        try:
            self._send_obj(req)
        except StratumDisconnected as e:
            with self._pending_lock:
                self._pending.pop(req_id, None)
            return (False, ("send-failed", str(e)), 0.0, req, None)
        ok = ev.wait(60.0)
        rtt_ms = (time.time() - t0) * 1000.0
        if not ok:
            with self._pending_lock:
                self._pending.pop(req_id, None)
            return (False, ("timeout", "no response within 60s"), rtt_ms, req, None)
        result, error, _ = slot
        accepted = result is True
        resp = {"id": req_id, "result": result, "error": error}
        return (accepted, error, rtt_ms, req, resp)

    # ------------ connection lifecycle ------------

    def _teardown_socket(self) -> None:
        self.connected.clear()
        try:
            if self.sock is not None:
                try:
                    self.sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                self.sock.close()
        except OSError:
            pass
        self.sock = None
        # Cancel any pending requests so callers wake up promptly.
        with self._pending_lock:
            for ev, slot in list(self._pending.values()):
                slot[1] = ("disconnected", "socket closed")
                ev.set()
            self._pending.clear()

    def _connect_and_handshake(self) -> None:
        """Open TCP, optionally TLS-wrap, send subscribe + authorize, spawn reader."""
        self.connected.clear()
        self.authorised.clear()
        self.have_job.clear()
        # Invalidate any stale job/extranonce1 so worker threads break out of
        # their inner nonce loop and re-snapshot once we have a fresh notify.
        with self.state_lock:
            self.current_job = None
            self.extranonce1 = b""
            self.clean_epoch += 1

        s = socket.create_connection((self.host, self.port), timeout=30)
        s.settimeout(None)
        if self.use_tls:
            ctx = ssl.create_default_context()
            s = ctx.wrap_socket(s, server_hostname=self.host)
        try:
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        self.sock = s
        self.recv_buf = b""

        # Spawn the reader thread BEFORE issuing the subscribe so we capture
        # responses (and possibly an early set_difficulty + notify burst).
        self.reader_thread = threading.Thread(
            target=self._reader_loop, daemon=True, name="stratum-reader"
        )
        self.reader_thread.start()
        self.connected.set()

        self.logger.emit("connect", host=self.host, port=self.port,
                         use_tls=self.use_tls, useragent=self.useragent)
        print(f"[{utc_iso(time.time())}] connected to {self.host}:{self.port} "
              f"({'TLS' if self.use_tls else 'TCP'})")

        # mining.subscribe -- response is
        # [ [["mining.set_difficulty",subId],["mining.notify",subId]],
        #   extranonce1Hex, extranonce2Size ]
        sub = self._call("mining.subscribe", [self.useragent], timeout=15)
        if not isinstance(sub, list) or len(sub) < 3:
            raise StratumDisconnected(f"bad subscribe response: {sub!r}")
        en1_hex = str(sub[1])
        en2_size = int(sub[2])
        with self.state_lock:
            self.extranonce1 = bytes.fromhex(en1_hex)
            self.extranonce2_size = en2_size
        self.logger.emit("subscribed",
                         extranonce1=en1_hex,
                         extranonce2_size=en2_size,
                         subscriptions=sub[0])
        print(f"[{utc_iso(time.time())}] subscribed: extranonce1={en1_hex} "
              f"extranonce2_size={en2_size}")

        # mining.authorize
        auth = self._call("mining.authorize",
                          [self.user, self.password or "x"],
                          timeout=15)
        ok = bool(auth)
        self.logger.emit("authorized", user=self.user, ok=ok)
        if not ok:
            raise StratumDisconnected("authorize returned false")
        self.authorised.set()
        print(f"[{utc_iso(time.time())}] authorized as {self.user}")

    def run_forever(self, reconnect_delay: float = 5.0) -> None:
        """Connect, handshake, then keep the connection alive.

        Reconnects on any drop with exponential backoff capped at 60s, and
        bumps clean_epoch on each (re)handshake so worker threads abandon
        their stale extranonce1 immediately.
        """
        attempt = 0
        while not self.stopped.is_set():
            attempt += 1
            try:
                self._connect_and_handshake()
                attempt = 0
                # Wait until the reader thread exits (= disconnect) or we stop.
                while (not self.stopped.is_set()
                       and self.reader_thread is not None
                       and self.reader_thread.is_alive()):
                    self.reader_thread.join(timeout=1.0)
                if self.stopped.is_set():
                    return
                self._teardown_socket()
                self.logger.emit("disconnect", reason="reader exit",
                                 attempt=attempt)
                print(f"[{utc_iso(time.time())}] disconnected; "
                      f"reconnect attempt #{attempt + 1}")
            except (OSError, StratumDisconnected) as e:
                self._teardown_socket()
                self.logger.emit("disconnect", reason=str(e), attempt=attempt)
                print(f"[{utc_iso(time.time())}] connect error: {e}")
            if self.stopped.is_set():
                return
            backoff = min(reconnect_delay * (2 ** min(max(attempt - 1, 0), 4)), 60.0)
            backoff += random.uniform(0, 0.5)
            time.sleep(backoff)

    # ------------ inbound reader ------------

    def _reader_loop(self) -> None:
        """Accumulate bytes until newline, parse JSON, dispatch."""
        try:
            while not self.stopped.is_set():
                while b"\n" not in self.recv_buf:
                    sock = self.sock
                    if sock is None:
                        raise StratumDisconnected("socket gone")
                    try:
                        chunk = sock.recv(8192)
                    except OSError as e:
                        raise StratumDisconnected(f"recv: {e}") from e
                    if not chunk:
                        raise StratumDisconnected("EOF")
                    self.recv_buf += chunk
                    if len(self.recv_buf) > 1024 * 1024:
                        raise StratumDisconnected("oversized line")
                idx = self.recv_buf.index(b"\n")
                line = self.recv_buf[:idx]
                self.recv_buf = self.recv_buf[idx + 1:]
                if not line.strip():
                    continue
                try:
                    msg = json.loads(line.decode("utf-8", errors="replace"))
                except ValueError:
                    self.logger.emit("parse-error", line=line[:200].decode("utf-8", "replace"))
                    continue
                if self.verbose:
                    print(f"  <<< {line.decode('utf-8', 'replace')}")
                try:
                    self._dispatch(msg)
                except Exception as e:  # never let one bad message kill the reader
                    self.logger.emit("dispatch-error", err=str(e), msg=msg)
        except StratumDisconnected:
            pass
        except Exception as e:  # pragma: no cover -- defensive
            self.logger.emit("reader-error", err=str(e))
        finally:
            # Wake any callers waiting for a response.
            with self._pending_lock:
                for ev, slot in list(self._pending.values()):
                    slot[1] = ("disconnected", "reader exit")
                    ev.set()
                self._pending.clear()

    def _dispatch(self, msg: dict) -> None:
        method = msg.get("method")
        if method:
            self._on_notify(method, msg.get("params") or [])
            return
        msg_id = msg.get("id")
        if msg_id is None:
            return
        with self._pending_lock:
            entry = self._pending.pop(msg_id, None)
        if entry is None:
            return
        ev, slot = entry
        slot[0] = msg.get("result")
        slot[1] = msg.get("error")
        ev.set()

    def _on_notify(self, method: str, params: list) -> None:
        if method == "mining.set_difficulty":
            self._on_set_difficulty(params)
        elif method == "mining.notify":
            self._on_mining_notify(params)
        elif method == "mining.set_extranonce":
            self._on_set_extranonce(params)
        elif method in ("client.show_message",):
            print(f"[{utc_iso(time.time())}] pool message: {params}")
            self.logger.emit("server-message", method=method, params=params)
        elif method in ("client.reconnect",):
            self.logger.emit("server-message", method=method, params=params)
        else:
            self.logger.emit("unknown-notify", method=method, params=params)

    def _on_set_difficulty(self, params: list) -> None:
        try:
            new_diff = float(params[0])
        except (TypeError, ValueError, IndexError):
            return
        if new_diff <= 0:
            return
        with self.state_lock:
            self.share_difficulty = new_diff
            self.share_target = target_from_share_difficulty(new_diff)
            tgt_be_hex = self.share_target.to_bytes(32, "big").hex()
        self.logger.emit("set_difficulty",
                         share_difficulty=new_diff,
                         share_target_be=tgt_be_hex)
        print(f"[{utc_iso(time.time())}] set_difficulty: "
              f"share_diff={new_diff:g} share_target=0x{tgt_be_hex[:16]}...")

    def _on_set_extranonce(self, params: list) -> None:
        try:
            en1_hex = str(params[0])
            en2_size = int(params[1])
        except (TypeError, ValueError, IndexError):
            return
        with self.state_lock:
            self.extranonce1 = bytes.fromhex(en1_hex)
            self.extranonce2_size = en2_size
            self.clean_epoch += 1
        self.logger.emit("set_extranonce",
                         extranonce1=en1_hex,
                         extranonce2_size=en2_size)
        print(f"[{utc_iso(time.time())}] set_extranonce: "
              f"en1={en1_hex} en2_size={en2_size}")

    def _on_mining_notify(self, params: list) -> None:
        # mining.notify params (per contrib/testnet/pool/src/stratum/client.ts:112):
        # [jobId, prev_be_hex, coinb1, coinb2, branches, "0x"+ver_hex,
        #  "0x"+bits_hex, "0x"+ntime_hex, clean_jobs]
        try:
            (job_id, prev_be_hex, coinb1_hex, coinb2_hex, branches_hex,
             ver_hex, bits_hex, ntime_hex, clean_jobs) = params[:9]
        except (TypeError, ValueError):
            self.logger.emit("notify-bad", params=params)
            return
        try:
            version = (int(str(ver_hex), 16)
                       if isinstance(ver_hex, str) else int(ver_hex))
            bits = (int(str(bits_hex), 16)
                    if isinstance(bits_hex, str) else int(bits_hex))
            ntime = (int(str(ntime_hex), 16)
                     if isinstance(ntime_hex, str) else int(ntime_hex))
            coinb1 = bytes.fromhex(str(coinb1_hex))
            coinb2 = bytes.fromhex(str(coinb2_hex))
            branches_be = [bytes.fromhex(str(b)) for b in (branches_hex or [])]
        except (TypeError, ValueError) as e:
            self.logger.emit("notify-decode-error", err=str(e), params=params)
            return
        net_target = target_from_nbits(bits)
        net_diff = network_difficulty_from_bits(bits)
        job = CurrentJob(
            job_id=str(job_id),
            prev_hash_be_hex=str(prev_be_hex),
            coinb1=coinb1,
            coinb2=coinb2,
            merkle_branches_be=branches_be,
            version=version,
            bits=bits,
            ntime=ntime,
            clean_jobs=bool(clean_jobs),
            received_at=time.time(),
            network_target=net_target,
            network_difficulty=net_diff,
        )
        with self.state_lock:
            self.current_job = job
            if bool(clean_jobs):
                self.clean_epoch += 1
        self.have_job.set()
        self.logger.emit(
            "notify",
            job_id=job.job_id,
            prev_hash_be=job.prev_hash_be_hex,
            coinb1=coinb1.hex(),
            coinb2=coinb2.hex(),
            merkle_branches=[b.hex() for b in branches_be],
            version=version,
            bits=bits,
            ntime=ntime,
            clean_jobs=bool(clean_jobs),
            network_target_be=net_target.to_bytes(32, "big").hex(),
            network_difficulty=net_diff,
        )
        print(f"[{utc_iso(time.time())}] notify: job={job.job_id} "
              f"clean={bool(clean_jobs)} "
              f"prev={str(prev_be_hex)[:16]}... ver=0x{version:08x} "
              f"bits=0x{bits:08x} ntime={ntime} "
              f"net_diff={net_diff:.6f}  coinb1={len(coinb1)}B "
              f"coinb2={len(coinb2)}B branches={len(branches_be)}")


# ---------------------------------------------------------------------------
# Pool mode: per-thread mining worker
# ---------------------------------------------------------------------------


def pool_mining_worker(thread_idx: int,
                       num_threads: int,
                       client: StratumPoolClient,
                       state: 'MinerState',
                       logger: JsonlLogger,
                       submit_queue: "queue.Queue[Share]",
                       progress_interval: int,
                       quiet_progress: bool) -> None:
    """Per-thread BLAKE3d nonce search.

    Outer loop: re-snapshot job + extranonce1 + share_target + clean_epoch
    each pass. Inner loop: iterate nonce 0..2^32 within the snapshot,
    breaking out IMMEDIATELY (every nonce) if clean_epoch changes, so a
    stale extranonce1 / job is never mined past one hash.

    Disjoint extranonce2 slicing across N threads: thread i starts at
    en2 = i and bumps by N when the nonce range is exhausted, so each
    thread searches a non-overlapping subset.
    """
    en2_counter = thread_idx

    # Cross-job cumulative counters survive clean_epoch resets so that
    # progress.hashrate is a stable instantaneous Δattempts/Δt over the
    # inter-emit window, not "average attempts over the current outer
    # pass". With clean_jobs=true on every notify (B3Chain pool quirk)
    # outer passes are <2s, so a per-pass average reading is dominated
    # by the very-short window right after each reset and oscillates
    # wildly. Hoisting these counters fixes that. (Lesson 2026-05-16.)
    cum_attempts = 0
    cum_at_last_emit = 0
    last_progress_at = time.time()

    while not state.stopping.is_set():
        # ---- Outer snapshot: wait for an authorised + non-empty job ----
        if not client.have_job.wait(timeout=1.0):
            continue
        with client.state_lock:
            job = client.current_job
            en1 = client.extranonce1
            en2_size = client.extranonce2_size
            local_epoch = client.clean_epoch
            share_target = client.share_target
            share_diff = client.share_difficulty
        if job is None or not en1:
            # Stale wake-up; loop back and wait for a real job.
            client.have_job.clear()
            continue

        # Cache derived constants for this snapshot.
        try:
            prev_le = bytes.fromhex(job.prev_hash_be_hex)[::-1]
        except ValueError:
            time.sleep(0.5)
            continue
        net_target = job.network_target

        # Per-job best-hash tracking (resets every outer pass).
        best_pow_int = (1 << 256) - 1
        attempts_for_job = 0
        local_start = time.time()

        # ---- Iterate extranonce2 slices within this snapshot ----
        while not state.stopping.is_set():
            if local_epoch != client.clean_epoch:
                break
            # Build coinbase + merkle once per (job, en2); only nonce changes
            # in the inner loop.
            try:
                en2 = en2_counter.to_bytes(en2_size, "little")
            except OverflowError:
                # Out of en2 bits -> wait for a fresh job.
                break
            coinbase = build_coinbase_full(job.coinb1, en1, en2, job.coinb2)
            cb_txid_le = double_sha256(coinbase)
            merkle_root_le = compute_merkle_root_from_branches(
                cb_txid_le, job.merkle_branches_be
            )

            # ---- Inner nonce loop ----
            nonce = 0
            broke_for_epoch = False
            while nonce < 0x1_0000_0000:
                # Epoch breakout EVERY nonce. The cost is one int read +
                # compare (~50 ns) which is negligible vs the BLAKE3
                # double-hash (~1 us). Checking only every 1024 nonces
                # caused GIL-starved threads (e.g. 30 workers on 16 cores)
                # to be stranded on stale jobs for many seconds, because
                # at 1 attempt/sec the next 1024-aligned check is ~17 min
                # away. (V11.2.321 lesson: "workers restart on clean_jobs"
                # must point to a real loop break, not a comment.)
                if local_epoch != client.clean_epoch or state.stopping.is_set():
                    broke_for_epoch = True
                    break
                header = serialize_header(job.version, prev_le, merkle_root_le,
                                          job.ntime, job.bits, nonce)
                pow_le = double_blake3(header)
                pow_int = int.from_bytes(pow_le, byteorder="little")
                attempts_for_job += 1

                if pow_int < best_pow_int:
                    best_pow_int = pow_int

                if pow_int <= share_target:
                    block_hash_le = double_sha256(header)
                    seq = client.alloc_share_seq()
                    is_block = pow_int <= net_target
                    share = Share(
                        seq=seq,
                        job_id=job.job_id,
                        extranonce1_hex=en1.hex(),
                        extranonce2_hex=en2.hex(),
                        ntime=job.ntime,
                        nonce=nonce,
                        coinbase=coinbase,
                        coinbase_txid_le=cb_txid_le,
                        merkle_root_le=merkle_root_le,
                        header=header,
                        pow_le=pow_le,
                        pow_int=pow_int,
                        block_hash_le=block_hash_le,
                        share_target=share_target,
                        share_difficulty=share_diff,
                        network_target=net_target,
                        network_difficulty=job.network_difficulty,
                        is_block=is_block,
                        found_at=time.time(),
                        attempts_for_job=attempts_for_job,
                        thread_idx=thread_idx,
                    )
                    submit_queue.put(share)
                    # Continue scanning the rest of the nonce space; only a
                    # clean_epoch change breaks us out.

                # Cumulative counter spans outer-pass resets and is the
                # basis for the rate-emission decision below.
                cum_attempts += 1

                # Emit progress on a wall-clock cadence (>=1s per emit) OR
                # whenever progress_interval attempts have been done AND
                # at least 0.2s has elapsed (a minimum window so the
                # measured rate is not noisy). Rate is the instantaneous
                # Δattempts / Δt over the window since the last emit, NOT
                # the per-outer-pass average -- the cumulative counters
                # span clean_epoch resets so the rate stays smooth even
                # when the pool clean-flags every notify.
                now_t = time.time()
                delta_t = now_t - last_progress_at
                delta_attempts = cum_attempts - cum_at_last_emit
                attempt_tick = (
                    delta_attempts >= progress_interval and delta_t >= 0.2
                )
                time_tick = delta_t >= 1.0
                if attempt_tick or time_tick:
                    rate = delta_attempts / delta_t if delta_t > 0 else 0.0
                    state.add_attempts(delta_attempts)
                    cum_at_last_emit = cum_attempts
                    last_progress_at = now_t
                    dist_to_share = (float(best_pow_int) / float(share_target)
                                     if share_target > 0 else float("inf"))
                    dist_to_block = (float(best_pow_int) / float(net_target)
                                     if net_target > 0 else float("inf"))
                    best_be_hex = best_pow_int.to_bytes(32, "big").hex()
                    if not quiet_progress:
                        print(f"[{utc_iso(time.time())}] progress "
                              f"thread={thread_idx} job={job.job_id} "
                              f"en2={en2.hex()} "
                              f"attempts={fmt_int(attempts_for_job)} "
                              f"rate={fmt_hashrate(rate)} "
                              f"best_pow_be={best_be_hex[:16]}... "
                              f"dist_to_share={dist_to_share:.3f}x "
                              f"dist_to_block={dist_to_block:.3g}x")
                    logger.emit("progress",
                                thread=thread_idx,
                                job_id=job.job_id,
                                extranonce2=en2.hex(),
                                attempts=attempts_for_job,
                                hashrate=rate,
                                best_pow_be=best_be_hex,
                                dist_to_share=dist_to_share,
                                dist_to_block=dist_to_block)
                nonce += 1

            if broke_for_epoch or state.stopping.is_set():
                break
            # Nonce range exhausted within this en2; bump and continue.
            en2_counter += num_threads

    # Worker is stopping: flush any attempts done since the last progress
    # emit so the final summary totals match reality (otherwise up to ~1s
    # of work per thread silently disappears from total_attempts).
    leftover = cum_attempts - cum_at_last_emit
    if leftover > 0:
        state.add_attempts(leftover)


# ---------------------------------------------------------------------------
# Pool mode: share submit serialiser + console dump
# ---------------------------------------------------------------------------


def _share_to_jsonl(s: Share) -> dict:
    return {
        "share_seq": s.seq,
        "thread": s.thread_idx,
        "job_id": s.job_id,
        "extranonce1": s.extranonce1_hex,
        "extranonce2": s.extranonce2_hex,
        "ntime": s.ntime,
        "ntime_hex": f"{s.ntime:08x}",
        "nonce": s.nonce,
        "nonce_hex": f"{s.nonce:08x}",
        "coinbase": s.coinbase.hex(),
        "coinbase_txid_be": s.coinbase_txid_le[::-1].hex(),
        "merkle_root_be": s.merkle_root_le[::-1].hex(),
        "header_hex": s.header.hex(),
        "pow_hash_le": s.pow_le.hex(),
        "pow_hash_be": s.pow_le[::-1].hex(),
        "pow_int_dec": str(s.pow_int),
        "block_hash_be": s.block_hash_le[::-1].hex(),
        "share_target_be": s.share_target.to_bytes(32, "big").hex(),
        "share_difficulty": s.share_difficulty,
        "network_target_be": s.network_target.to_bytes(32, "big").hex(),
        "network_difficulty": s.network_difficulty,
        "is_block": s.is_block,
        "attempts_for_job": s.attempts_for_job,
        "found_at": s.found_at,
    }


def _print_share_dump_pre(s: Share) -> None:
    """Print the comprehensive per-share dump BEFORE sending mining.submit.

    Doing this before the submit means even if the network drops on the way
    out, the share is fully recorded for forensics. The post() call appends
    the server response + RTT once it arrives.
    """
    pow_be = s.pow_le[::-1].hex()
    block_be = s.block_hash_le[::-1].hex()
    cb_txid_be = s.coinbase_txid_le[::-1].hex()
    merkle_be = s.merkle_root_le[::-1].hex()
    share_tgt_be = s.share_target.to_bytes(32, "big").hex()
    net_tgt_be = s.network_target.to_bytes(32, "big").hex()
    ratio_share = (float(s.pow_int) / float(s.share_target)
                   if s.share_target > 0 else float("inf"))
    ratio_block = (float(s.pow_int) / float(s.network_target)
                   if s.network_target > 0 else float("inf"))
    elapsed_for_job = max(time.time() - s.found_at, 1e-9)
    rate = s.attempts_for_job / elapsed_for_job
    ts = utc_iso(s.found_at)
    ntime_iso = _dt.datetime.fromtimestamp(s.ntime, tz=_dt.timezone.utc).isoformat()
    header_hex = s.header.hex()
    ver = header_hex[0:8]
    prev = header_hex[8:72]
    merkle = header_hex[72:136]
    nt = header_hex[136:144]
    nb = header_hex[144:152]
    nn = header_hex[152:160]

    print()
    print(f"[{ts}] === SHARE #{s.seq} (thread={s.thread_idx}, job={s.job_id}) ===")
    if s.is_block:
        print("  *** BLOCK CANDIDATE -- pow_int <= network_target ***")
    print(f"  trigger             : pow <= shareTarget  (BLAKE3(BLAKE3(header)) check)")
    print(f"  job_id              : {s.job_id}")
    print(f"  extranonce1         : {s.extranonce1_hex}                 "
          f"(server-assigned)")
    print(f"  extranonce2         : {s.extranonce2_hex}                 "
          f"({len(s.extranonce2_hex) // 2} bytes, miner-chosen, "
          f"thread {s.thread_idx} slice)")
    print(f"  ntime               : 0x{s.ntime:08x}  ({s.ntime}, {ntime_iso})")
    print(f"  nonce               : 0x{s.nonce:08x}  ({s.nonce})")
    print(f"  attempts_this_job   : {fmt_int(s.attempts_for_job)}  (this thread)")
    print(f"  hashrate_this_share : {fmt_hashrate(rate)}")
    print(f"  coinbase ({len(s.coinbase)} B)    : {_wrap_hex(s.coinbase.hex())}")
    print(f"  coinbase_txid (BE)  : {cb_txid_be}")
    print(f"  merkle_root  (BE)   : {merkle_be}")
    print(f"  header (80 B)       : {ver} {prev} {merkle} {nt} {nb} {nn}")
    print(f"                        \\--ver--/\\------------- prev (LE) -------------/"
          f"\\------------ merkle (LE) ------------/\\-ntime-/\\-bits-/\\-nonce-/")
    print(f"  PoW hash (LE)       : {s.pow_le.hex()}")
    print(f"  PoW hash (BE)       : {pow_be}")
    print(f"  block_hash (BE)     : {block_be}")
    print(f"                        (SHA256d, identity hash for explorer)")
    print(f"  share_target  (BE)  : {share_tgt_be}")
    print(f"  share_difficulty    : {s.share_difficulty:.6f}")
    print(f"  network_target(BE)  : {net_tgt_be}")
    print(f"  network_difficulty  : {s.network_difficulty:.6f}")
    print(f"  pow_int / share_tgt : {ratio_share:.6f}  (lower = better, must be <= 1)")
    print(f"  pow_int / net_tgt   : {ratio_block:.6g}")
    print(f"  is_block            : {str(s.is_block).lower()}")
    print(f"  ----- mining.submit -----")
    sys.stdout.flush()


def _print_share_dump_post(s: Share, accepted: bool, error: Any,
                           rtt_ms: float, req: dict, resp: Optional[dict]) -> None:
    """Print the post-submit response section + a compact one-line summary."""
    print(f"  -> {json.dumps(req, separators=(',', ':'))}")
    if resp is not None:
        print(f"  <- {json.dumps(resp, separators=(',', ':'))}     "
              f"rtt={rtt_ms:.1f} ms")
    else:
        print(f"  <- (no response)     rtt={rtt_ms:.1f} ms  error={error!r}")
    if accepted:
        if s.is_block:
            print(f"  status              : ACCEPTED  *** BLOCK ACCEPTED ***  "
                  f"(server validated against share + network targets)")
        else:
            print(f"  status              : ACCEPTED  "
                  f"(server validated against share target)")
    else:
        print(f"  status              : REJECTED  error={error!r}")
    print(f"  ====================================================================")

    pow_be = s.pow_le[::-1].hex()
    elapsed_for_job = max(time.time() - s.found_at + 1e-9, 1e-9)
    rate = s.attempts_for_job / elapsed_for_job
    short_ts = utc_iso(time.time()).split("T", 1)[1]
    print(f"[{short_ts}] share=#{s.seq} job={s.job_id} nonce=0x{s.nonce:08x} "
          f"pow_be={pow_be[:16]}... diff={s.share_difficulty:g} "
          f"net_diff={s.network_difficulty:.6f} "
          f"{'ACCEPTED' if accepted else 'REJECTED'}  "
          f"rtt={rtt_ms:.1f}ms  rate={fmt_hashrate(rate)}")
    sys.stdout.flush()


def submit_serialiser(client: StratumPoolClient,
                      state: 'MinerState',
                      logger: JsonlLogger,
                      submit_queue: "queue.Queue[Share]",
                      max_attempts: int) -> None:
    """Single-threaded share submitter.

    All worker threads enqueue Share objects here; this one consumer thread
    serialises the actual mining.submit writes so socket bytes from
    different shares can't interleave with each other or with the
    reader-thread reconnect logic.

    For each Share:
      1. Print + JSONL the full pre-submit dump.
      2. Send mining.submit and wait for the response.
      3. Print + JSONL the response (accepted/rejected + RTT).
      4. Update stats.
      5. If --max-attempts reached, signal stop.
    """
    while not state.stopping.is_set():
        try:
            share = submit_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        if share is None:
            return

        _print_share_dump_pre(share)
        logger.emit("share_pre_submit", **_share_to_jsonl(share))

        accepted, error, rtt_ms, req, resp = client.submit_share(share)

        _print_share_dump_post(share, accepted, error, rtt_ms, req, resp)

        with state.lock:
            state.shares_submitted += 1
            if accepted:
                state.shares_accepted += 1
            else:
                state.shares_rejected += 1
            elapsed = max(time.time() - share.found_at + 1e-9, 1e-9)
            state.last_share_hashrate = share.attempts_for_job / elapsed
            if share.is_block and accepted:
                state.blocks_found += 1
        client.shares_submitted = state.shares_submitted
        client.shares_accepted = state.shares_accepted
        client.shares_rejected = state.shares_rejected

        logger.emit(
            "share_submit",
            **_share_to_jsonl(share),
            server_request=req,
            server_response=resp,
            server_rtt_ms=rtt_ms,
            accepted=accepted,
            error=error,
        )
        if share.is_block and accepted:
            logger.emit(
                "block_found",
                job_id=share.job_id,
                block_hash_be=share.block_hash_le[::-1].hex(),
                header_hex=share.header.hex(),
            )

        if max_attempts and state.shares_submitted >= max_attempts:
            print(f"[{utc_iso(time.time())}] reached --max-attempts "
                  f"({max_attempts}); stopping")
            state.stopping.set()
            return


# ---------------------------------------------------------------------------
# Mining loop
# ---------------------------------------------------------------------------

class MinerState:
    """Shared state for the mining loops (solo + pool)."""
    def __init__(self):
        self.running = True
        self.stopping = threading.Event()
        self.total_hashes = 0           # solo-mode legacy counter
        self.total_attempts = 0         # pool mode cumulative
        self.shares_submitted = 0
        self.shares_accepted = 0
        self.shares_rejected = 0
        self.blocks_found = 0
        self.last_share_hashrate = 0.0
        self.lock = threading.Lock()

    def add_attempts(self, n: int) -> None:
        with self.lock:
            self.total_attempts += n


def mine_block(rpc: RPCClient, coinbase_addr: str, coinbase_msg: str,
               state: MinerState, verbose: bool) -> bool:
    """
    Get a block template, mine it, and submit if valid.
    Returns True if a block was found and submitted.
    """
    # Get block template
    template = rpc.call("getblocktemplate", [{"rules": ["segwit"]}])

    version = template["version"]
    prev_hash = uint256_from_hex_le(template["previousblockhash"])
    bits_hex = template["bits"]
    bits = int(bits_hex, 16)
    target = target_from_nbits(bits)
    cur_time = template["curtime"]
    height = template["height"]

    # Get coinbase transaction
    if "coinbasetxn" in template:
        coinbase_hex = template["coinbasetxn"]["data"]
    else:
        # Need to generate address to create coinbase
        coinbase_hex = rpc.call("createrawtransaction", [[], {}])
        raise RPCError("No coinbasetxn in template. Start node with wallet or "
                       "use -server with generatetoaddress for regtest mining.")

    # Transaction list: coinbase + mempool transactions
    txns_hex = [coinbase_hex]
    tx_hashes = []
    for tx in template.get("transactions", []):
        txns_hex.append(tx["data"])
        tx_hashes.append(bytes.fromhex(tx["hash"])[::-1])  # txid is LE

    # Compute merkle root
    coinbase_bytes = bytes.fromhex(coinbase_hex)
    coinbase_txid = double_sha256(coinbase_bytes)
    merkle_root = build_merkle_root(coinbase_txid, tx_hashes)

    if verbose:
        print(f"  Template: height={height} txns={len(txns_hex)} "
              f"bits=0x{bits:08x} target={target:064x}")

    # Mine
    nonce = 0
    start_time = time.time()
    report_interval = 500_000

    while state.running and nonce < 0xFFFFFFFF:
        header = serialize_header(version, prev_hash, merkle_root,
                                  cur_time, bits, nonce)
        pow_hash = double_blake3(header)
        pow_int = int.from_bytes(pow_hash, byteorder='little')

        if pow_int <= target:
            # Found a valid block!
            block_hex = get_block_hex(header, txns_hex)
            identity_hash = double_sha256(header)[::-1].hex()

            elapsed = time.time() - start_time
            hashrate = (nonce + 1) / elapsed if elapsed > 0 else 0

            print(f"\n  Block found! height={height} nonce={nonce} "
                  f"hash={identity_hash[:16]}... "
                  f"({hashrate:,.0f} H/s, {elapsed:.1f}s)")

            # Submit
            result = rpc.call("submitblock", [block_hex])
            if result is None:
                print(f"  Block accepted! height={height}")
                with state.lock:
                    state.blocks_found += 1
                return True
            else:
                print(f"  Block rejected: {result}")
                return False

        nonce += 1

        if nonce % report_interval == 0:
            elapsed = time.time() - start_time
            hashrate = nonce / elapsed if elapsed > 0 else 0
            with state.lock:
                state.total_hashes += report_interval
            if verbose:
                print(f"    {nonce:,} hashes ({hashrate:,.0f} H/s)", end='\r')

    # Nonce space exhausted or stopped
    with state.lock:
        state.total_hashes += nonce % report_interval
    return False


def mining_loop(rpc: RPCClient, coinbase_addr: str, coinbase_msg: str,
                state: MinerState, verbose: bool):
    """Continuous mining loop."""
    while state.running:
        try:
            mine_block(rpc, coinbase_addr, coinbase_msg, state, verbose)
        except RPCError as e:
            print(f"  RPC error: {e}")
            time.sleep(5)
        except ConnectionRefusedError:
            print("  Cannot connect to b3chaind. Retrying in 5s...")
            time.sleep(5)
        except Exception as e:
            print(f"  Error: {e}")
            time.sleep(1)


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------

def benchmark():
    """Run a 10-second BLAKE3 double-hash benchmark."""
    print("Running BLAKE3 double-hash benchmark (10 seconds)...")

    # Create a dummy 80-byte header
    header = bytes(80)
    count = 0
    nonce = 0
    start = time.time()
    duration = 10.0

    while time.time() - start < duration:
        # Simulate mining: modify nonce bytes and hash
        nonce_bytes = struct.pack('<I', nonce)
        test_header = header[:76] + nonce_bytes
        double_blake3(test_header)
        nonce += 1
        count += 1

    elapsed = time.time() - start
    hashrate = count / elapsed

    print(f"  Hashes: {count:,}")
    print(f"  Time:   {elapsed:.2f}s")
    print(f"  Rate:   {hashrate:,.0f} H/s")
    print(f"          {hashrate/1000:,.1f} kH/s")
    return hashrate


# ---------------------------------------------------------------------------
# Pool mode orchestrator
# ---------------------------------------------------------------------------


def pool_mining_loop(args, state: 'MinerState') -> None:
    """Run the miner in Stratum V1 pool mode.

    Threading model:
      * Main thread (this function) wires everything up and waits for
        either --max-attempts to be reached or Ctrl+C.
      * StratumPoolClient.run_forever() owns the connection lifecycle and
        keeps reconnecting on drops; it spawns its own daemon reader
        thread inside _connect_and_handshake().
      * N pool_mining_worker threads do the BLAKE3d nonce search; they
        share a queue.Queue with the submit_serialiser thread.
      * One submit_serialiser thread serialises mining.submit writes and
        the per-share dump, so console output and socket writes never
        interleave.
    """
    try:
        host, port, use_tls = parse_stratum_url(args.stratum)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    if not args.user:
        print("ERROR: --user is required in pool mode "
              "(typically <email>.<workerName>).", file=sys.stderr)
        sys.exit(1)

    logger = JsonlLogger(args.json_log if args.json_log else None)
    if args.json_log:
        print(f"JSONL log -> {args.json_log}")

    client = StratumPoolClient(
        host=host, port=port, use_tls=use_tls,
        user=args.user, password=args.pass_,
        useragent=args.useragent or USER_AGENT_DEFAULT,
        logger=logger,
        verbose=args.verbose,
    )

    print(f"b3chain CPU miner -- pool mode")
    print(f"  Pool:    {args.stratum}  ({'TLS' if use_tls else 'TCP'})")
    print(f"  User:    {args.user}")
    print(f"  Threads: {args.threads}")
    print(f"  PoW:     BLAKE3(BLAKE3(80-byte header))")
    print()

    submit_queue: "queue.Queue[Share]" = queue.Queue(maxsize=1024)

    threads: list = []

    # 1) Stratum client thread (owns the connection + reader).
    def _client_target():
        try:
            client.run_forever(reconnect_delay=float(args.reconnect_delay))
        finally:
            state.stopping.set()
    t_client = threading.Thread(target=_client_target, daemon=True,
                                name="stratum-client")
    t_client.start()
    threads.append(t_client)

    # 2) Submit serialiser thread.
    t_submit = threading.Thread(
        target=submit_serialiser,
        args=(client, state, logger, submit_queue, int(args.max_attempts)),
        daemon=True,
        name="submit-serialiser",
    )
    t_submit.start()
    threads.append(t_submit)

    # 3) N worker threads.
    num_threads = max(1, int(args.threads))
    workers: list = []
    for i in range(num_threads):
        w = threading.Thread(
            target=pool_mining_worker,
            args=(i, num_threads, client, state, logger, submit_queue,
                  int(args.progress_interval), bool(args.quiet_progress)),
            daemon=True,
            name=f"miner-{i}",
        )
        w.start()
        workers.append(w)
    threads.extend(workers)

    # ---- Main thread: wait for stop ----
    start_time = time.time()
    try:
        while not state.stopping.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping miner...")
        state.stopping.set()

    # Tear down: stop the client (closes socket, wakes reader),
    # then wake the submitter with a sentinel.
    client.stop()
    try:
        submit_queue.put_nowait(None)  # type: ignore[arg-type]
    except queue.Full:
        pass

    for t in workers:
        t.join(timeout=2.0)
    t_submit.join(timeout=5.0)
    t_client.join(timeout=5.0)

    elapsed = max(time.time() - start_time, 1e-9)
    avg_rate = state.total_attempts / elapsed
    summary = {
        "runtime_s": elapsed,
        "shares_submitted": state.shares_submitted,
        "shares_accepted": state.shares_accepted,
        "shares_rejected": state.shares_rejected,
        "blocks_found": state.blocks_found,
        "total_attempts": state.total_attempts,
        "avg_hashrate": avg_rate,
    }
    logger.emit("summary", **summary)
    print()
    print("Pool mining summary:")
    print(f"  Runtime:           {elapsed:.1f}s")
    print(f"  Shares submitted:  {state.shares_submitted}")
    print(f"  Shares accepted:   {state.shares_accepted}")
    print(f"  Shares rejected:   {state.shares_rejected}")
    print(f"  Blocks found:      {state.blocks_found}")
    print(f"  Total attempts:    {fmt_int(state.total_attempts)}")
    print(f"  Avg hashrate:      {fmt_hashrate(avg_rate)}")
    logger.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="b3chain reference CPU miner (double BLAKE3-256 PoW)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Pool mining (Stratum V1) with full per-share dump + JSONL log:
  %(prog)s --stratum stratum+tcp://pool.b3chain.org:3333 \\
           --user alice@example.com.cpu1 --pass x \\
           --threads 2 --json-log shares.jsonl

  # Solo mining on regtest with cookie auth:
  %(prog)s --regtest --coinbaseaddr b3rt1q...

  # Solo mining on mainnet with explicit credentials:
  %(prog)s --rpcuser myuser --rpcpassword mypass --coinbaseaddr b31q...

  # Benchmark hash rate:
  %(prog)s --benchmark
"""
    )
    # Solo-mode (RPC) flags.
    parser.add_argument("--rpcuser", default="", help="RPC username")
    parser.add_argument("--rpcpassword", default="", help="RPC password")
    parser.add_argument("--rpcconnect", default="127.0.0.1", help="RPC host")
    parser.add_argument("--rpcport", type=int, default=0, help="RPC port")
    parser.add_argument("--coinbaseaddr", default="",
                        help="Address for coinbase reward (solo mode)")
    parser.add_argument("--coinbasemsg", default="",
                        help="Extra text in coinbase (max 92 bytes)")
    parser.add_argument("--datadir", default="",
                        help="Data directory for cookie auth")
    parser.add_argument("--regtest", action="store_true",
                        help="Use regtest parameters")
    parser.add_argument("--testnet", action="store_true",
                        help="Use testnet parameters")

    # Pool-mode (Stratum V1) flags.
    parser.add_argument("--stratum", default="",
                        help="Pool URL (e.g. stratum+tcp://pool:3333). "
                             "Selecting --stratum chooses pool mode.")
    parser.add_argument("--user", default="",
                        help="Pool worker username (typically <email>.<worker>)")
    # 'pass' is a Python keyword; argparse renames a hyphenated flag to
    # `args.pass` which is also illegal, so we explicitly map it via dest.
    parser.add_argument("--pass", dest="pass_", default="x", metavar="PASS",
                        help="Pool password (ignored by the pool, default 'x')")
    parser.add_argument("--useragent", default=USER_AGENT_DEFAULT,
                        help=f"User-agent for mining.subscribe "
                             f"(default {USER_AGENT_DEFAULT})")
    parser.add_argument("--json-log", dest="json_log", default="",
                        help="Append-only JSONL file recording every share + event")
    parser.add_argument("--quiet-progress", dest="quiet_progress",
                        action="store_true",
                        help="Suppress per-N-hash progress lines on stdout "
                             "(still written to JSONL)")
    parser.add_argument("--progress-interval", dest="progress_interval",
                        type=int, default=1_000_000,
                        help="Internal-hash count between progress lines "
                             "(default 1,000,000)")
    parser.add_argument("--reconnect-delay", dest="reconnect_delay",
                        type=float, default=5.0,
                        help="Reconnect backoff base seconds "
                             "(default 5; cap 60)")
    parser.add_argument("--max-attempts", dest="max_attempts",
                        type=int, default=0,
                        help="Stop after N share submissions "
                             "(0 = forever; useful for tests)")

    # Common flags.
    parser.add_argument("--threads", type=int, default=1,
                        help="Number of mining threads (default: 1)")
    parser.add_argument("--benchmark", action="store_true",
                        help="Run hash rate benchmark and exit")
    parser.add_argument("--verbose", action="store_true",
                        help="Print extra debug info")

    args = parser.parse_args()

    # Mode selection. --benchmark wins; --stratum and --coinbaseaddr are
    # mutually exclusive.
    if args.benchmark:
        benchmark()
        return

    if args.stratum and args.coinbaseaddr:
        print("ERROR: --stratum (pool mode) and --coinbaseaddr (solo mode) "
              "are mutually exclusive.", file=sys.stderr)
        sys.exit(2)

    # Set up shared state + signal handler (used by both modes).
    state = MinerState()

    def signal_handler(sig, frame):
        print("\nStopping miner...")
        state.running = False
        state.stopping.set()

    signal.signal(signal.SIGINT, signal_handler)
    try:
        signal.signal(signal.SIGTERM, signal_handler)
    except (AttributeError, ValueError):
        # SIGTERM may be unavailable (e.g. some Windows configurations).
        pass

    # ----------------- Pool mode -----------------
    if args.stratum:
        pool_mining_loop(args, state)
        return

    # ----------------- Solo mode (existing code path) -----------------
    if args.datadir:
        datadir = args.datadir
    else:
        home = os.path.expanduser("~")
        if sys.platform == "darwin":
            datadir = os.path.join(home, "Library", "Application Support",
                                   "B3Chain")
        elif sys.platform == "win32":
            datadir = os.path.join(os.environ.get("APPDATA", home), "B3Chain")
        else:
            datadir = os.path.join(home, ".b3chain")

    if args.rpcport:
        port = args.rpcport
    elif args.regtest:
        port = 18545
    elif args.testnet:
        port = 18534
    else:
        port = 8534

    user = args.rpcuser
    password = args.rpcpassword
    if not user or not password:
        cookie_user, cookie_pass = read_cookie(datadir)
        if cookie_user:
            user = cookie_user
            password = cookie_pass
        else:
            print("ERROR: No RPC credentials. Provide --rpcuser/--rpcpassword "
                  "or ensure .cookie file exists in data directory.")
            print(f"  Checked: {datadir}")
            sys.exit(1)

    if not args.coinbaseaddr:
        print("ERROR: --coinbaseaddr is required for solo mode "
              "(or use --stratum for pool mode).")
        print("  Generate one with: b3chain-cli getnewaddress")
        sys.exit(1)

    rpc = RPCClient(args.rpcconnect, port, user, password)

    try:
        info = rpc.call("getblockchaininfo")
        chain = info.get("chain", "unknown")
        blocks = info.get("blocks", 0)
        print(f"b3chain CPU miner")
        print(f"  Chain:   {chain}")
        print(f"  Height:  {blocks}")
        print(f"  Address: {args.coinbaseaddr}")
        print(f"  Threads: {args.threads}")
        print()
    except Exception as e:
        print(f"ERROR: Cannot connect to b3chaind at "
              f"{args.rpcconnect}:{port}: {e}")
        sys.exit(1)

    print("Mining started. Press Ctrl+C to stop.\n")
    start_time = time.time()

    if args.threads <= 1:
        mining_loop(rpc, args.coinbaseaddr, args.coinbasemsg, state,
                    args.verbose)
    else:
        threads = []
        for i in range(args.threads):
            t = threading.Thread(
                target=mining_loop,
                args=(rpc, args.coinbaseaddr, args.coinbasemsg, state,
                      args.verbose),
                daemon=True,
            )
            t.start()
            threads.append(t)

        try:
            while state.running:
                time.sleep(1)
        except KeyboardInterrupt:
            state.running = False

        for t in threads:
            t.join(timeout=5)

    elapsed = time.time() - start_time
    print(f"\nMining summary:")
    print(f"  Runtime:      {elapsed:.1f}s")
    print(f"  Blocks found: {state.blocks_found}")
    print(f"  Total hashes: {state.total_hashes:,}")
    if elapsed > 0:
        print(f"  Avg hashrate: {state.total_hashes/elapsed:,.0f} H/s")


if __name__ == "__main__":
    main()
