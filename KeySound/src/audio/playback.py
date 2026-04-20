"""
Audio playback controller using yt-dlp + python-vlc.

yt-dlp extracts a direct audio stream URL from any YouTube playlist or video.
python-vlc plays that URL via libvlc — no browser, no account needed.

Requirements:
  pip install yt-dlp python-vlc
  VLC media player installed: https://www.videolan.org/vlc/
"""
from __future__ import annotations

import logging
import random
import threading
import time
from typing import Callable, Optional

_FADE_STEPS = 30
_FADE_OUT_DURATION = 1.0   # seconds
_FADE_TO_SILENCE_DURATION = 30.0  # seconds — fade to silence on idle
_FADE_IN_DURATION = 3.0    # seconds

logger = logging.getLogger(__name__)

try:
    import vlc as _vlc
    _VLC_INSTANCE = _vlc.Instance("--no-video", "--quiet", "--no-osd")
    _VLC_AVAILABLE = True
except Exception as _e:
    _VLC_INSTANCE = None
    _VLC_AVAILABLE = False
    logger.warning("VLC not available (%s). Install from https://www.videolan.org/vlc/", _e)

try:
    import yt_dlp as _yt_dlp
    _YTDLP_AVAILABLE = True
except ImportError:
    _YTDLP_AVAILABLE = False
    logger.warning("yt-dlp not installed. Run: pip install yt-dlp")


