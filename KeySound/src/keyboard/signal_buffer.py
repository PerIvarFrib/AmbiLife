"""
Rolling signal buffer that computes typing-behaviour metrics over a sliding
time window — without storing any key content.

Metrics returned by compute_metrics():
  wpm            — estimated words per minute (5 chars = 1 word)
  pause_ratio    — fraction of window time spent NOT typing (0.0 – 1.0)
  backspace_rate — backspaces / total keystroke count (0.0 – 1.0)
  burst_score    — normalised standard deviation of inter-keystroke intervals
                   (higher = more erratic / bursting)
"""
from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass
from typing import NamedTuple

from src.keyboard.listener import KeyEventType


# A keystroke pause is counted when the gap between consecutive keystrokes
# exceeds this threshold (seconds).
_PAUSE_THRESHOLD_S: float = 2.0


@dataclass(frozen=True)
class TypingMetrics:
    wpm: float
    pause_ratio: float
    backspace_rate: float
    burst_score: float

    @property
    def is_empty(self) -> bool:
        return self.wpm == 0.0 and self.backspace_rate == 0.0


class _Event(NamedTuple):
    event_type: KeyEventType
    ts: float  # monotonic seconds


class SignalBuffer:
    """
    Thread-safe ring buffer of key events for a configurable time window.
    """

    def __init__(self, window_seconds: float = 120.0) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._window = window_seconds
        self._events: deque[_Event] = deque()
        # Import here to avoid circular import at module level
        import threading
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_event(self, event_type: KeyEventType, ts: float) -> None:
        with self._lock:
            self._events.append(_Event(event_type, ts))
            self._evict(ts)

    def compute_metrics(self) -> TypingMetrics:
        with self._lock:
            now = time.monotonic()
            self._evict(now)
            events = list(self._events)

        return _compute(events, window_seconds=self._window)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _evict(self, now: float) -> None:
        cutoff = now - self._window
        while self._events and self._events[0].ts < cutoff:
            self._events.popleft()


# ------------------------------------------------------------------
# Pure computation helper (no side-effects, easy to unit test)
# ------------------------------------------------------------------

def _compute(events: list[_Event], window_seconds: float) -> TypingMetrics:
    if not events:
        return TypingMetrics(wpm=0.0, pause_ratio=0.0, backspace_rate=0.0, burst_score=0.0)

    # Only count chars + backspaces as "keystrokes" (ignore Shift, Ctrl, etc.)
    keystrokes = [e for e in events if e.event_type in (KeyEventType.CHAR, KeyEventType.BACKSPACE)]
    total_ks = len(keystrokes)

    if total_ks == 0:
        return TypingMetrics(wpm=0.0, pause_ratio=1.0, backspace_rate=0.0, burst_score=0.0)

    # --- WPM ---
    char_count = sum(1 for e in keystrokes if e.event_type == KeyEventType.CHAR)
    elapsed = min(window_seconds, events[-1].ts - events[0].ts) if len(events) > 1 else 0.0
    elapsed_min = max(elapsed / 60.0, 1 / 60.0)  # at least 1 second to avoid div/0
    wpm = (char_count / 5.0) / elapsed_min

    # --- Backspace rate ---
    bs_count = total_ks - char_count
    backspace_rate = bs_count / total_ks

    # --- Pause ratio ---
    # Count gap time between consecutive keystrokes exceeding threshold
    pause_time = 0.0
    ks_timestamps = [e.ts for e in keystrokes]
    for i in range(1, len(ks_timestamps)):
        gap = ks_timestamps[i] - ks_timestamps[i - 1]
        if gap > _PAUSE_THRESHOLD_S:
            pause_time += gap
    actual_elapsed = max(ks_timestamps[-1] - ks_timestamps[0], 1.0)
    pause_ratio = min(pause_time / actual_elapsed, 1.0)

    # --- Burst score ---
    # Normalised std-dev of inter-keystroke intervals (only gaps < pause threshold)
    gaps = [
        ks_timestamps[i] - ks_timestamps[i - 1]
        for i in range(1, len(ks_timestamps))
        if ks_timestamps[i] - ks_timestamps[i - 1] < _PAUSE_THRESHOLD_S
    ]
    if len(gaps) >= 2:
        mean_gap = sum(gaps) / len(gaps)
        variance = sum((g - mean_gap) ** 2 for g in gaps) / len(gaps)
        std_dev = math.sqrt(variance)
        burst_score = min(std_dev / max(mean_gap, 0.001), 1.0)
    else:
        burst_score = 0.0

    return TypingMetrics(
        wpm=round(wpm, 2),
        pause_ratio=round(pause_ratio, 4),
        backspace_rate=round(backspace_rate, 4),
        burst_score=round(burst_score, 4),
    )
