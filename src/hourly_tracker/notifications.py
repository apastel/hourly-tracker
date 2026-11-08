"""Windows desktop notifications for workday reminders."""

from __future__ import annotations

import logging
import sys


def show_desktop_notification(title: str, message: str) -> bool:
    if sys.platform != "win32":
        return False

    try:
        from winotify import Notification

        notification = Notification(
            app_id="Hourly Tracker",
            title=title,
            msg=message,
        )
        notification.show()
        return True
    except Exception:
        logging.exception("Desktop notification could not be shown")
        return False
