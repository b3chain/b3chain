# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license.
"""
JSONL stream parser for the live mining dashboard.

The miner (b3chain-cpuminer.py) writes one JSON object per line to its
--json-log file. Every object has a {"ts", "event", ...} shape. Known
events are listed in `EVENT_*` constants below.

`JSONLTail` is a stateful tail-reader: it tracks the byte offset it has
already consumed and a partial-line buffer so that mid-write lines are
never double-read or split. Each call to `poll()` returns the parsed
events that were appended since the previous call.

Typed dataclasses (ShareEvent, ProgressEvent, NotifyEvent, etc.) are
emitted for the events the dashboard cares about; everything else comes
back as a `RawEvent` (just the raw dict + ts) so the JSONL-events tab
can still display it.
"""

from __future__ import annotations

import dataclasses
import json
import os
from typing import Any, Dict, Iterable, List, Optional, Union


# ---------------------------------------------------------------------------
# Event names (exactly what the miner emits)
# ---------------------------------------------------------------------------

EVENT_CONNECT = "connect"
EVENT_SUBSCRIBED = "subscribed"
EVENT_AUTHORIZED = "authorized"
EVENT_SET_DIFFICULTY = "set_difficulty"
EVENT_SET_EXTRANONCE = "set_extranonce"
EVENT_NOTIFY = "notify"
EVENT_PROGRESS = "progress"
EVENT_SHARE_PRE_SUBMIT = "share_pre_submit"
EVENT_SHARE_SUBMIT = "share_submit"
EVENT_BLOCK_FOUND = "block_found"
EVENT_DISCONNECT = "disconnect"
EVENT_SUMMARY = "summary"


# ---------------------------------------------------------------------------
# Typed events
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ShareEvent:
    """A `share_submit` JSONL row, normalised for the dashboard."""
    ts: float
    seq: int
    thread: int
    job_id: str
    extranonce1: str
    extranonce2: str
    ntime: int
    nonce: int
    header_hex: str
    pow_hash_le: str
    pow_hash_be: str
    block_hash_be: str
    share_target_be: str
    share_difficulty: float
    network_target_be: str
    network_difficulty: float
    is_block: bool
    rtt_ms: float
    accepted: bool
    error: Optional[Any]
    attempts_for_job: int
    coinbase_hex: str
    coinbase_txid_be: str
    merkle_root_be: str

    @property
    def status(self) -> str:
        return "ACCEPTED" if self.accepted else "REJECTED"


@dataclasses.dataclass
class ProgressEvent:
    """A `progress` JSONL row -- per-worker periodic progress line."""
    ts: float
    thread: int
    job_id: str
    extranonce2: str
    attempts: int
    hashrate: float
    best_pow_be: str
    dist_to_share: Optional[float] = None
    dist_to_block: Optional[float] = None


@dataclasses.dataclass
class NotifyEvent:
    """A `notify` JSONL row -- new job pushed by the pool."""
    ts: float
    job_id: str
    prev_hash_be: str
    network_target_be: str
    network_difficulty: float
    bits: int
    version: int
    ntime: int
    clean: bool


@dataclasses.dataclass
class SetDifficultyEvent:
    ts: float
    share_difficulty: float
    share_target_be: str


@dataclasses.dataclass
class SubscribedEvent:
    ts: float
    extranonce1: str
    extranonce2_size: int


@dataclasses.dataclass
class ConnectEvent:
    ts: float
    host: str
    port: int
    use_tls: bool
    useragent: str


@dataclasses.dataclass
class AuthorizedEvent:
    ts: float
    user: str
    ok: bool


@dataclasses.dataclass
class DisconnectEvent:
    ts: float
    reason: str
    attempt: int = 0


@dataclasses.dataclass
class BlockFoundEvent:
    ts: float
    job_id: str
    block_hash_be: str
    header_hex: str


@dataclasses.dataclass
class SummaryEvent:
    ts: float
    runtime_s: float
    shares_submitted: int
    shares_accepted: int
    shares_rejected: int
    blocks_found: int
    total_attempts: int
    avg_hashrate: float


@dataclasses.dataclass
class RawEvent:
    """Catch-all for events we don't have a typed wrapper for."""
    ts: float
    event: str
    raw: Dict[str, Any]


