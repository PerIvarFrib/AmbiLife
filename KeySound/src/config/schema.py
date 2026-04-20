"""
Configuration schema — dataclasses representing persisted app settings.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PlaylistConfig:
    flowing: str = ""
    focused: str = ""
    struggling: str = ""
    idle: str = ""


@dataclass
class DetectionConfig:
    window_seconds: float = 120.0
    classifier_interval_seconds: float = 10.0
    debounce_seconds: float = 30.0
    idle_timeout_seconds: float = 180.0
    # Classifier thresholds
    flowing_min_wpm: float = 40.0
    flowing_max_backspace_rate: float = 0.08
    flowing_max_pause_ratio: float = 0.30
    struggling_min_backspace_rate: float = 0.15
    struggling_min_burst_score: float = 0.70


@dataclass
class AppConfig:
    playlists: PlaylistConfig = field(default_factory=PlaylistConfig)
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    tracking_enabled: bool = True
