"""The away table lists tracker events and delete puts that time back."""

from __future__ import annotations

import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    import tkinter as tk

    from hourly_tracker.app import HourlyTrackerApp
except Exception as exc:  # pragma: no cover - depends on the local Python build
    tk = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None

from hourly_tracker.formatting import format_clock
from hourly_tracker.storage import Storage
from hourly_tracker.tracker import Tracker


@unittest.skipIf(tk is None, f"tkinter unavailable: {IMPORT_ERROR}")
class AwayTableTest(unittest.TestCase):
    def test_workday_notifications_repeat_every_fifteen_minutes(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        storage = Storage(Path(tmp.name) / "notifications.db")
        self.addCleanup(storage.close)
        start = dt.datetime.now().replace(microsecond=0) - dt.timedelta(hours=10)
        tracker = Tracker(storage, login_time=lambda: start)

        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.attributes("-alpha", 0)
        root.withdraw()
        app = HourlyTrackerApp(
            root,
            tracker,
            idle_provider=lambda: 0.0,
            auto_poll=False,
        )
        now = dt.datetime.now().replace(microsecond=0)
        summary = SimpleNamespace(
            day=now.date(),
            projected_end=now - dt.timedelta(hours=1),
        )
        app._notified_workday_day = None
        app._next_workday_reminder = None

        with mock.patch("hourly_tracker.app.show_desktop_notification") as notify:
            app._update_workday_notifications(now, summary)
            app._update_workday_notifications(now + dt.timedelta(minutes=19), summary)
            self.assertEqual(notify.call_count, 1)
            app._update_workday_notifications(now + dt.timedelta(minutes=20), summary)
            app._update_workday_notifications(now + dt.timedelta(minutes=40), summary)

        self.assertEqual(notify.call_count, 3)
        completed_at = format_clock(summary.projected_end)
        expected_text = (
            "Workday complete",
            f"Your workday was completed at {completed_at}. "
            "Time to stop working.",
        )
        for call in notify.call_args_list:
            self.assertEqual(call.args, expected_text)

    def test_table_lists_idle_and_delete_returns_it_to_worked_time(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        storage = Storage(Path(tmp.name) / "ui.db")
        self.addCleanup(storage.close)
        now = dt.datetime.now().replace(microsecond=0)
        anchor = (now - dt.timedelta(minutes=20)).replace(second=0, microsecond=0)
        tracker = Tracker(storage, login_time=lambda: anchor)
        tracker.set_threshold_minutes(1)
        tracker.tick(anchor, 0)
        tracker.tick(anchor + dt.timedelta(seconds=30), 30)
        tracker.tick(anchor + dt.timedelta(seconds=60), 60)
        tracker.tick(anchor + dt.timedelta(seconds=70), 0)
        self.assertEqual(len(tracker.rows(now)), 1)

        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.attributes("-alpha", 0)
        root.withdraw()
        app = HourlyTrackerApp(
            root,
            tracker,
            idle_provider=lambda: 0.0,
            auto_poll=False,
        )
        root.withdraw()
        root.update_idletasks()

        children = app.tree.get_children()
        self.assertEqual(len(children), 1)
        self.assertEqual(app.tree.item(children[0], "values")[0], "Idle")
        before = tracker.summary(dt.datetime.now())
        self.assertGreater(before.away, dt.timedelta(0))
        worked_before = app.worked_var.get()

        app.tree.selection_set(children[0])
        app._sync_buttons()
        self.assertEqual(str(app.delete_button.cget("state")), "normal")
        with mock.patch("hourly_tracker.app.messagebox.askyesno", return_value=True):
            app.delete_button.invoke()
        root.update_idletasks()

        self.assertEqual(app.tree.get_children(), ())
        after = tracker.summary(dt.datetime.now())
        self.assertEqual(after.away, dt.timedelta(0))
        self.assertGreater(after.worked, before.worked)
        self.assertLess(after.projected_end, before.projected_end)
        self.assertNotEqual(app.worked_var.get(), worked_before)
        root.withdraw()
