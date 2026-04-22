"""
Global mouse listener using pynput.

PRIVACY NOTE: Only anonymised metadata is captured — event timestamps and the
category of mouse action (click, scroll, or movement burst). Pointer coordinates
are only used transiently to accumulate movement distance; they are never stored.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from typing import Callable

from src.keyboard.listener import InputEventType

logger = logging.getLogger(__name__)

# Minimum accumulated movement (pixels) before emitting a MOUSE_MOVE_BURST event.
_MOVE_BURST_THRESHOLD_PX: float = 200.0
# Minimum time (seconds) between consecutive MOUSE_MOVE_BURST emissions.
_MOVE_BURST_MIN_INTERVAL_S: float = 0.1

try:
    from pynput import mouse as _pynput_mouse
    _PYNPUT_AVAILABLE = True
except Exception as _e:
    _pynput_mouse = None  # type: ignore[assignment]
    _PYNPUT_AVAILABLE = False
    logger.warning("pynput mouse unavailable (%s) — mouse signals will not be detected.", _e)


class MouseEventListener:
    """
    Listens for global mouse events and emits anonymised metadata events.

    The callback receives (event_type: InputEventType, timestamp: float) where
    timestamp is the monotonic time in seconds.  The interface is intentionally
    identical to KeyEventListener so both can share the same buffer callback.
    """

    def __init__(self, callback: Callable[[InputEventType, float], None]) -> None:
        self._callback = callback
        self._listener = None
        self._lock = threading.Lock()

        # Movement accumulation state (only accessed from the pynput thread).
        self._move_accumulated: float = 0.0
        self._last_move_pos: tuple[int, int] | None = None
        self._last_burst_ts: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        if not _PYNPUT_AVAILABLE:
            logger.warning("Mouse listener not started: pynput mouse unavailable.")
            return
        with self._lock:
            if self._listener is not None:
                return
            try:
                self._listener = _pynput_mouse.Listener(
                    on_click=self._on_click,
                    on_scroll=self._on_scroll,
                    on_move=self._on_move,
                )
                self._listener.start()
                logger.info("Mouse listener started.")
            except Exception as exc:
                self._listener = None
                logger.warning("Mouse listener failed to start: %s", exc)

    def stop(self) -> None:
        with self._lock:
            if self._listener is None:
                return
            self._listener.stop()
            self._listener = None

    @property
    def running(self) -> bool:
        with self._lock:
            return self._listener is not None and self._listener.is_alive()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_click(self, x: int, y: int, button, pressed: bool) -> None:
        if not pressed:
            return  # only fire on button-down
        try:
            self._callback(InputEventType.MOUSE_CLICK, time.monotonic())
        except Exception:
            pass

    def _on_scroll(self, x: int, y: int, dx: float, dy: float) -> None:
        if dx == 0.0 and dy == 0.0:
            return  # ignore zero-delta inertia ticks
        try:
            self._callback(InputEventType.MOUSE_SCROLL, time.monotonic())
        except Exception as exc:
            logger.debug("Mouse scroll callback error: %s", exc)

    def _on_move(self, x: int, y: int) -> None:
        if self._last_move_pos is not None:
            lx, ly = self._last_move_pos
            dist = math.hypot(x - lx, y - ly)
            self._move_accumulated += dist
        self._last_move_pos = (x, y)

        now = time.monotonic()
        if (
            self._move_accumulated >= _MOVE_BURST_THRESHOLD_PX
            and now - self._last_burst_ts >= _MOVE_BURST_MIN_INTERVAL_S
        ):
            self._move_accumulated = 0.0
            self._last_burst_ts = now
            try:
                self._callback(InputEventType.MOUSE_MOVE_BURST, now)
            except Exception:
                pass
