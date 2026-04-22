"""
Settings window built with customtkinter.

Two tabs:
  1. Playlists — one URI/URL entry per mood
  2. Detection  — sliders for WPM threshold, backspace rate, idle timeout, debounce
"""
from __future__ import annotations

import gc
from typing import Callable

import customtkinter as ctk

from src.config.schema import AppConfig, DetectionConfig
from src.config import settings as cfg_store

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

_LABEL_WIDTH = 200
_ENTRY_WIDTH = 340


class SettingsWindow:
    """
    Opens a customtkinter Toplevel settings window.
    Thread-safe: must be called from the main thread (or via after()).
    """

    def __init__(
        self,
        config: AppConfig,
        on_save: Callable[[AppConfig], None],
    ) -> None:
        self._config = config
        self._on_save = on_save
        self._win: ctk.CTk | None = None

    def open(self) -> None:
        """Create and show the window (blocking within its own event loop)."""
        self._win = ctk.CTk()
        self._win.title("KeySound — Settings")
        self._win.geometry("620x600")
        self._win.resizable(False, False)

        tabview = ctk.CTkTabview(self._win, width=600, height=420)
        tabview.pack(padx=10, pady=10)

        tab_playlists = tabview.add("Playlists")
        tab_detection = tabview.add("Detection")

        self._vars: dict = {}

        self._build_playlists_tab(tab_playlists)
        self._build_detection_tab(tab_detection)

        # Save / Cancel
        btn_frame = ctk.CTkFrame(self._win, fg_color="transparent")
        btn_frame.pack(pady=(0, 10))
        ctk.CTkButton(btn_frame, text="Save", width=120, command=self._save).pack(side="left", padx=8)
        ctk.CTkButton(btn_frame, text="Defaults", width=120, fg_color="gray30",
                      command=self._reset_defaults).pack(side="left", padx=8)
        ctk.CTkButton(btn_frame, text="Dev Mode", width=120, fg_color="#7B2D00",
                      command=self._set_dev_mode).pack(side="left", padx=8)
        ctk.CTkButton(btn_frame, text="Cancel", width=120, fg_color="gray40",
                      command=self._cancel).pack(side="left", padx=8)

        self._win.mainloop()

    # ------------------------------------------------------------------
    # Tab builders
    # ------------------------------------------------------------------

    def _build_playlists_tab(self, parent: ctk.CTkFrame) -> None:
        pl = self._config.playlists
        for mood_name, var_key, default in [
            ("Flowing (energising)", "playlist_flowing", pl.flowing),
            ("Focused (instrumental)", "playlist_focused", pl.focused),
            ("Struggling (calming)", "playlist_struggling", pl.struggling),
            ("Editing (focused edits)", "playlist_editing", pl.editing),
            ("Reading (ambient)", "playlist_reading", pl.reading),
            ("Idle (ambient/pause)", "playlist_idle", pl.idle),
        ]:
            self._vars[var_key] = ctk.StringVar(value=default)
            self._row(parent, f"{mood_name}:", self._vars[var_key],
                      placeholder="https://www.youtube.com/playlist?list=…")

        ctk.CTkLabel(parent,
                     text="Paste a YouTube playlist URL (e.g. https://www.youtube.com/playlist?list=…).",
                     text_color="gray60", wraplength=500).pack(anchor="w", padx=16, pady=(8, 0))

    def _build_detection_tab(self, parent: ctk.CTkFrame) -> None:
        det = self._config.detection

        def slider_row(label: str, key: str, from_: float, to: float, val: float, fmt: str = "{:.0f}"):
            frame = ctk.CTkFrame(parent, fg_color="transparent")
            frame.pack(fill="x", padx=16, pady=4)
            ctk.CTkLabel(frame, text=label, width=_LABEL_WIDTH, anchor="w").pack(side="left")
            var = ctk.DoubleVar(value=val)
            self._vars[key] = var
            lbl = ctk.CTkLabel(frame, text=fmt.format(val), width=50)
            lbl.pack(side="right")
            slider = ctk.CTkSlider(frame, from_=from_, to=to, variable=var,
                                   command=lambda v, l=lbl, f=fmt: l.configure(text=f.format(v)))
            slider.pack(side="left", expand=True, fill="x", padx=8)

        slider_row("Flowing min WPM:", "flowing_min_wpm", 10, 100, det.flowing_min_wpm)
        slider_row("Flowing max backspace %:", "flowing_max_backspace_rate", 0, 0.5,
                   det.flowing_max_backspace_rate, "{:.0%}")
        slider_row("Flowing max pause %:", "flowing_max_pause_ratio", 0, 1.0,
                   det.flowing_max_pause_ratio, "{:.0%}")
        slider_row("Struggling min backspace %:", "struggling_min_backspace_rate", 0, 0.5,
                   det.struggling_min_backspace_rate, "{:.0%}")
        slider_row("Editing min shortcut %:", "editing_min_shortcut_rate", 0, 0.5,
                   det.editing_min_shortcut_rate, "{:.0%}")
        slider_row("Editing min nav key %:", "editing_min_nav_rate", 0, 0.5,
                   det.editing_min_nav_rate, "{:.0%}")
        slider_row("Editing max WPM:", "editing_max_wpm", 1, 60, det.editing_max_wpm)
        slider_row("Reading max WPM:", "reading_max_wpm", 1, 20, det.reading_max_wpm)
        slider_row("Reading min scrolls/min:", "reading_min_scroll_rate", 0, 20,
                   det.reading_min_scroll_rate, "{:.1f}")
        slider_row("Idle timeout (seconds):", "idle_timeout_seconds", 30, 600,
                   det.idle_timeout_seconds)
        slider_row("Mood debounce (seconds):", "debounce_seconds", 5, 120,
                   det.debounce_seconds)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _row(self, parent, label: str, var: ctk.StringVar, placeholder: str = "") -> None:
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(frame, text=label, width=_LABEL_WIDTH, anchor="w").pack(side="left")
        ctk.CTkEntry(frame, textvariable=var, width=_ENTRY_WIDTH,
                     placeholder_text=placeholder).pack(side="left")

    def _save(self) -> None:
        v = self._vars
        cfg = self._config

        cfg.playlists.flowing = v["playlist_flowing"].get().strip()
        cfg.playlists.focused = v["playlist_focused"].get().strip()
        cfg.playlists.struggling = v["playlist_struggling"].get().strip()
        cfg.playlists.editing = v["playlist_editing"].get().strip()
        cfg.playlists.reading = v["playlist_reading"].get().strip()
        cfg.playlists.idle = v["playlist_idle"].get().strip()

        cfg.detection.flowing_min_wpm = float(v["flowing_min_wpm"].get())
        cfg.detection.flowing_max_backspace_rate = float(v["flowing_max_backspace_rate"].get())
        cfg.detection.flowing_max_pause_ratio = float(v["flowing_max_pause_ratio"].get())
        cfg.detection.struggling_min_backspace_rate = float(v["struggling_min_backspace_rate"].get())
        cfg.detection.editing_min_shortcut_rate = float(v["editing_min_shortcut_rate"].get())
        cfg.detection.editing_min_nav_rate = float(v["editing_min_nav_rate"].get())
        cfg.detection.editing_max_wpm = float(v["editing_max_wpm"].get())
        cfg.detection.reading_max_wpm = float(v["reading_max_wpm"].get())
        cfg.detection.reading_min_scroll_rate = float(v["reading_min_scroll_rate"].get())
        cfg.detection.idle_timeout_seconds = float(v["idle_timeout_seconds"].get())
        cfg.detection.debounce_seconds = float(v["debounce_seconds"].get())

        cfg_store.save(cfg)
        self._on_save(cfg)

        self._vars.clear()  # release StringVars/DoubleVars on this thread
        if self._win:
            self._win.destroy()
            self._win = None
        gc.collect()  # force cleanup of internal CTk/tkinter objects on this thread

    def _set_dev_mode(self) -> None:
        """Fast-response settings for testing — low debounce and idle timeout."""
        self._vars["flowing_min_wpm"].set(10.0)
        self._vars["flowing_max_backspace_rate"].set(0.5)
        self._vars["flowing_max_pause_ratio"].set(0.9)
        self._vars["struggling_min_backspace_rate"].set(0.5)
        self._vars["editing_min_shortcut_rate"].set(0.05)
        self._vars["editing_min_nav_rate"].set(0.05)
        self._vars["editing_max_wpm"].set(60.0)
        self._vars["reading_max_wpm"].set(10.0)
        self._vars["reading_min_scroll_rate"].set(1.0)
        self._vars["idle_timeout_seconds"].set(10.0)
        self._vars["debounce_seconds"].set(5.0)

    def _reset_defaults(self) -> None:
        d = DetectionConfig()
        self._vars["flowing_min_wpm"].set(d.flowing_min_wpm)
        self._vars["flowing_max_backspace_rate"].set(d.flowing_max_backspace_rate)
        self._vars["flowing_max_pause_ratio"].set(d.flowing_max_pause_ratio)
        self._vars["struggling_min_backspace_rate"].set(d.struggling_min_backspace_rate)
        self._vars["editing_min_shortcut_rate"].set(d.editing_min_shortcut_rate)
        self._vars["editing_min_nav_rate"].set(d.editing_min_nav_rate)
        self._vars["editing_max_wpm"].set(d.editing_max_wpm)
        self._vars["reading_max_wpm"].set(d.reading_max_wpm)
        self._vars["reading_min_scroll_rate"].set(d.reading_min_scroll_rate)
        self._vars["idle_timeout_seconds"].set(d.idle_timeout_seconds)
        self._vars["debounce_seconds"].set(d.debounce_seconds)

    def _cancel(self) -> None:
        self._vars.clear()  # release StringVars/DoubleVars on this thread
        if self._win:
            self._win.destroy()
            self._win = None
        gc.collect()  # force cleanup of internal CTk/tkinter objects on this thread
