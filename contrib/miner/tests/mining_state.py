# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license.
"""
Aggregate state objects for the live mining dashboard.

These classes consume parsed JSONL events from `mining_parsers.py` and
maintain rolling stats that the dashboard widgets render. None of these
touch Qt directly; the dashboard owns the Qt side and pumps events in.
"""

from __future__ import annotations

import collections
import dataclasses
import time
from typing import Deque, Dict, List, Optional, Tuple

from .mining_parsers import (
    NotifyEvent, ProgressEvent, SetDifficultyEvent, ShareEvent,
    SubscribedEvent,
)


HASHRATE_WINDOW_SECONDS = 300.0  # 5 minutes
RECENT_SHARES_CAP = 200


# ---------------------------------------------------------------------------
# Rolling hashrate ring
# ---------------------------------------------------------------------------


class HashrateRing:
    """Rolling per-thread hashrate samples over the last N seconds.

    A single global "current" hashrate is computed by summing the most
    recent sample per thread. The chart consumes the same data and plots
    the time-aligned aggregate.
    """

    def __init__(self, window_s: float = HASHRATE_WINDOW_SECONDS,
                 smooth_window_s: float = 5.0) -> None:
        self.window_s = window_s
        # The chart deque holds samples for `window_s` (5 min by default).
        # `current_rate()` averages over `_smooth_window_s` (a much
        # shorter window) so the big stat card doesn't flicker.
        self._smooth_window_s = smooth_window_s
        # Each thread gets its own deque so cross-thread samples don't fight.
        self._per_thread: Dict[int, Deque[Tuple[float, float]]] = {}
        # Aggregate samples (t, total_rate) for the chart.
        self._agg: Deque[Tuple[float, float]] = collections.deque()

    def feed(self, ts: float, thread: int, rate_hps: float) -> None:
        dq = self._per_thread.setdefault(thread, collections.deque())
        dq.append((ts, rate_hps))
        self._evict_old(dq, ts)
        self._agg.append((ts, self._aggregate_at(ts)))
        self._evict_old(self._agg, ts)

    def _evict_old(self, dq: Deque[Tuple[float, float]], now: float) -> None:
        cutoff = now - self.window_s
        while dq and dq[0][0] < cutoff:
            dq.popleft()

    def _aggregate_at(self, now: float) -> float:
        # Sum the most-recent sample per thread.
        total = 0.0
        for dq in self._per_thread.values():
            if not dq:
                continue
            t, r = dq[-1]
            if now - t <= self.window_s:
                total += r
        return total

    def current_rate(self) -> float:
        """Smoothed instantaneous total hashrate.

        Each per-thread `progress` event from the miner is already an
        instantaneous Δattempts/Δt sample over a >=1s window per worker,
        but threads emit at staggered times. Returning just the latest
        aggregate sample causes per-emit ripple in the displayed value.
        Average the last `_smooth_window_s` seconds of aggregate samples
        so the displayed hashrate is stable while still tracking real
        changes within a few seconds.
        """
        if not self._agg:
            return 0.0
        cutoff = self._agg[-1][0] - self._smooth_window_s
        recent = [r for t, r in self._agg if t >= cutoff]
        if not recent:
            return self._agg[-1][1]
        return sum(recent) / len(recent)

    def avg_rate(self) -> float:
        if not self._agg:
            return 0.0
        total = sum(r for _, r in self._agg)
        return total / len(self._agg)

    def chart_samples(self) -> List[Tuple[float, float]]:
        """Return (t, rate) samples for the chart."""
        return list(self._agg)

    def threads(self) -> List[int]:
        return sorted(self._per_thread.keys())


# ---------------------------------------------------------------------------
# Recent shares + counters
# ---------------------------------------------------------------------------


class ShareList:
    """Capped list of recent shares + accept/reject/blocks counters."""

    def __init__(self, cap: int = RECENT_SHARES_CAP) -> None:
        self.cap = cap
        self.shares: Deque[ShareEvent] = collections.deque(maxlen=cap)
        self.submitted: int = 0
        self.accepted: int = 0
        self.rejected: int = 0
        self.blocks: int = 0

    def add(self, ev: ShareEvent) -> None:
        self.shares.appendleft(ev)
        self.submitted += 1
        if ev.accepted:
            self.accepted += 1
            if ev.is_block:
                self.blocks += 1
        else:
            self.rejected += 1

    @property
    def accept_rate(self) -> float:
        if self.submitted == 0:
            return 0.0
        return self.accepted / self.submitted

    def last(self) -> Optional[ShareEvent]:
        if not self.shares:
            return None
        return self.shares[0]


# ---------------------------------------------------------------------------
# Per-thread stats
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ThreadStat:
    thread: int
    rate_hps: float = 0.0
    attempts: int = 0
    best_pow_be: str = ""
    last_seen_ts: float = 0.0
    job_id: str = ""