class PlaybackController:
    """
    Maps mood names to YouTube playlist/video URLs and controls playback.
    Stream URL extraction runs in a background thread so mood changes
    return immediately; audio starts a few seconds later.
    """

    def __init__(self, on_error: Optional[Callable[[str], None]] = None) -> None:
        self._on_error = on_error
        self._playlist_map: dict[str, str] = {}
        self._current_mood: Optional[str] = None
        self._paused_by_idle: bool = False
        self._load_version: int = 0

        if _VLC_AVAILABLE:
            self._player = _VLC_INSTANCE.media_player_new()
            em = self._player.event_manager()
            em.event_attach(_vlc.EventType.MediaPlayerEndReached, self._on_track_end)
        else:
            self._player = None
        self._play_lock = threading.Lock()  # serialises stop→start transitions

    def set_playlist(self, mood_name: str, url: str) -> None:
        self._playlist_map[mood_name.lower()] = url.strip()
        logger.info("Playlist for '%s': %s", mood_name, url.strip())

    def play_for_mood(self, mood_name: str) -> None:
        key = mood_name.lower()
        logger.info("play_for_mood: %s  (vlc=%s  yt-dlp=%s)", mood_name, _VLC_AVAILABLE, _YTDLP_AVAILABLE)
        url = self._playlist_map.get(key, "")
        if key == "idle" and not url:
            self._paused_by_idle = True
            self._load_version += 1  # cancel any in-flight load or fade-in
            threading.Thread(target=self._fade_to_silence, daemon=True).start()
            return
        self._paused_by_idle = False
        self._current_mood = key
        if not url:
            logger.warning("No playlist configured for mood '%s' — add a YouTube URL in Settings.", mood_name)
            return
        self._load_version += 1
        version = self._load_version
        threading.Thread(target=self._load_and_play, args=(url, version), daemon=True).start()

    def pause(self) -> None:
        self._paused_by_idle = False
        self._do_pause()

    def resume(self) -> None:
        self._paused_by_idle = False
        if not _VLC_AVAILABLE or not self._player:
            return
        if self._player.get_state() == _vlc.State.Paused:
            self._player.pause()  # toggle back to playing
        elif self._current_mood:
            self.play_for_mood(self._current_mood)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _do_pause(self) -> None:
        if _VLC_AVAILABLE and self._player and self._player.is_playing():
            self._player.pause()

    def _on_track_end(self, event) -> None:
        if self._current_mood and not self._paused_by_idle:
            url = self._playlist_map.get(self._current_mood)
            if url:
                self._load_version += 1
                version = self._load_version
                threading.Thread(
                    target=self._load_and_play, args=(url, version), daemon=True
                ).start()

    def _load_and_play(self, playlist_url: str, version: int) -> None:
        if not _VLC_AVAILABLE or not _YTDLP_AVAILABLE:
            logger.error("Cannot play: VLC available=%s  yt-dlp available=%s", _VLC_AVAILABLE, _YTDLP_AVAILABLE)
            return
        logger.info("Extracting stream URL from: %s", playlist_url[:80])
        stream_url = self._extract_stream_url(playlist_url)
        if stream_url is None:
            logger.warning("Stream URL extraction failed (None returned) for: %s", playlist_url[:80])
            return
        if self._load_version != version:
            logger.debug("Load superseded after extraction; discarding.")
            return

        # Lock ensures only one thread runs stop→start at a time,
        # preventing two tracks from playing simultaneously.
        with self._play_lock:
            if self._load_version != version:
                logger.debug("Load superseded inside lock; discarding.")
                return
            logger.info("Playing stream…")
            self._fade_out_and_stop()
            media = _VLC_INSTANCE.media_new(stream_url)
            self._player.set_media(media)
            self._player.audio_set_volume(0)
            self._player.play()

        # Volume is 0; wait for VLC to actually start outputting audio
        # before fading in — play() is async and buffers for several seconds.
        self._wait_for_playing()
        self._fade_in(version)

    def _wait_for_playing(self, timeout: float = 20.0) -> None:
        """Block until VLC enters the Playing state or timeout elapses."""
        if not _VLC_AVAILABLE or not self._player:
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self._player.get_state()
            if state == _vlc.State.Playing:
                return
            if state in (_vlc.State.Error, _vlc.State.Ended, _vlc.State.Stopped):
                return
            time.sleep(0.05)

    def _fade_to_silence(self) -> None:
        """Acquire the play lock then fade out and stop — used for idle transitions."""
        with self._play_lock:
            self._fade_out_and_stop(duration=_FADE_TO_SILENCE_DURATION)

    def _fade_out_and_stop(self, duration: float = _FADE_OUT_DURATION) -> None:
        """Fade out if playing, then unconditionally stop. Call while holding _play_lock."""
        if not _VLC_AVAILABLE or not self._player:
            return
        if self._player.is_playing():
            vol = self._player.audio_get_volume()
            interval = duration / _FADE_STEPS
            for i in range(1, _FADE_STEPS + 1):
                self._player.audio_set_volume(max(0, vol - int(vol * i / _FADE_STEPS)))
                time.sleep(interval)
        self._player.stop()
        self._player.audio_set_volume(100)  # restore for next track

    def _fade_in(self, version: int) -> None:
        """Fade from 0 to 100, aborting early if a newer load has been requested."""
        if not _VLC_AVAILABLE or not self._player:
            return
        interval = _FADE_IN_DURATION / _FADE_STEPS
        for i in range(1, _FADE_STEPS + 1):
            if self._load_version != version:
                self._player.audio_set_volume(100)  # let the new track take over cleanly
                return
            self._player.audio_set_volume(min(100, int(100 * i / _FADE_STEPS)))
            time.sleep(interval)

    def _extract_stream_url(self, playlist_url: str) -> Optional[str]:
        """
        1. Flat-extract up to 20 playlist entries to get video IDs quickly.
        2. Pick one at random.
        3. Extract the direct audio stream URL for that video.
        """
        try:
            flat_opts = {
                "extract_flat": "in_playlist",
                "quiet": True,
                "no_warnings": True,
                "playlist_items": "1-20",
            }
            with _yt_dlp.YoutubeDL(flat_opts) as ydl:
                info = ydl.extract_info(playlist_url, download=False)

            if not info:
                return None

            entries = [e for e in info.get("entries", []) if e]
            if entries:
                entry = random.choice(entries)
                video_url = entry.get("url") or f"https://www.youtube.com/watch?v={entry['id']}"
            else:
                video_url = playlist_url  # single video URL passed directly

            stream_opts = {
                "format": "bestaudio[ext=webm]/bestaudio/best",
                "quiet": True,
                "no_warnings": True,
            }
            with _yt_dlp.YoutubeDL(stream_opts) as ydl:
                info = ydl.extract_info(video_url, download=False)
                return info.get("url") if info else None

        except Exception as exc:
            logger.error("yt-dlp extraction failed: %s", exc)
            if self._on_error:
                self._on_error(f"Could not load music: {exc}")
            return None

