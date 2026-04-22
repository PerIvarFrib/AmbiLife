"""
KeySound — entry point.

Threading model:
  - Main thread        : pystray tray icon event loop (required on Windows)
  - keyboard thread    : pynput listener (spawned by KeyEventListener.start())
  - classifier timer   : periodic threading.Timer chain (every N seconds)
  - settings window    : spawned in a daemon thread on demand
"""
from __future__ import annotations

import logging
import sys
import threading
import time

from src.config import settings as cfg_store
from src.config.schema import AppConfig
from src.keyboard.listener import InputEventType, KeyEventListener
from src.keyboard.signal_buffer import SignalBuffer
from src.mouse.listener import MouseEventListener
from src.mood.classifier import Mood, MoodThresholds, classify
from src.mood.state_manager import MoodStateManager
from src.audio.playback import PlaybackController
from src.ui.settings import SettingsWindow
from src.ui.tray import TrayApp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("keysound")


class KeySoundApp:
    def __init__(self) -> None:
        self._config: AppConfig = cfg_store.load()
        self._playback: PlaybackController | None = None
        self._buffer: SignalBuffer | None = None
        self._listener: KeyEventListener | None = None
        self._state_manager: MoodStateManager | None = None
        self._tray: TrayApp | None = None
        self._classifier_timer: threading.Timer | None = None
        self._last_activity_ts: float = 0.0
        self._tracking_enabled: bool = True
        self._settings_thread: threading.Thread | None = None
        self._mouse_listener: MouseEventListener | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def run(self) -> None:
        self._setup()
        logger.info("KeySound started. Tray icon active.")
        self._tray.run()  # blocking; pystray must run on the main thread on Windows

    def _setup(self) -> None:
        cfg = self._config
        det = cfg.detection

        # Signal buffer
        self._buffer = SignalBuffer(window_seconds=det.window_seconds)

        # Keyboard listener
        self._listener = KeyEventListener(callback=self._on_key_event)

        # Mood state manager
        self._state_manager = MoodStateManager(
            on_mood_change=self._on_mood_change,
            debounce_seconds=det.debounce_seconds,
        )

        # Playback
        self._setup_player(cfg)

        # Tray
        self._tray = TrayApp(
            on_settings=self._open_settings,
            on_quit=self._quit,
            on_toggle_tracking=self._toggle_tracking,
            on_play_now=self._play_now,
        )

        # Mouse listener
        self._mouse_listener = MouseEventListener(callback=self._on_mouse_event)

        # Start listening
        self._listener.start()
        self._mouse_listener.start()
        self._schedule_classifier()

    def _setup_player(self, cfg: AppConfig) -> None:
        try:
            self._playback = PlaybackController(on_error=self._on_audio_error)
            pl = cfg.playlists
            for mood_name, url in [
                ("flowing", pl.flowing),
                ("focused", pl.focused),
                ("struggling", pl.struggling),
                ("editing", pl.editing),
                ("reading", pl.reading),
                ("idle", pl.idle),
            ]:
                if url:
                    self._playback.set_playlist(mood_name, url)
        except Exception as exc:
            logger.warning("Player setup failed: %s", exc)

    # ------------------------------------------------------------------
    # Classifier timer
    # ------------------------------------------------------------------

    def _schedule_classifier(self) -> None:
        interval = self._config.detection.classifier_interval_seconds
        self._classifier_timer = threading.Timer(interval, self._run_classifier)
        self._classifier_timer.daemon = True
        self._classifier_timer.start()

    def _run_classifier(self) -> None:
        try:
            if not self._tracking_enabled:
                return

            idle_timeout = self._config.detection.idle_timeout_seconds
            now = time.monotonic()
            time_since_last_key = now - self._last_activity_ts if self._last_activity_ts else float("inf")

            if time_since_last_key >= idle_timeout:
                mood = Mood.IDLE
            else:
                metrics = self._buffer.compute_metrics()
                det = self._config.detection
                thresholds = MoodThresholds(
                    flowing_min_wpm=det.flowing_min_wpm,
                    flowing_max_backspace_rate=det.flowing_max_backspace_rate,
                    flowing_max_pause_ratio=det.flowing_max_pause_ratio,
                    struggling_min_backspace_rate=det.struggling_min_backspace_rate,
                    struggling_min_burst_score=det.struggling_min_burst_score,
                    editing_min_shortcut_rate=det.editing_min_shortcut_rate,
                    editing_min_nav_rate=det.editing_min_nav_rate,
                    editing_max_wpm=det.editing_max_wpm,
                    reading_max_wpm=det.reading_max_wpm,
                    reading_min_scroll_rate=det.reading_min_scroll_rate,
                    idle_timeout_seconds=det.idle_timeout_seconds,
                )
                mood = classify(metrics, thresholds)
                logger.info(
                    "Metrics → wpm=%.1f  bs=%.0f%%  pause=%.0f%%  burst=%.2f  "
                    "shortcut=%.0f%%  nav=%.0f%%  scroll=%.1f/min  → %s",
                    metrics.wpm,
                    metrics.backspace_rate * 100,
                    metrics.pause_ratio * 100,
                    metrics.burst_score,
                    metrics.shortcut_rate * 100,
                    metrics.nav_rate * 100,
                    metrics.scroll_rate,
                    mood.value,
                )

            self._state_manager.update(mood)
        except Exception as exc:
            logger.warning("Classifier error: %s", exc)
        finally:
            self._schedule_classifier()

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_key_event(self, event_type: InputEventType, ts: float) -> None:
        if not self._tracking_enabled:
            return
        self._last_activity_ts = ts
        self._buffer.add_event(event_type, ts)

    def _on_mouse_event(self, event_type: InputEventType, ts: float) -> None:
        if not self._tracking_enabled:
            return
        self._last_activity_ts = ts
        self._buffer.add_event(event_type, ts)

    def _on_mood_change(self, old_mood: Mood, new_mood: Mood) -> None:
        logger.info("Mood: %s → %s", old_mood.value, new_mood.value)
        if self._tray:
            self._tray.set_mood(new_mood)
        if self._playback is None:
            logger.warning("No playlists configured — open Settings and add YouTube playlist URLs.")
            return
        logger.info("Requesting playback for mood: %s", new_mood.value)
        self._playback.play_for_mood(new_mood.value)

    def _on_audio_error(self, message: str) -> None:
        logger.error("Audio: %s", message)
        if self._tray:
            self._tray.notify("KeySound — Audio Error", message)

    # ------------------------------------------------------------------
    # Tray actions
    # ------------------------------------------------------------------

    def _toggle_tracking(self) -> None:
        self._tracking_enabled = not self._tracking_enabled
        if self._tray:
            self._tray.set_tracking(self._tracking_enabled)
        if not self._tracking_enabled and self._buffer:
            self._buffer.clear()
        logger.info("Tracking %s", "enabled" if self._tracking_enabled else "paused")

    def _play_now(self) -> None:
        """Manually re-trigger playback for the current mood."""
        if self._playback is None:
            logger.warning("No playlists configured — open Settings first.")
            return
        current = self._state_manager.current_mood
        logger.info("Manual play: requesting playback for mood: %s", current.value)
        self._playback.play_for_mood(current.value)

    def _open_settings(self) -> None:
        # Guard: don't open a second window if one is already open.
        if self._settings_thread and self._settings_thread.is_alive():
            return
        def _run():
            win = SettingsWindow(
                config=self._config,
                on_save=self._on_settings_saved,
            )
            win.open()
        self._settings_thread = threading.Thread(target=_run, daemon=True)
        self._settings_thread.start()

    def _on_settings_saved(self, new_cfg: AppConfig) -> None:
        self._config = new_cfg
        # Update playlists in-place — do NOT recreate the controller.
        # Recreating would abandon the old VLC player still running, causing
        # two audio streams to play simultaneously.
        if self._playback:
            pl = new_cfg.playlists
            for mood_name, url in [
                ("flowing", pl.flowing), ("focused", pl.focused),
                ("struggling", pl.struggling), ("editing", pl.editing),
                ("reading", pl.reading), ("idle", pl.idle),
            ]:
                self._playback.set_playlist(mood_name, url or "")
        logger.info("Settings saved and applied.")

    def _quit(self) -> None:
        logger.info("Quitting KeySound…")
        if self._classifier_timer:
            self._classifier_timer.cancel()
        if self._listener:
            self._listener.stop()
        if self._mouse_listener:
            self._mouse_listener.stop()
        if self._tray:
            self._tray.stop()

def main() -> None:
    app = KeySoundApp()
    app.run()


if __name__ == "__main__":
    main()
