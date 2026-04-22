"""
Unit tests for the mood classifier.
Run with: pytest tests/test_classifier.py
"""
from src.keyboard.signal_buffer import ActivityMetrics
from src.mood.classifier import Mood, MoodThresholds, classify

_T = MoodThresholds()  # default thresholds


def _metrics(
    wpm=0.0, pause_ratio=0.0, backspace_rate=0.0, burst_score=0.0,
    shortcut_rate=0.0, nav_rate=0.0, scroll_rate=0.0,
    click_rate=0.0, mouse_activity_rate=0.0,
) -> ActivityMetrics:
    return ActivityMetrics(
        wpm=wpm,
        pause_ratio=pause_ratio,
        backspace_rate=backspace_rate,
        burst_score=burst_score,
        shortcut_rate=shortcut_rate,
        nav_rate=nav_rate,
        scroll_rate=scroll_rate,
        click_rate=click_rate,
        mouse_activity_rate=mouse_activity_rate,
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


class TestEditingMood:
    def test_high_shortcut_rate_low_wpm_is_editing(self):
        m = _metrics(wpm=5.0, shortcut_rate=0.30)
        assert classify(m, _T) == Mood.EDITING

    def test_high_nav_rate_low_wpm_is_editing(self):
        m = _metrics(wpm=10.0, nav_rate=0.40)
        assert classify(m, _T) == Mood.EDITING

    def test_editing_not_triggered_at_high_wpm(self):
        # If WPM is above editing_max_wpm, EDITING should not fire
        m = _metrics(wpm=30.0, shortcut_rate=0.30)
        # Should fall to FOCUSED since not flowing/struggling and wpm >= editing_max_wpm
        assert classify(m, _T) == Mood.FOCUSED

    def test_flowing_takes_precedence_over_editing(self):
        # Fast typist who also uses shortcuts stays FLOWING
        m = _metrics(wpm=50.0, backspace_rate=0.04, pause_ratio=0.10, shortcut_rate=0.20)
        assert classify(m, _T) == Mood.FLOWING

    def test_editing_with_no_activity_not_editing(self):
        assert classify(_metrics(), _T) == Mood.IDLE


class TestReadingMood:
    def test_near_zero_wpm_with_scrolling_is_reading(self):
        m = _metrics(wpm=0.0, scroll_rate=5.0)
        assert classify(m, _T) == Mood.READING

    def test_low_wpm_just_at_threshold_with_scrolling(self):
        m = _metrics(wpm=5.0, scroll_rate=2.0)
        assert classify(m, _T) == Mood.READING

    def test_scrolling_with_too_much_typing_not_reading(self):
        # WPM above reading_max_wpm — user is typing AND scrolling → not reading
        m = _metrics(wpm=20.0, scroll_rate=5.0)
        assert classify(m, _T) != Mood.READING

    def test_low_wpm_without_scrolling_not_reading(self):
        # Near-zero typing but no scrolling → FOCUSED (not reading)
        m = _metrics(wpm=2.0, scroll_rate=0.0)
        assert classify(m, _T) == Mood.FOCUSED

    def test_reading_idle_boundary(self):
        # is_empty check fires before reading — all-zero metrics → IDLE not READING
        assert classify(_metrics(scroll_rate=0.0), _T) == Mood.IDLE
