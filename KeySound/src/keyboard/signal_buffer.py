"""
Rolling signal buffer that computes activity-behaviour metrics over a sliding
time window — without storing any key content or pointer coordinates.

Metrics returned by compute_metrics():
  wpm                 — estimated words per minute (5 chars = 1 word)
  pause_ratio         — fraction of window time spent NOT typing (0.0 – 1.0)
  backspace_rate      — backspaces / typing keystroke count (0.0 – 1.0)
  burst_score         — normalised std-dev of inter-keystroke intervals
  shortcut_rate       — SHORTCUT events / all keyboard events (0.0 – 1.0)
  nav_rate            — NAVIGATION events / all keyboard events (0.0 – 1.0)
  scroll_rate         — MOUSE_SCROLL events per minute
  click_rate          — MOUSE_CLICK events per minute
  mouse_activity_rate — (MOUSE_CLICK + MOUSE_SCROLL + MOUSE_MOVE_BURST) per minute
"""
from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass
from typing import NamedTuple

from src.keyboard.listener import InputEventType


# A keystroke pause is counted when the gap between consecutive keystrokes
# exceeds this threshold (seconds).
_PAUSE_THRESHOLD_S: float = 2.0

# Keyboard-only event types used for typing metrics.
_TYPING_TYPES = frozenset({
    InputEventType.CHAR,
    InputEventType.BACKSPACE,
    InputEventType.SHORTCUT,
    InputEventType.NAVIGATION,
})


@dataclass(frozen=True)
class ActivityMetrics:
    wpm: float
    pause_ratio: float
    backspace_rate: float
    burst_score: float
    shortcut_rate: float
    nav_rate: float
    scroll_rate: float        # events per minute
    click_rate: float         # events per minute
    mouse_activity_rate: float  # events per minute

    @property
    def is_empty(self) -> bool:
        return (
            self.wpm == 0.0
            and self.backspace_rate == 0.0
            and self.shortcut_rate == 0.0
            and self.nav_rate == 0.0
            and self.scroll_rate == 0.0
            and self.click_rate == 0.0
            and self.mouse_activity_rate == 0.0
        )


# Backward-compat alias — existing code that imports TypingMetrics still works.
TypingMetrics = ActivityMetrics


class _Event(NamedTuple):
    event_type: InputEventType
    ts: float  # monotonic seconds


class SignalBuffer:
    """
    Thread-safe ring buffer of input events for a configurable time window.
    Accepts both keyboard (InputEventType.CHAR / BACKSPACE / …) and mouse
    (MOUSE_CLICK / MOUSE_SCROLL / MOUSE_MOVE_BURST) events.
    """

    def __init__(self, window_seconds: float = 120.0) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._window = window_seconds
        self._events: deque[_Event] = deque()
        import threading
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_event(self, event_type: InputEventType, ts: float) -> None:
        with self._lock:
            self._events.append(_Event(event_type, ts))
            self._evict(ts)

    def compute_metrics(self) -> ActivityMetrics:
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

def _compute(events: list[_Event], window_seconds: float) -> ActivityMetrics:
    _zero = ActivityMetrics(
        wpm=0.0, pause_ratio=0.0, backspace_rate=0.0, burst_score=0.0,
        shortcut_rate=0.0, nav_rate=0.0, scroll_rate=0.0,
        click_rate=0.0, mouse_activity_rate=0.0,
    )
    if not events:
        return _zero

    # --- Elapsed window time (capped at window_seconds) ---
    elapsed = min(window_seconds, events[-1].ts - events[0].ts) if len(events) > 1 else 0.0
    elapsed_min = max(elapsed / 60.0, 1 / 60.0)

    # --- Keyboard events ---
    kb_events = [e for e in events if e.event_type in _TYPING_TYPES]
    total_kb = len(kb_events)

    char_count = sum(1 for e in kb_events if e.event_type == InputEventType.CHAR)
    bs_count = sum(1 for e in kb_events if e.event_type == InputEventType.BACKSPACE)
    shortcut_count = sum(1 for e in kb_events if e.event_type == InputEventType.SHORTCUT)
    nav_count = sum(1 for e in kb_events if e.event_type == InputEventType.NAVIGATION)

    # --- WPM (char events only, excluding backspace/shortcuts/nav) ---
    wpm = (char_count / 5.0) / elapsed_min if char_count > 0 else 0.0

    # --- Typing keystrokes for rhythm metrics (CHAR + BACKSPACE) ---
    typing_ks = [e for e in kb_events if e.event_type in (InputEventType.CHAR, InputEventType.BACKSPACE)]
    total_typing = len(typing_ks)

    # --- Backspace rate ---
    backspace_rate = bs_count / total_typing if total_typing > 0 else 0.0

    # --- Pause ratio ---
    pause_time = 0.0
    if total_typing > 0:
        ks_timestamps = [e.ts for e in typing_ks]
        for i in range(1, len(ks_timestamps)):
            gap = ks_timestamps[i] - ks_timestamps[i - 1]
            if gap > _PAUSE_THRESHOLD_S:
                pause_time += gap
        actual_elapsed = max(ks_timestamps[-1] - ks_timestamps[0], 1.0)
        pause_ratio = min(pause_time / actual_elapsed, 1.0)
    else:
        ks_timestamps = []
        pause_ratio = 0.0

    # --- Burst score ---
    if len(ks_timestamps) >= 2:
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
    else:
        burst_score = 0.0

    # --- Shortcut / navigation rates (fraction of keyboard events) ---
    shortcut_rate = shortcut_count / total_kb if total_kb > 0 else 0.0
    nav_rate = nav_count / total_kb if total_kb > 0 else 0.0

    # --- Mouse event rates (per minute) ---
    scroll_count = sum(1 for e in events if e.event_type == InputEventType.MOUSE_SCROLL)
    click_count = sum(1 for e in events if e.event_type == InputEventType.MOUSE_CLICK)
    burst_count = sum(1 for e in events if e.event_type == InputEventType.MOUSE_MOVE_BURST)

    scroll_rate = scroll_count / elapsed_min
    click_rate = click_count / elapsed_min
    mouse_activity_rate = (click_count + scroll_count + burst_count) / elapsed_min

    return ActivityMetrics(
        wpm=round(wpm, 2),
        pause_ratio=round(pause_ratio, 4),
        backspace_rate=round(backspace_rate, 4),
        burst_score=round(burst_score, 4),
        shortcut_rate=round(shortcut_rate, 4),
        nav_rate=round(nav_rate, 4),
        scroll_rate=round(scroll_rate, 2),
        click_rate=round(click_rate, 2),
        mouse_activity_rate=round(mouse_activity_rate, 2),
    )
