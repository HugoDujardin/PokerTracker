"""Configuration de l'application (persistee en JSON).

Sur Windows 11 les donnees sont rangees dans %APPDATA%\\PokerTracker.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List

APP_NAME = "PokerTracker"


def app_dir() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Settings:
    db_path: str = ""
    hh_folders: List[str] = field(default_factory=list)
    auto_import: bool = True
    scan_interval: float = 1.0
    hud_enabled: bool = True
    hud_profile: str = "Cash 6-max"
    hud_opacity: float = 0.92
    hud_font_size: int = 11
    hud_follow_tables: bool = True
    hud_min_hands: int = 0
    hero_names: List[str] = field(default_factory=list)
    theme: str = "dark"
    language: str = "fr"
    default_currency: str = "EUR"
    seat_offsets: Dict[str, List[List[float]]] = field(default_factory=dict)
    popup_on_hover: bool = True
    show_hand_count: bool = True
    hud_scale: float = 1.0

    # ------------------------------------------------------------------
    @classmethod
    def path(cls) -> Path:
        return app_dir() / "config.json"

    @classmethod
    def load(cls) -> "Settings":
        p = cls.path()
        data: Dict[str, Any] = {}
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
        known = {f for f in cls.__dataclass_fields__}
        settings = cls(**{k: v for k, v in data.items() if k in known})
        if not settings.db_path:
            settings.db_path = str(app_dir() / "pokertracker.db")
        return settings

    def save(self) -> None:
        self.path().write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False),
                               encoding="utf-8")
