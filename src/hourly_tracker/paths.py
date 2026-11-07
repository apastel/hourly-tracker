"""Per-user data directory. Kept separate from the original HourlyTracker app."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "HourlyTrackerV2"


def app_data_dir() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    path = root / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def database_path() -> Path:
    return app_data_dir() / "hourly_tracker.db"
