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

    from hourly_tracker.app import (
        HourlyTrackerApp,
        StartupSettingsDialog,
        _detect_system_theme,
    )
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
    def test_start_time_is_shown_read_only(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        storage = Storage(Path(tmp.name) / "start.db")
        self.addCleanup(storage.close)
        tracker = Tracker(storage, login_time=lambda: dt.datetime.now())

        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.withdraw()
        app = HourlyTrackerApp(root, tracker, auto_poll=False)

        self.assertEqual(app.start_label.winfo_class(), "TLabel")
        self.assertTrue(app.start_var.get())
        self.assertFalse(hasattr(app, "start_entry"))
        self.assertFalse(hasattr(app, "_save_start"))

    def test_summary_orders_primary_metrics_and_emphasizes_total_away(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        storage = Storage(Path(tmp.name) / "summary.db")
        self.addCleanup(storage.close)
        tracker = Tracker(storage, login_time=lambda: dt.datetime.now())

        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.withdraw()
        app = HourlyTrackerApp(root, tracker, auto_poll=False)

        primary = app.start_label.master.master
        self.assertEqual(
            [block.winfo_children()[0].cget("text") for block in primary.winfo_children()],
            ["Start", "Projected end", "Worked", "Remaining"],
        )
        totals = primary.master
        separator = next(
            child
            for child in totals.winfo_children()
            if child.winfo_class() == "TSeparator"
        )
        self.assertEqual(int(separator.grid_info()["row"]), 1)
        away = next(
            child
            for child in totals.winfo_children()
            if child.winfo_class() == "TFrame"
            and int(child.grid_info()["row"]) == 2
        )
        away_blocks = away.winfo_children()
        self.assertEqual(
            [block.winfo_children()[0].cget("text") for block in away_blocks],
            ["Total Away", "Idle", "Offline"],
        )
        self.assertEqual(
            away_blocks[0].winfo_children()[1].cget("style"),
            "Metric.TLabel",
        )
        self.assertEqual(
            away_blocks[1].winfo_children()[1].cget("style"),
            "SecondaryMetric.TLabel",
        )
        summary_panel = totals.master
        vertical_separator = next(
            child
            for child in summary_panel.winfo_children()
            if child.winfo_class() == "TSeparator"
        )
        self.assertEqual(str(vertical_separator.cget("orient")), "vertical")
        self.assertEqual(int(vertical_separator.grid_info()["column"]), 1)
        self.assertIs(app.hours_spin.master.master, summary_panel)
        self.assertEqual(int(app.hours_spin.master.grid_info()["column"]), 2)
        self.assertEqual(int(app.log.cget("height")), 6)
        self.assertEqual(int(app.log.master.grid_rowconfigure(3)["weight"]), 2)
        self.assertEqual(int(app.log.master.grid_rowconfigure(6)["weight"]), 1)
        self.assertEqual(int(app.tree.cget("height")), 8)
        self.assertEqual(int(app.tree.grid_info()["row"]), 0)
        self.assertEqual(int(app.table_scrollbar.grid_info()["column"]), 1)
        self.assertTrue(app.tree.cget("yscrollcommand"))
        self.assertTrue(app.table_scrollbar.cget("command"))
        self.assertEqual(int(app.activity_label.grid_info()["row"]), 5)
        self.assertEqual(int(app.log.grid_info()["row"]), 6)

    def test_windows_system_theme_uses_apps_appearance_setting(self):
        key = mock.MagicMock()
        open_key = mock.MagicMock()
        open_key.__enter__.return_value = key
        winreg = SimpleNamespace(
            HKEY_CURRENT_USER=object(),
            OpenKey=mock.Mock(return_value=open_key),
            QueryValueEx=mock.Mock(return_value=(0, 4)),
        )
        with (
            mock.patch("hourly_tracker.app.sys.platform", "win32"),
            mock.patch.dict(sys.modules, {"winreg": winreg}),
        ):
            self.assertEqual(_detect_system_theme(), "dark")
        winreg.OpenKey.assert_called_once()
        winreg.QueryValueEx.assert_called_once_with(key, "AppsUseLightTheme")

    def test_dark_theme_uses_light_control_arrows(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        storage = Storage(Path(tmp.name) / "arrows.db")
        self.addCleanup(storage.close)
        tracker = Tracker(storage, login_time=lambda: dt.datetime.now())

        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.withdraw()
        app = HourlyTrackerApp(root, tracker, auto_poll=False)

        app._apply_theme("dark")

        self.assertEqual(app._style.lookup("TSpinbox", "arrowcolor"), "#f1f1f1")
        self.assertEqual(app._style.lookup("TCombobox", "arrowcolor"), "#f1f1f1")

    def test_appearance_setting_defaults_to_system_and_updates_live(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        storage = Storage(Path(tmp.name) / "appearance.db")
        self.addCleanup(storage.close)
        tracker = Tracker(storage, login_time=lambda: dt.datetime.now())

        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.withdraw()
        with (
            mock.patch("hourly_tracker.app._detect_system_theme", return_value="dark"),
            mock.patch("hourly_tracker.app.startup.is_supported", return_value=False),
        ):
            app = HourlyTrackerApp(root, tracker, auto_poll=False)
            self.assertEqual(storage.get_setting("theme"), None)
            self.assertEqual(app._theme_preference, "system")
            self.assertEqual(app._active_theme, "dark")

            app._open_settings()
            self.assertEqual(app._settings_dialog.theme_var.get(), "System")
            app._settings_dialog.theme_var.set("Light")
            app._settings_dialog._save_theme()
            self.assertEqual(storage.get_setting("theme"), "light")
            self.assertEqual(app._active_theme, "light")

            app._settings_dialog.theme_var.set("System")
            app._settings_dialog._save_theme()
            self.assertEqual(storage.get_setting("theme"), "system")
            self.assertEqual(app._active_theme, "dark")
            app._settings_dialog.destroy()

    def test_refresh_does_not_resolve_nonstandard_tk_focus_as_widget(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        storage = Storage(Path(tmp.name) / "focus.db")
        self.addCleanup(storage.close)
        tracker = Tracker(storage, login_time=lambda: dt.datetime.now())

        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.withdraw()
        app = HourlyTrackerApp(root, tracker, auto_poll=False)

        with mock.patch.object(
            root,
            "focus_get",
            side_effect=KeyError("popdown"),
        ):
            app.refresh()

    def test_settings_window_saves_windows_startup_preference(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        storage = Storage(Path(tmp.name) / "settings.db")
        self.addCleanup(storage.close)
        tracker = Tracker(storage, login_time=lambda: dt.datetime.now())

        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.withdraw()
        app = HourlyTrackerApp(root, tracker, auto_poll=False)

        with (
            mock.patch("hourly_tracker.app.startup.is_supported", return_value=True),
            mock.patch("hourly_tracker.app.startup.is_enabled", return_value=False),
            mock.patch("hourly_tracker.app.startup.set_enabled") as set_enabled,
        ):
            app._open_settings()
            self.assertIsInstance(app._settings_dialog, StartupSettingsDialog)
            app._settings_dialog.startup_var.set(True)
            app._settings_dialog._save_startup()

        set_enabled.assert_called_once_with(True)
        app._settings_dialog.destroy()

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