ParsedEvent = Union[
    ShareEvent, ProgressEvent, NotifyEvent, SetDifficultyEvent,
    SubscribedEvent, ConnectEvent, AuthorizedEvent, DisconnectEvent,
    BlockFoundEvent, SummaryEvent, RawEvent,
]


# ---------------------------------------------------------------------------
# Single-line dispatcher
# ---------------------------------------------------------------------------


def parse_jsonl_line(line: str) -> Optional[ParsedEvent]:
    """Parse one JSONL line; return a typed event or RawEvent. Returns None
    on a hopelessly malformed line so the caller can keep going."""
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None

    ts = float(obj.get("ts", 0.0))
    event = str(obj.get("event", ""))

    try:
        if event == EVENT_SHARE_SUBMIT:
            return ShareEvent(
                ts=ts,
                seq=int(obj.get("share_seq", 0)),
                thread=int(obj.get("thread", 0)),
                job_id=str(obj.get("job_id", "")),
                extranonce1=str(obj.get("extranonce1", "")),
                extranonce2=str(obj.get("extranonce2", "")),
                ntime=int(obj.get("ntime", 0)),
                nonce=int(obj.get("nonce", 0)),
                header_hex=str(obj.get("header_hex", "")),
                pow_hash_le=str(obj.get("pow_hash_le", "")),
                pow_hash_be=str(obj.get("pow_hash_be", "")),
                block_hash_be=str(obj.get("block_hash_be", "")),
                share_target_be=str(obj.get("share_target_be", "")),
                share_difficulty=float(obj.get("share_difficulty", 0.0)),
                network_target_be=str(obj.get("network_target_be", "")),
                network_difficulty=float(obj.get("network_difficulty", 0.0)),
                is_block=bool(obj.get("is_block", False)),
                rtt_ms=float(obj.get("server_rtt_ms", 0.0) or 0.0),
                accepted=bool(obj.get("accepted", False)),
                error=obj.get("error"),
                attempts_for_job=int(obj.get("attempts_for_job", 0)),
                coinbase_hex=str(obj.get("coinbase", "")),
                coinbase_txid_be=str(obj.get("coinbase_txid_be", "")),
                merkle_root_be=str(obj.get("merkle_root_be", "")),
            )
        if event == EVENT_PROGRESS:
            return ProgressEvent(
                ts=ts,
                thread=int(obj.get("thread", 0)),
                job_id=str(obj.get("job_id", "")),
                extranonce2=str(obj.get("extranonce2", "")),
                attempts=int(obj.get("attempts", 0)),
                hashrate=float(obj.get("hashrate", 0.0)),
                best_pow_be=str(obj.get("best_pow_be", "")),
                dist_to_share=_opt_float(obj.get("dist_to_share")),
                dist_to_block=_opt_float(obj.get("dist_to_block")),
            )
        if event == EVENT_NOTIFY:
            return NotifyEvent(
                ts=ts,
                job_id=str(obj.get("job_id", "")),
                prev_hash_be=str(obj.get("prev_hash_be", "")),
                network_target_be=str(obj.get("network_target_be", "")),
                network_difficulty=float(obj.get("network_difficulty", 0.0)),
                bits=int(obj.get("bits", 0)),
                version=int(obj.get("version", 0)),
                ntime=int(obj.get("ntime", 0)),
                clean=bool(obj.get("clean", False)),
            )
        if event == EVENT_SET_DIFFICULTY:
            return SetDifficultyEvent(
                ts=ts,
                share_difficulty=float(obj.get("share_difficulty", 0.0)),
                share_target_be=str(obj.get("share_target_be", "")),
            )
        if event == EVENT_SUBSCRIBED:
            return SubscribedEvent(
                ts=ts,
                extranonce1=str(obj.get("extranonce1", "")),
                extranonce2_size=int(obj.get("extranonce2_size", 0)),
            )
        if event == EVENT_CONNECT:
            return ConnectEvent(
                ts=ts,
                host=str(obj.get("host", "")),
                port=int(obj.get("port", 0)),
                use_tls=bool(obj.get("use_tls", False)),
                useragent=str(obj.get("useragent", "")),
            )
        if event == EVENT_AUTHORIZED:
            return AuthorizedEvent(
                ts=ts,
                user=str(obj.get("user", "")),
                ok=bool(obj.get("ok", False)),
            )
        if event == EVENT_DISCONNECT:
            return DisconnectEvent(
                ts=ts,
                reason=str(obj.get("reason", "")),
                attempt=int(obj.get("attempt", 0) or 0),
            )
        if event == EVENT_BLOCK_FOUND:
            return BlockFoundEvent(
                ts=ts,
                job_id=str(obj.get("job_id", "")),
                block_hash_be=str(obj.get("block_hash_be", "")),
                header_hex=str(obj.get("header_hex", "")),
            )
        if event == EVENT_SUMMARY:
            return SummaryEvent(
                ts=ts,
                runtime_s=float(obj.get("runtime_s", 0.0)),
                shares_submitted=int(obj.get("shares_submitted", 0)),
                shares_accepted=int(obj.get("shares_accepted", 0)),
                shares_rejected=int(obj.get("shares_rejected", 0)),
                blocks_found=int(obj.get("blocks_found", 0)),
                total_attempts=int(obj.get("total_attempts", 0)),
                avg_hashrate=float(obj.get("avg_hashrate", 0.0)),
            )
    except (TypeError, ValueError):
        return RawEvent(ts=ts, event=event, raw=obj)

    return RawEvent(ts=ts, event=event, raw=obj)


