"""
Mood state manager with debounce logic.

A mood change is only committed after the candidate mood has been
consistently classified for `debounce_seconds` (default 30 s).
This prevents rapid playlist switching during brief fluctuations.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

from src.mood.classifier import Mood


class MoodStateManager:
    """
    Tracks current mood, applies debounce, and fires on_mood_change callbacks.

    Usage:
        manager = MoodStateManager(on_mood_change=my_callback)
        # Call manager.update(new_mood) from the periodic classifier timer.
    """

    def __init__(
        self,
        on_mood_change: Callable[[Mood, Mood], None] | None = None,
        debounce_seconds: float = 30.0,
        initial_mood: Mood = Mood.IDLE,
    ) -> None:
        self._on_mood_change = on_mood_change
        self._debounce = debounce_seconds
        self._current_mood: Mood = initial_mood
        self._candidate_mood: Mood = initial_mood
        self._candidate_since: float = time.monotonic()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def current_mood(self) -> Mood:
        with self._lock:
            return self._current_mood

    def update(self, new_mood: Mood) -> None:
        """
        Call this each time the classifier produces a new label.
        The change is committed only after debounce_seconds of stable signal.
        """
        with self._lock:
            now = time.monotonic()

            if new_mood != self._candidate_mood:
                # Candidate reset: restart debounce timer
                self._candidate_mood = new_mood
                self._candidate_since = now
                return

            # Same candidate sustained long enough?
            if now - self._candidate_since >= self._debounce:
                if new_mood != self._current_mood:
                    old_mood = self._current_mood
                    self._current_mood = new_mood
                    callback = self._on_mood_change
                else:
                    callback = None
            else:
                callback = None

        # Fire callback outside the lock to avoid potential deadlock
        if callback is not None:
            try:
                callback(old_mood, new_mood)
            except Exception:
                pass

    def force_mood(self, mood: Mood) -> None:
        """Bypass debounce — used when the user manually overrides the mood."""
        with self._lock:
            old_mood = self._current_mood
            self._current_mood = mood
            self._candidate_mood = mood
            self._candidate_since = time.monotonic()
            callback = self._on_mood_change if mood != old_mood else None

        if callback is not None:
            try:
                callback(old_mood, mood)
            except Exception:
                pass
