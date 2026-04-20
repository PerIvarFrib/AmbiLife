"""
Unit tests for the mood classifier.
Run with: pytest tests/test_classifier.py
"""
from src.keyboard.signal_buffer import TypingMetrics
from src.mood.classifier import Mood, MoodThresholds, classify

_T = MoodThresholds()  # default thresholds


def _metrics(wpm=0.0, pause_ratio=0.0, backspace_rate=0.0, burst_score=0.0) -> TypingMetrics:
    return TypingMetrics(
        wpm=wpm,
        pause_ratio=pause_ratio,
        backspace_rate=backspace_rate,
        burst_score=burst_score,
    )


class TestIdleMood:
    def test_empty_metrics_is_idle(self):
        assert classify(_metrics()) == Mood.IDLE

    def test_zero_wpm_zero_backspace_is_idle(self):
        assert classify(_metrics(wpm=0.0, backspace_rate=0.0)) == Mood.IDLE


class TestFlowingMood:
    def test_high_wpm_low_errors_is_flowing(self):
        m = _metrics(wpm=60.0, backspace_rate=0.04, pause_ratio=0.10)
        assert classify(m, _T) == Mood.FLOWING

    def test_exactly_at_threshold_is_flowing(self):
        m = _metrics(wpm=40.0, backspace_rate=0.08, pause_ratio=0.30)
        assert classify(m, _T) == Mood.FLOWING

    def test_just_below_wpm_threshold_not_flowing(self):
        m = _metrics(wpm=39.9, backspace_rate=0.04, pause_ratio=0.10)
        assert classify(m, _T) != Mood.FLOWING

    def test_high_wpm_but_high_backspace_not_flowing(self):
        m = _metrics(wpm=60.0, backspace_rate=0.09, pause_ratio=0.10)
        assert classify(m, _T) != Mood.FLOWING

    def test_high_wpm_but_high_pause_not_flowing(self):
        m = _metrics(wpm=60.0, backspace_rate=0.04, pause_ratio=0.31)
        assert classify(m, _T) != Mood.FLOWING


class TestStrugglingMood:
    def test_high_backspace_rate_is_struggling(self):
        m = _metrics(wpm=20.0, backspace_rate=0.20, pause_ratio=0.20, burst_score=0.90)
        assert classify(m, _T) == Mood.STRUGGLING

    def test_exactly_at_backspace_threshold_is_struggling(self):
        m = _metrics(wpm=20.0, backspace_rate=0.15, pause_ratio=0.20, burst_score=0.90)
        assert classify(m, _T) == Mood.STRUGGLING

    def test_burst_alone_is_not_struggling(self):
        # High burst_score with low backspace should NOT trigger struggling —
        # normal typing is bursty by nature.
        m = _metrics(wpm=20.0, backspace_rate=0.05, pause_ratio=0.20, burst_score=0.90)
        assert classify(m, _T) == Mood.FOCUSED

    def test_both_signals_is_struggling(self):
        m = _metrics(wpm=20.0, backspace_rate=0.20, pause_ratio=0.20, burst_score=0.90)
        assert classify(m, _T) == Mood.STRUGGLING

    def test_just_below_backspace_threshold_not_struggling(self):
        m = _metrics(wpm=20.0, backspace_rate=0.14, pause_ratio=0.20)
        # Could be FOCUSED (not STRUGGLING)
        assert classify(m, _T) == Mood.FOCUSED


class TestFocusedMood:
    def test_moderate_typing_is_focused(self):
        m = _metrics(wpm=25.0, backspace_rate=0.05, pause_ratio=0.25)
        assert classify(m, _T) == Mood.FOCUSED

    def test_slow_but_steady_is_focused(self):
        m = _metrics(wpm=15.0, backspace_rate=0.05, pause_ratio=0.15)
        assert classify(m, _T) == Mood.FOCUSED


class TestCustomThresholds:
    def test_custom_flowing_wpm_lower(self):
        custom = MoodThresholds(flowing_min_wpm=20.0)
        m = _metrics(wpm=25.0, backspace_rate=0.04, pause_ratio=0.10)
        assert classify(m, custom) == Mood.FLOWING

    def test_custom_struggling_backspace_higher(self):
        custom = MoodThresholds(struggling_min_backspace_rate=0.30)
        m = _metrics(wpm=20.0, backspace_rate=0.20, pause_ratio=0.20, burst_score=0.90)
        # With raised threshold, 20% backspace is no longer struggling
        assert classify(m, custom) == Mood.FOCUSED
