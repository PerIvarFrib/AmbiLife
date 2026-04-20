"""
Config persistence: load/save AppConfig as JSON to %APPDATA%/KeySound/config.json.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
from pathlib import Path

from src.config.schema import AppConfig, DetectionConfig, PlaylistConfig

logger = logging.getLogger(__name__)

_APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "KeySound"
_CONFIG_PATH = _APP_DIR / "config.json"


def config_path() -> Path:
    return _CONFIG_PATH


def load() -> AppConfig:
    """Load config from disk; returns defaults if the file does not exist."""
    if not _CONFIG_PATH.exists():
        return AppConfig()
    try:
        raw = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        return _from_dict(raw)
    except Exception as exc:
        logger.warning("Failed to load config (%s); using defaults.", exc)
        return AppConfig()


def save(cfg: AppConfig) -> None:
    """Persist config to disk atomically."""
    _APP_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _CONFIG_PATH.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(_to_dict(cfg), indent=2), encoding="utf-8")
        tmp.replace(_CONFIG_PATH)
    except Exception as exc:
        logger.error("Failed to save config: %s", exc)
        if tmp.exists():
            tmp.unlink(missing_ok=True)


# ------------------------------------------------------------------
# Serialisation helpers
# ------------------------------------------------------------------

def _to_dict(cfg: AppConfig) -> dict:
    return dataclasses.asdict(cfg)


def _from_dict(raw: dict) -> AppConfig:
    def _get(d: dict, key: str, default):
        return d.get(key, default)

    pl_raw = raw.get("playlists", {})
    det_raw = raw.get("detection", {})

    playlists = PlaylistConfig(
        flowing=_get(pl_raw, "flowing", ""),
        focused=_get(pl_raw, "focused", ""),
        struggling=_get(pl_raw, "struggling", ""),
        idle=_get(pl_raw, "idle", ""),
    )

    default_det = DetectionConfig()
    detection = DetectionConfig(
        window_seconds=_get(det_raw, "window_seconds", default_det.window_seconds),
        classifier_interval_seconds=_get(det_raw, "classifier_interval_seconds", default_det.classifier_interval_seconds),
        debounce_seconds=_get(det_raw, "debounce_seconds", default_det.debounce_seconds),
        idle_timeout_seconds=_get(det_raw, "idle_timeout_seconds", default_det.idle_timeout_seconds),
        flowing_min_wpm=_get(det_raw, "flowing_min_wpm", default_det.flowing_min_wpm),
        flowing_max_backspace_rate=_get(det_raw, "flowing_max_backspace_rate", default_det.flowing_max_backspace_rate),
        flowing_max_pause_ratio=_get(det_raw, "flowing_max_pause_ratio", default_det.flowing_max_pause_ratio),
        struggling_min_backspace_rate=_get(det_raw, "struggling_min_backspace_rate", default_det.struggling_min_backspace_rate),
        struggling_min_burst_score=_get(det_raw, "struggling_min_burst_score", default_det.struggling_min_burst_score),
    )

    return AppConfig(
        playlists=playlists,
        detection=detection,
        tracking_enabled=raw.get("tracking_enabled", True),
    )