class PerThreadStats:
    """Latest per-thread snapshot, plus aggregate total attempts.

    Total attempts is computed as the sum of the most recent `attempts`
    value reported per thread; the miner's progress events report the
    cumulative count for the current job, which resets on `notify`.
    To keep a *running total across jobs* we accumulate increments
    rather than just taking the latest sample.
    """

    def __init__(self) -> None:
        self._stats: Dict[int, ThreadStat] = {}
        # When the job changes for a thread, its `attempts` resets, so we
        # carry forward the previous job's accumulated attempts.
        self._carry: Dict[int, int] = {}
        self._last_attempts: Dict[int, int] = {}

    def feed(self, ev: ProgressEvent) -> None:
        st = self._stats.setdefault(ev.thread, ThreadStat(thread=ev.thread))
        if (st.job_id and st.job_id != ev.job_id
                and ev.thread in self._last_attempts):
            # New job for this thread: carry the previous tally forward.
            self._carry[ev.thread] = (self._carry.get(ev.thread, 0)
                                      + self._last_attempts[ev.thread])
        st.rate_hps = ev.hashrate
        st.attempts = self._carry.get(ev.thread, 0) + ev.attempts
        st.best_pow_be = ev.best_pow_be
        st.last_seen_ts = ev.ts
        st.job_id = ev.job_id
        self._last_attempts[ev.thread] = ev.attempts

    def all(self) -> List[ThreadStat]:
        return [self._stats[k] for k in sorted(self._stats.keys())]

    def total_attempts(self) -> int:
        return sum(s.attempts for s in self._stats.values())

    def best_pow_be(self) -> str:
        """Best (smallest BE) PoW across all threads. Empty string until any."""
        best = ""
        for s in self._stats.values():
            if not s.best_pow_be:
                continue
            if not best or _hex_lt(s.best_pow_be, best):
                best = s.best_pow_be
        return best


def _hex_lt(a: str, b: str) -> bool:
    """Compare two hex strings as big-endian integers without int()."""
    try:
        return int(a, 16) < int(b, 16)
    except ValueError:
        return a < b


# ---------------------------------------------------------------------------
# Aggregate session
# ---------------------------------------------------------------------------


class MiningSession:
    """The dashboard's single source of truth for runtime stats."""

    def __init__(self) -> None:
        self.started_at: float = 0.0
        self.stopped_at: float = 0.0

        # Connection / pool state
        self.connected: bool = False
        self.host: str = ""
        self.port: int = 0
        self.use_tls: bool = False
        self.useragent: str = ""
        self.user: str = ""
        self.extranonce1: str = ""
        self.extranonce2_size: int = 0

        # Difficulty
        self.share_difficulty: float = 0.0
        self.share_target_be: str = ""
        self.network_difficulty: float = 0.0
        self.network_target_be: str = ""
        self.current_job: str = ""

        # Stats
        self.hashrate = HashrateRing()
        self.shares = ShareList()
        self.threads = PerThreadStats()

        # Disconnect detail (most recent)
        self.last_disconnect_reason: str = ""

    @property
    def runtime_s(self) -> float:
        if self.started_at == 0.0:
            return 0.0
        end = self.stopped_at if self.stopped_at else time.time()
        return max(end - self.started_at, 0.0)

    def begin(self) -> None:
        self.started_at = time.time()
        self.stopped_at = 0.0

    def end(self) -> None:
        if self.stopped_at == 0.0:
            self.stopped_at = time.time()

    # ---- event ingestion -------------------------------------------------

    def on_subscribed(self, ev: SubscribedEvent) -> None:
        self.extranonce1 = ev.extranonce1
        self.extranonce2_size = ev.extranonce2_size

    def on_set_difficulty(self, ev: SetDifficultyEvent) -> None:
        self.share_difficulty = ev.share_difficulty
        self.share_target_be = ev.share_target_be

    def on_notify(self, ev: NotifyEvent) -> None:
        self.network_difficulty = ev.network_difficulty
        self.network_target_be = ev.network_target_be
        self.current_job = ev.job_id

    def on_progress(self, ev: ProgressEvent) -> None:
        self.hashrate.feed(ev.ts, ev.thread, ev.hashrate)
        self.threads.feed(ev)

    def on_share(self, ev: ShareEvent) -> None:
        self.shares.add(ev)
        # network/share difficulty come along for the ride; don't downgrade
        # if we somehow saw a higher value via notify before the share.
        if ev.network_difficulty > 0:
            self.network_difficulty = ev.network_difficulty
            self.network_target_be = ev.network_target_be
        if ev.share_difficulty > 0:
            self.share_difficulty = ev.share_difficulty
            self.share_target_be = ev.share_target_be

    # ---- snapshot for Save Session --------------------------------------

    def snapshot(self) -> dict:
        last = self.shares.last()
        return {
            "config": {
                "host": self.host,
                "port": self.port,
                "use_tls": self.use_tls,
                "user": self.user,
                "useragent": self.useragent,
            },
            "extranonce1": self.extranonce1,
            "extranonce2_size": self.extranonce2_size,
            "runtime_s": round(self.runtime_s, 2),
            "totals": {
                "submitted": self.shares.submitted,
                "accepted": self.shares.accepted,
                "rejected": self.shares.rejected,
                "blocks": self.shares.blocks,
                "accept_rate": round(self.shares.accept_rate, 4),
                "attempts": self.threads.total_attempts(),
                "current_hashrate_hps": round(self.hashrate.current_rate(), 2),
                "avg_hashrate_hps": round(self.hashrate.avg_rate(), 2),
                "best_pow_be": self.threads.best_pow_be(),
            },
            "network": {
                "difficulty": self.network_difficulty,
                "target_be": self.network_target_be,
            },
            "share": {
                "difficulty": self.share_difficulty,
                "target_be": self.share_target_be,
            },
            "current_job": self.current_job,
            "per_thread": [
                {
                    "id": s.thread,
                    "rate_hps": round(s.rate_hps, 2),
                    "attempts": s.attempts,
                    "best_pow_be": s.best_pow_be,
                    "job_id": s.job_id,
                }
                for s in self.threads.all()
            ],
            "last_share": dataclasses.asdict(last) if last else None,
            "disconnect_reason": self.last_disconnect_reason,
        }
