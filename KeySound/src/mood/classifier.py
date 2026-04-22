"""
Rule-based mood classifier.

Thresholds are injected as a MoodThresholds dataclass so they can be loaded
from user settings and swapped without touching this logic.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.keyboard.signal_buffer import ActivityMetrics

# Backward-compat alias so any existing code importing TypingMetrics still works.
TypingMetrics = ActivityMetrics


class Mood(str, Enum):
    FLOWING = "flowing"       # High WPM, low errors, low pauses
    FOCUSED = "focused"       # Moderate, deliberate typing
    STRUGGLING = "struggling" # High backspace rate, erratic rhythm
    EDITING = "editing"       # Shortcuts / navigation keys dominate, low typing
    READING = "reading"       # Near-zero typing with active scrolling
    IDLE = "idle"             # No activity


@dataclass(frozen=True)
class MoodThresholds:
    # FLOWING thresholds (all must be met)
    flowing_min_wpm: float = 40.0
    flowing_max_backspace_rate: float = 0.08
    flowing_max_pause_ratio: float = 0.30

    # STRUGGLING thresholds (BOTH must be met).
    # burst_score alone is NOT enough: natural typing is bursty (fast within
    # words, slower between), so burst_score routinely exceeds 0.70 for any
    # normal typist.  Requiring both signals avoids false positives.
    struggling_min_backspace_rate: float = 0.15
    struggling_min_burst_score: float = 0.85

    # EDITING thresholds
    editing_min_shortcut_rate: float = 0.10  # fraction of kb events that are shortcuts
    editing_min_nav_rate: float = 0.15        # fraction of kb events that are nav keys
    editing_max_wpm: float = 25.0             # EDITING only when not flowing

    # READING thresholds
    reading_max_wpm: float = 5.0             # near-zero typing
    reading_min_scroll_rate: float = 2.0     # scrolls per minute

    # IDLE: handled externally via idle timeout (seconds with no activity)
    idle_timeout_seconds: float = 180.0


_DEFAULT_THRESHOLDS = MoodThresholds()


def classify(metrics: ActivityMetrics, thresholds: MoodThresholds = _DEFAULT_THRESHOLDS) -> Mood:
    """
    Pure function: maps ActivityMetrics to a Mood label.

    Precedence (first match wins):
      1. IDLE       — no keyboard or mouse activity at all
      2. READING    — near-zero typing + active scrolling
      3. FLOWING    — high WPM, low errors, low pauses
      4. STRUGGLING — high backspace rate + erratic rhythm
      5. EDITING    — shortcuts/nav dominate, low WPM
      6. FOCUSED    — default fallback
    """
    if metrics.is_empty:
        return Mood.IDLE

    t = thresholds

    # READING: very little typing, but the user is actively scrolling.
    if (
        metrics.wpm <= t.reading_max_wpm
        and metrics.scroll_rate >= t.reading_min_scroll_rate
    ):
        return Mood.READING

    # FLOWING: high-confidence positive typing signal.
    if (
        metrics.wpm >= t.flowing_min_wpm
        and metrics.backspace_rate <= t.flowing_max_backspace_rate
        and metrics.pause_ratio <= t.flowing_max_pause_ratio
    ):
        return Mood.FLOWING

    # STRUGGLING: high-confidence negative signal (requires both signals).
    if (
        metrics.backspace_rate >= t.struggling_min_backspace_rate
        and metrics.burst_score >= t.struggling_min_burst_score
    ):
        return Mood.STRUGGLING

    # EDITING: shortcut / navigation key activity dominates, low WPM.
    if (
        metrics.wpm < t.editing_max_wpm
        and (
            metrics.shortcut_rate >= t.editing_min_shortcut_rate
            or metrics.nav_rate >= t.editing_min_nav_rate
        )
    ):
        return Mood.EDITING

    return Mood.FOCUSED
