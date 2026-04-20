"""
Global keyboard listener using pynput.

PRIVACY NOTE: Only metadata is captured — event timestamps and whether a key
is a backspace or a regular character. The actual characters typed are NEVER
stored, logged, or transmitted.
"""
from __future__ import annotations

import threading
from enum import Enum, auto
from typing import Callable
from pynput import keyboard


class KeyEventType(Enum):
    CHAR = auto()       # Any printable character (content not recorded)
    BACKSPACE = auto()  # Backspace / delete key
    SPECIAL = auto()    # Any other special key (shift, enter, ctrl, etc.)


class KeyEventListener:
    """
    Listens for global keyboard events and emits anonymised metadata events.

    The callback receives (event_type: KeyEventType, timestamp: float) where
    timestamp is the monotonic time in seconds.
    """

    def __init__(self, callback: Callable[[KeyEventType, float], None]) -> None:
        self._callback = callback
        self._listener: keyboard.Listener | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._listener is not None:
                return
            self._listener = keyboard.Listener(on_press=self._on_press)
            self._listener.start()

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

    def _on_press(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        import time

        ts = time.monotonic()

        if key == keyboard.Key.backspace:
            event_type = KeyEventType.BACKSPACE
        elif isinstance(key, keyboard.KeyCode) and key.char is not None:
            event_type = KeyEventType.CHAR
        else:
            event_type = KeyEventType.SPECIAL

        try:
            self._callback(event_type, ts)
        except Exception:
            pass  # Never let a callback crash the listener thread
