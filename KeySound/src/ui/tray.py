"""
System-tray icon using pystray.

The tray icon:
  - Changes colour/icon to reflect the current mood
  - Provides a menu: Current Mood (display), Pause/Resume, Settings, Quit
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

import pystray
from PIL import Image, ImageDraw

from src.mood.classifier import Mood

# Mood → RGB colour for the generated fallback icon
_MOOD_COLORS: dict[Mood, tuple[int, int, int]] = {
    Mood.FLOWING: (0, 200, 100),      # green
    Mood.FOCUSED: (60, 120, 220),     # blue
    Mood.STRUGGLING: (220, 80, 60),   # red-orange
    Mood.IDLE: (140, 140, 140),       # grey
}


def _make_icon(mood: Mood, size: int = 64) -> Image.Image:
    """Generate a simple solid-circle icon for a mood (used when no .ico file)."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    color = _MOOD_COLORS.get(mood, (180, 180, 180))
    margin = 4
    draw.ellipse([margin, margin, size - margin, size - margin], fill=color)
    return img


class TrayApp:
    """
    Wraps pystray.Icon and exposes a simple API to update mood state.
    Runs pystray on the calling thread (must be the main thread on Windows).
    """

    def __init__(
        self,
        on_settings: Callable[[], None],
        on_quit: Callable[[], None],
        on_toggle_tracking: Callable[[], None],
        on_play_now: Callable[[], None],
    ) -> None:
        self._on_settings = on_settings
        self._on_quit = on_quit
        self._on_toggle_tracking = on_toggle_tracking
        self._on_play_now = on_play_now
        self._current_mood: Mood = Mood.IDLE
        self._tracking_enabled: bool = True
        self._icon: Optional[pystray.Icon] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_mood(self, mood: Mood) -> None:
        self._current_mood = mood
        if self._icon:
            self._icon.icon = _make_icon(mood)
            self._icon.update_menu()

    def set_tracking(self, enabled: bool) -> None:
        self._tracking_enabled = enabled
        if self._icon:
            self._icon.update_menu()

    def run(self) -> None:
        """Blocking call — runs the tray event loop."""
        self._icon = pystray.Icon(
            name="KeySound",
            icon=_make_icon(self._current_mood),
            title="KeySound",
            menu=self._build_menu(),
        )
        self._icon.run()

    def stop(self) -> None:
        if self._icon:
            self._icon.stop()

    def notify(self, title: str, message: str) -> None:
        if self._icon:
            self._icon.notify(message, title)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem(
                lambda _: f"Mood: {self._current_mood.value.capitalize()}",
                action=None,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Play Now", action=self._handle_play_now),
            pystray.MenuItem(
                lambda _: "Pause Tracking" if self._tracking_enabled else "Resume Tracking",
                action=self._handle_toggle_tracking,
            ),
            pystray.MenuItem("Settings…", action=self._handle_settings),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", action=self._handle_quit),
        )

    def _handle_settings(self, icon, item) -> None:
        threading.Thread(target=self._on_settings, daemon=True).start()

    def _handle_play_now(self, icon, item) -> None:
        threading.Thread(target=self._on_play_now, daemon=True).start()

    def _handle_toggle_tracking(self, icon, item) -> None:
        self._on_toggle_tracking()

    def _handle_quit(self, icon, item) -> None:
        self._on_quit()
