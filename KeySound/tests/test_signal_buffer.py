"""
Unit tests for SignalBuffer and the _compute helper.
Run with: pytest tests/test_signal_buffer.py
"""
import time
from src.keyboard.listener import InputEventType
from src.keyboard.signal_buffer import SignalBuffer, _compute, _Event


def _char(ts: float) -> _Event:
    return _Event(InputEventType.CHAR, ts)


def _bs(ts: float) -> _Event:
    return _Event(InputEventType.BACKSPACE, ts)


def _shortcut(ts: float) -> _Event:
    return _Event(InputEventType.SHORTCUT, ts)


def _nav(ts: float) -> _Event:
    return _Event(InputEventType.NAVIGATION, ts)


def _scroll(ts: float) -> _Event:
    return _Event(InputEventType.MOUSE_SCROLL, ts)


def _click(ts: float) -> _Event:
    return _Event(InputEventType.MOUSE_CLICK, ts)


def _move_burst(ts: float) -> _Event:
    return _Event(InputEventType.MOUSE_MOVE_BURST, ts)


class TestComputeEmpty:
    def test_returns_zeros_for_no_events(self):
        m = _compute([], window_seconds=120)
        assert m.wpm == 0.0
        assert m.pause_ratio == 0.0
        assert m.backspace_rate == 0.0
        assert m.burst_score == 0.0
        assert m.shortcut_rate == 0.0
        assert m.nav_rate == 0.0
        assert m.scroll_rate == 0.0
        assert m.click_rate == 0.0
        assert m.mouse_activity_rate == 0.0
        assert m.is_empty


class TestWPM:
    def test_simple_wpm(self):
        # 60 chars in 60 seconds → 12 WPM (60 chars / 5 chars/word / 1 min)
        events = [_char(float(i)) for i in range(60)]
        m = _compute(events, window_seconds=120)
        assert 11 <= m.wpm <= 13

    def test_fast_typing(self):
        # 300 chars in 60 seconds → 60 WPM
        step = 60 / 300
        events = [_char(i * step) for i in range(300)]
        m = _compute(events, window_seconds=120)
        assert 55 <= m.wpm <= 65


class TestBackspaceRate:
    def test_no_backspaces(self):
        events = [_char(float(i)) for i in range(20)]
        m = _compute(events, window_seconds=120)
        assert m.backspace_rate == 0.0

    def test_half_backspaces(self):
        events = []
        for i in range(20):
            events.append(_char(float(i * 2)))
            events.append(_bs(float(i * 2 + 1)))
        m = _compute(events, window_seconds=120)
        assert abs(m.backspace_rate - 0.5) < 0.01

    def test_heavy_backspace_rate(self):
        events = [_char(float(i)) for i in range(17)] + [_bs(float(17 + i)) for i in range(3)]
        m = _compute(events, window_seconds=120)
        assert abs(m.backspace_rate - 0.15) < 0.01


class TestPauseRatio:
    def test_no_pauses(self):
        # Keys every 0.1s — no pause exceeds threshold
        events = [_char(i * 0.1) for i in range(50)]
        m = _compute(events, window_seconds=120)
        assert m.pause_ratio < 0.1

    def test_heavy_pauses(self):
        # 2 bursts separated by a 10-second pause
        burst1 = [_char(float(i) * 0.1) for i in range(10)]
        burst2 = [_char(20.0 + i * 0.1) for i in range(10)]
        m = _compute(burst1 + burst2, window_seconds=120)
        # ~10s pause out of ~21s elapsed — should be substantial
        assert m.pause_ratio > 0.3


class TestBurstScore:
    def test_regular_rhythm_low_burst(self):
        # Perfectly regular 0.2s intervals
        events = [_char(i * 0.2) for i in range(50)]
        m = _compute(events, window_seconds=120)
        assert m.burst_score < 0.1

    def test_erratic_rhythm_high_burst(self):
        import random
        random.seed(42)
        # Very erratic: random gaps between 0.05s and 1.5s
        ts = 0.0
        events = []
        for _ in range(50):
            events.append(_char(ts))
            ts += random.uniform(0.05, 1.5)
        m = _compute(events, window_seconds=120)
        assert m.burst_score > 0.3


class TestSignalBufferEviction:
    def test_old_events_evicted(self):
        buf = SignalBuffer(window_seconds=1.0)
        buf._events.append(_Event(InputEventType.CHAR, time.monotonic() - 10.0))
        buf._events.append(_Event(InputEventType.CHAR, time.monotonic()))
        m = buf.compute_metrics()
        assert len(buf) == 1

    def test_add_and_retrieve(self):
        buf = SignalBuffer(window_seconds=60.0)
        now = time.monotonic()
        buf.add_event(InputEventType.CHAR, now)
        buf.add_event(InputEventType.BACKSPACE, now + 0.1)
        assert len(buf) == 2


class TestShortcutAndNavRates:
    def test_shortcut_rate_pure_shortcuts(self):
        # 10 shortcuts, 0 other kb events → shortcut_rate = 1.0
        events = [_shortcut(float(i)) for i in range(10)]
        m = _compute(events, window_seconds=120)
        assert m.shortcut_rate == 1.0
        assert m.nav_rate == 0.0

    def test_nav_rate_pure_nav(self):
        events = [_nav(float(i)) for i in range(10)]
        m = _compute(events, window_seconds=120)
        assert m.nav_rate == 1.0
        assert m.shortcut_rate == 0.0

    def test_mixed_kb_rates(self):
        # 5 chars + 5 shortcuts → shortcut_rate = 0.5
        events = [_char(float(i)) for i in range(5)] + [_shortcut(5.0 + i) for i in range(5)]
        m = _compute(events, window_seconds=120)
        assert abs(m.shortcut_rate - 0.5) < 0.01

    def test_shortcuts_do_not_contribute_to_wpm(self):
        # Lots of shortcuts but no CHAR events → wpm should be 0
        events = [_shortcut(float(i)) for i in range(50)]
        m = _compute(events, window_seconds=120)
        assert m.wpm == 0.0


class TestMouseMetrics:
    def test_scroll_rate_positive(self):
        # 12 scrolls spread across 60 seconds → ~12 scrolls/min
        events = [_scroll(float(i) * 5) for i in range(12)]  # t=0,5,10,...,55
        m = _compute(events, window_seconds=120)
        assert m.scroll_rate > 0

    def test_no_mouse_events_zero_rates(self):
        events = [_char(float(i)) for i in range(10)]
        m = _compute(events, window_seconds=120)
        assert m.scroll_rate == 0.0
        assert m.click_rate == 0.0
        assert m.mouse_activity_rate == 0.0

    def test_mouse_activity_includes_all_types(self):
        events = [_click(0.0), _scroll(1.0), _move_burst(2.0)]
        m = _compute(events, window_seconds=120)
        assert m.mouse_activity_rate > 0
        assert m.click_rate > 0
        assert m.scroll_rate > 0

    def test_is_empty_false_with_only_mouse(self):
        events = [_scroll(0.0), _scroll(1.0), _scroll(2.0)]
        m = _compute(events, window_seconds=120)
        assert not m.is_empty
