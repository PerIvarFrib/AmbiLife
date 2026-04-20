"""
Rule-based mood classifier.

Thresholds are injected as a MoodThresholds dataclass so they can be loaded
from user settings and swapped without touching this logic.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.keyboard.signal_buffer import TypingMetrics


class Mood(str, Enum):
    FLOWING = "flowing"       # High WPM, low errors, low pauses
    FOCUSED = "focused"       # Moderate, deliberate typing
    STRUGGLING = "struggling" # High backspace rate, erratic rhythm
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

    # IDLE: handled externally via idle timeout (seconds with no keystrokes)
    idle_timeout_seconds: float = 180.0


_DEFAULT_THRESHOLDS = MoodThresholds()


def classify(metrics: TypingMetrics, thresholds: MoodThresholds = _DEFAULT_THRESHOLDS) -> Mood:
    """
    Pure function: maps TypingMetrics to a Mood label.

    Precedence: IDLE is set externally; among the remaining three:
      1. FLOWING  (high confidence positive signal)
      2. STRUGGLING (high confidence negative signal)
      3. FOCUSED  (default / everything else)
    """
    if metrics.is_empty:
        return Mood.IDLE

    t = thresholds

    if (
        metrics.wpm >= t.flowing_min_wpm
        and metrics.backspace_rate <= t.flowing_max_backspace_rate
        and metrics.pause_ratio <= t.flowing_max_pause_ratio
    ):
        return Mood.FLOWING

    if (
        metrics.backspace_rate >= t.struggling_min_backspace_rate
        and metrics.burst_score >= t.struggling_min_burst_score
    ):
        return Mood.STRUGGLING

    return Mood.FOCUSED
