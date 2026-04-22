"""
Global keyboard listener using pynput.

PRIVACY NOTE: Only metadata is captured — event timestamps and the category of
key pressed (printable char, backspace, shortcut, navigation, or other special).
The actual characters typed are NEVER stored, logged, or transmitted.
"""
from __future__ import annotations

import threading
from enum import Enum, auto
from typing import Callable
from pynput import keyboard

# Navigation keys that signal editing/reading behaviour when pressed alone.
_NAV_KEYS = {
    keyboard.Key.up, keyboard.Key.down, keyboard.Key.left, keyboard.Key.right,
    keyboard.Key.home, keyboard.Key.end, keyboard.Key.page_up, keyboard.Key.page_down,
    keyboard.Key.tab,
}

# Modifier keys — held state tracked to detect shortcuts.
_MODIFIER_KEYS = {
    keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r,
    keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r,
    keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r,
}


class InputEventType(Enum):
    CHAR = auto()           # Any printable character (content not recorded)
    BACKSPACE = auto()      # Backspace / delete key
    SHORTCUT = auto()       # Modifier (Ctrl/Alt/Win) held + another key pressed
    NAVIGATION = auto()     # Arrow keys, Home, End, PgUp, PgDn, Tab (no modifier)
    SPECIAL = auto()        # Any other special key (shift, enter, etc.)
    # Mouse variants — emitted by MouseEventListener via the same callback type
    MOUSE_CLICK = auto()    # Left or right mouse button press
    MOUSE_SCROLL = auto()   # Scroll wheel event
    MOUSE_MOVE_BURST = auto()  # Accumulated ≥200 px of mouse movement


# Backward-compat alias so existing imports of KeyEventType keep working.
KeyEventType = InputEventType


class KeyEventListener:
    """
    Listens for global keyboard events and emits anonymised metadata events.

    The callback receives (event_type: InputEventType, timestamp: float) where
    timestamp is the monotonic time in seconds.
    """

    def __init__(self, callback: Callable[[InputEventType, float], None]) -> None:
        self._callback = callback
        self._listener: keyboard.Listener | None = None
        self._lock = threading.Lock()
        self._modifiers: set = set()  # currently held modifier keys

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._listener is not None:
                return
            self._listener = keyboard.Listener(
                on_press=self._on_press,
                on_release=self._on_release,
            )
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

    def _on_release(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        self._modifiers.discard(key)

    def _on_press(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        import time

        ts = time.monotonic()

        if key in _MODIFIER_KEYS:
            self._modifiers.add(key)
            return  # modifier press alone is not an activity event

        if key == keyboard.Key.backspace:
            event_type = InputEventType.BACKSPACE
        elif self._modifiers:
            # A non-modifier key pressed while a modifier is held → shortcut
            event_type = InputEventType.SHORTCUT
        elif key in _NAV_KEYS:
            event_type = InputEventType.NAVIGATION
        elif isinstance(key, keyboard.KeyCode) and key.char is not None:
            event_type = InputEventType.CHAR
        else:
            event_type = InputEventType.SPECIAL

        try:
            self._callback(event_type, ts)
        except Exception:
            pass  # Never let a callback crash the listener thread
