"""Launch the Hourly Tracker window."""

from __future__ import annotations

import datetime as dt
import logging
import sys
import tkinter as tk

from hourly_tracker.idle import get_idle_seconds
from hourly_tracker.login_time import get_login_time
from hourly_tracker.paths import app_data_dir, database_path
from hourly_tracker.storage import Storage
from hourly_tracker.tracker import Tracker


def main() -> None:
    _configure_logging()
    storage = Storage(database_path())
    tracker = Tracker(storage, login_time=get_login_time)
    root = tk.Tk()
    from hourly_tracker.app import HourlyTrackerApp

    HourlyTrackerApp(root, tracker, idle_provider=get_idle_seconds)
    try:
        root.mainloop()
    finally:
        storage.close()


def _configure_logging() -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    try:
        log_dir = app_data_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        filename = log_dir / f"hourly-tracker_{dt.date.today():%Y-%m-%d}.log"
        handlers.insert(0, logging.FileHandler(filename, encoding="utf-8"))
    except OSError:
        pass
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )


if __name__ == "__main__":
    main()