def _opt_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Stateful tail reader
# ---------------------------------------------------------------------------


class JSONLTail:
    """Tail-reader for the miner's --json-log file.

    Each `poll()` reads bytes appended since the last call, decodes them
    as UTF-8, splits on newlines, and returns a list of parsed events.
    A trailing partial line (no newline yet because the miner is mid-write)
    is held in `self._buffer` and re-tried on the next call.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self._offset: int = 0
        self._buffer: bytes = b""
        self._missing_count: int = 0

    @property
    def exists(self) -> bool:
        return os.path.exists(self.path)

    @property
    def offset(self) -> int:
        return self._offset

    def reset(self) -> None:
        self._offset = 0
        self._buffer = b""
        self._missing_count = 0

    def poll(self) -> List[ParsedEvent]:
        """Read newly-appended bytes and return parsed events.

        Returns an empty list (not raise) if the file does not exist yet
        (the miner just started) or has been truncated. If the file has
        shrunk we reset; this happens if the user manually deletes the
        log mid-run."""
        if not os.path.exists(self.path):
            self._missing_count += 1
            return []
        try:
            size = os.path.getsize(self.path)
        except OSError:
            return []
        if size < self._offset:
            # Truncation -- reset to the start.
            self.reset()
        if size == self._offset and not self._buffer:
            return []

        try:
            with open(self.path, "rb") as f:
                f.seek(self._offset)
                chunk = f.read(size - self._offset)
        except OSError:
            return []

        self._offset += len(chunk)

        data = self._buffer + chunk
        events: List[ParsedEvent] = []
        # Split on newlines; keep the last partial fragment in the buffer.
        if b"\n" not in data:
            self._buffer = data
            return events

        # Convert any remaining trailing chunk after the last newline to buffer.
        last_newline = data.rfind(b"\n")
        complete = data[:last_newline]
        self._buffer = data[last_newline + 1:]

        for raw_line in complete.split(b"\n"):
            if not raw_line.strip():
                continue
            try:
                line = raw_line.decode("utf-8")
            except UnicodeDecodeError:
                line = raw_line.decode("utf-8", errors="replace")
            ev = parse_jsonl_line(line)
            if ev is not None:
                events.append(ev)
        return events

    def drain_remaining(self) -> List[ParsedEvent]:
        """One last poll() but force-flush any buffered partial line through
        the parser too. Use this on miner exit so a trailing event with no
        terminating newline (rare) still lands in the dashboard."""
        events = self.poll()
        if self._buffer:
            try:
                line = self._buffer.decode("utf-8", errors="replace")
            except Exception:
                line = ""
            self._buffer = b""
            ev = parse_jsonl_line(line)
            if ev is not None:
                events.append(ev)
        return events
