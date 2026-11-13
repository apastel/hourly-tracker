"""Desktop window: workday summary and an editable away-time table."""

from __future__ import annotations

import datetime as dt
import logging
import os
import sqlite3
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from hourly_tracker import startup
from hourly_tracker.formatting import (
    format_clock,
    format_day,
    format_duration,
    format_editor,
    format_hms,
    format_start_field,
    format_stamp,
    parse_timestamp,
)
from hourly_tracker.idle import get_idle_seconds
from hourly_tracker.notifications import show_desktop_notification
from hourly_tracker.tracker import AwayRow, Tracker, TrackerError

STATUS_TEXT = {
    "working": "Working",
    "idle": "Idle",
    "complete": "Workday complete",
}
STATUS_STYLE = {
    "working": "Working.TLabel",
    "idle": "Idle.TLabel",
    "complete": "Complete.TLabel",
}
THEME_MODES = ("system", "light", "dark")
THEME_PALETTES = {
    "light": {
        "background": "#f0f0f0",
        "surface": "#ffffff",
        "foreground": "#202020",
        "subtle": "#5c6570",
        "field": "#ffffff",
        "border": "#a0a0a0",
        "selection": "#0078d7",
        "selection_text": "#ffffff",
        "idle_row": "#fff8ee",
        "offline_row": "#f3f7fb",
        "working": "#1b7f3a",
        "idle": "#b86e00",
        "complete": "#1a56c4",
    },
    "dark": {
        "background": "#1e1e1e",
        "surface": "#252526",
        "foreground": "#f1f1f1",
        "subtle": "#b8b8b8",
        "field": "#333333",
        "border": "#555555",
        "selection": "#264f78",
        "selection_text": "#ffffff",
        "idle_row": "#3b3024",
        "offline_row": "#26323d",
        "working": "#65c982",
        "idle": "#e6ad58",
        "complete": "#78a9f8",
    },
}


def _detect_system_theme() -> str:
    if sys.platform == "win32":
        try:
            import winreg

            key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                use_light_theme, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return "light" if use_light_theme else "dark"
        except (ImportError, OSError):
            logging.exception("Could not read the Windows appearance setting")
            return "light"

    if sys.platform == "darwin":
        value = _run_theme_command(
            ["defaults", "read", "-g", "AppleInterfaceStyle"],
        )
        return "dark" if value and value.lower() == "dark" else "light"

    if sys.platform.startswith("linux"):
        gtk_theme = os.environ.get("GTK_THEME")
        if gtk_theme:
            return "dark" if "dark" in gtk_theme.lower() else "light"
        color_scheme = _run_theme_command(
            ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
        )
        if color_scheme:
            if "prefer-dark" in color_scheme.lower():
                return "dark"
            if "prefer-light" in color_scheme.lower():
                return "light"
        gtk_theme = _run_theme_command(
            ["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"],
        )
        return "dark" if gtk_theme and "dark" in gtk_theme.lower() else "light"

    return "light"


def _run_theme_command(command: list[str]) -> str | None:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip().strip("\"'")


class HourlyTrackerApp:
    def __init__(
        self,
        root: tk.Tk,
        tracker: Tracker,
        idle_provider: Callable[[], float] | None = None,
        *,
        auto_poll: bool = True,
        poll_ms: int = 1000,
    ):
        self.root = root
        self.tracker = tracker
        self._idle_provider = idle_provider or get_idle_seconds
        self.poll_ms = poll_ms
        self._polling = auto_poll
        self._refreshing = True
        self._last_idle: float | None = None
        self._rows: list[AwayRow] = []
        self._idle_error_logged = False
        self._log_lines = 0
        self._tray = None
        self._settings_dialog: StartupSettingsDialog | None = None
        self._theme_preference = self._read_theme_preference()
        self._close_behavior = self._read_close_behavior()
        self._active_theme = "light"
        self._theme_poll_id: str | None = None
        self._notified_workday_day: dt.date | None = None
        self._next_workday_reminder: dt.datetime | None = None

        self.root.title("Hourly Tracker")
        self.root.minsize(760, 560)
        self.root.geometry("860x640")
        self._configure_style()
        self._build()
        self._apply_theme()
        self._theme_poll_id = self.root.after(30000, self._check_system_theme)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._start_tray)
        self._refreshing = False
        if auto_poll:
            self._schedule()
        else:
            self.refresh()

    def _configure_style(self) -> None:
        self._style = ttk.Style(self.root)
        if "clam" in self._style.theme_names():
            self._style.theme_use("clam")
        base = ("Segoe UI", 10)
        self._style.configure(".", font=base)
        self._style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"))
        self._style.configure("Metric.TLabel", font=("Segoe UI", 18, "bold"))
        self._style.configure("SecondaryMetric.TLabel", font=("Segoe UI", 14))
        self._style.configure(
            "TotalAwayCaption.TLabel",
            font=("Segoe UI", 10, "bold"),
        )
        for status in ("Working", "Idle", "Complete"):
            self._style.configure(
                f"{status}.TLabel",
                font=("Segoe UI", 16, "bold"),
            )

    def _read_theme_preference(self) -> str:
        preference = self.tracker.storage.get_setting("theme", "system")
        return preference if preference in THEME_MODES else "system"

    def _read_close_behavior(self) -> str:
        behavior = self.tracker.storage.get_setting("close_behavior", "tray")
        return behavior if behavior in ("tray", "quit") else "tray"

    def _apply_theme(self, active_theme: str | None = None) -> None:
        if active_theme is None:
            if self._theme_preference == "system":
                active_theme = _detect_system_theme()
            else:
                active_theme = self._theme_preference
        self._active_theme = active_theme

        palette = THEME_PALETTES[self._active_theme]
        if self._active_theme == "dark" and "clam" in self._style.theme_names():
            self._style.theme_use("clam")
        elif self._active_theme == "light" and "vista" in self._style.theme_names():
            self._style.theme_use("vista")
        elif "clam" in self._style.theme_names():
            self._style.theme_use("clam")

        self._style.configure(".", font=("Segoe UI", 10))
        self._style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"))
        self._style.configure("Metric.TLabel", font=("Segoe UI", 18, "bold"))
        self._style.configure(
            "SecondaryMetric.TLabel",
            font=("Segoe UI", 14),
            background=palette["background"],
            foreground=palette["foreground"],
        )
        self._style.configure(
            "TotalAwayCaption.TLabel",
            font=("Segoe UI", 10, "bold"),
            background=palette["background"],
            foreground=palette["foreground"],
        )
        self._style.configure(
            ".",
            background=palette["background"],
            foreground=palette["foreground"],
        )
        self._style.configure("TFrame", background=palette["background"])
        self._style.configure(
            "TLabel",
            background=palette["background"],
            foreground=palette["foreground"],
        )
        self._style.configure(
            "Subtle.TLabel",
            background=palette["background"],
            foreground=palette["subtle"],
        )
        for status, color in (
            ("Working", "working"),
            ("Idle", "idle"),
            ("Complete", "complete"),
        ):
            self._style.configure(
                f"{status}.TLabel",
                font=("Segoe UI", 16, "bold"),
                background=palette["background"],
                foreground=palette[color],
            )
        self._style.configure(
            "TButton",
            background=palette["surface"],
            foreground=palette["foreground"],
            bordercolor=palette["border"],
        )
        self._style.map(
            "TButton",
            background=[
                ("pressed", palette["border"]),
                ("active", palette["field"]),
            ],
            foreground=[("disabled", palette["subtle"])],
        )
        for widget_style in ("TEntry", "TSpinbox", "TCombobox"):
            self._style.configure(
                widget_style,
                fieldbackground=palette["field"],
                foreground=palette["foreground"],
                background=palette["surface"],
                bordercolor=palette["border"],
                insertcolor=palette["foreground"],
                arrowcolor=palette["foreground"],
            )
            self._style.map(
                widget_style,
                fieldbackground=[("readonly", palette["field"])],
                foreground=[("disabled", palette["subtle"])],
            )
        for widget_style in ("TCheckbutton", "TRadiobutton"):
            self._style.configure(
                widget_style,
                background=palette["background"],
                foreground=palette["foreground"],
            )
            self._style.map(
                widget_style,
                background=[("active", palette["background"])],
                foreground=[("disabled", palette["subtle"])],
            )
        self._style.configure(
            "Treeview",
            background=palette["field"],
            fieldbackground=palette["field"],
            foreground=palette["foreground"],
        )
        self._style.map(
            "Treeview",
            background=[("selected", palette["selection"])],
            foreground=[("selected", palette["selection_text"])],
        )
        self._style.configure(
            "Treeview.Heading",
            background=palette["surface"],
            foreground=palette["foreground"],
        )
        self.tree.tag_configure("idle", background=palette["idle_row"])
        self.tree.tag_configure("offline", background=palette["offline_row"])
        self.root.configure(background=palette["background"])
        self.log.configure(
            background=palette["field"],
            foreground=palette["foreground"],
            insertbackground=palette["foreground"],
            selectbackground=palette["selection"],
            selectforeground=palette["selection_text"],
            highlightbackground=palette["border"],
        )

    def _set_theme_preference(self, preference: str) -> bool:
        if preference not in THEME_MODES:
            raise ValueError(f"Unknown theme preference: {preference}")
        try:
            self.tracker.storage.set_setting("theme", preference)
        except sqlite3.Error as exc:
            logging.exception("Could not save appearance setting")
            messagebox.showerror(
                "Settings",
                f"Could not save the appearance setting:\n{exc}",
                parent=self.root,
            )
            return False
        self._theme_preference = preference
        self._apply_theme()
        return True

    def _set_close_behavior(self, behavior: str) -> bool:
        if behavior not in ("tray", "quit"):
            raise ValueError(f"Unknown close behavior: {behavior}")
        try:
            self.tracker.storage.set_setting("close_behavior", behavior)
        except sqlite3.Error as exc:
            logging.exception("Could not save close button setting")
            messagebox.showerror(
                "Settings",
                f"Could not save the close button setting:\n{exc}",
                parent=self.root,
            )
            return False
        self._close_behavior = behavior
        return True

    def _check_system_theme(self) -> None:
        if self._theme_preference == "system":
            theme = _detect_system_theme()
            if theme != self._active_theme:
                self._apply_theme(theme)
        self._theme_poll_id = self.root.after(30000, self._check_system_theme)

    def _build(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main = ttk.Frame(self.root, padding=16)
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(3, weight=2)
        main.rowconfigure(6, weight=1)

        header = ttk.Frame(main)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Hourly Tracker", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.day_var = tk.StringVar()
        ttk.Label(header, textvariable=self.day_var, style="Subtle.TLabel").grid(
            row=0, column=1, sticky="e"
        )
        ttk.Button(header, text="Settings", command=self._open_settings).grid(
            row=0, column=2, sticky="e", padx=(12, 0)
        )
        self.status_label = ttk.Label(header, text="Working", style="Working.TLabel")
        self.status_label.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.idle_now_var = tk.StringVar()
        ttk.Label(header, textvariable=self.idle_now_var, style="Subtle.TLabel").grid(
            row=1, column=1, sticky="e", pady=(4, 0)
        )

        summary_panel = ttk.Frame(main)
        summary_panel.grid(row=1, column=0, sticky="ew", pady=(16, 8))
        summary_panel.columnconfigure(0, weight=1)

        totals = ttk.Frame(summary_panel)
        totals.grid(row=0, column=0, sticky="ew")
        totals.columnconfigure(0, weight=1)
        self.start_var = tk.StringVar()
        self.worked_var = tk.StringVar(value="0m")
        self.remaining_var = tk.StringVar(value="0m")
        self.end_var = tk.StringVar(value="—")
        self.idle_var = tk.StringVar(value="0m")
        self.offline_var = tk.StringVar(value="0m")
        self.away_var = tk.StringVar(value="0m")
        primary = ttk.Frame(totals)
        primary.grid(row=0, column=0, sticky="ew")
        for column, (caption, variable) in enumerate(
            (
                ("Start", self.start_var),
                ("Projected end", self.end_var),
                ("Worked", self.worked_var),
                ("Remaining", self.remaining_var),
            )
        ):
            block = ttk.Frame(primary)
            block.grid(row=0, column=column, sticky="w", padx=(0, 22))
            ttk.Label(block, text=caption, style="Subtle.TLabel").grid(row=0, column=0, sticky="w")
            value = ttk.Label(block, textvariable=variable, style="Metric.TLabel")
            value.grid(row=1, column=0, sticky="w")
            if caption == "Start":
                self.start_label = value

        ttk.Separator(totals, orient="horizontal").grid(
            row=1,
            column=0,
            sticky="ew",
            pady=(4, 8),
        )
        away_totals = ttk.Frame(totals)
        away_totals.grid(row=2, column=0, sticky="ew")
        for column, (caption, variable, value_style) in enumerate(
            (
                ("Total Away", self.away_var, "Metric.TLabel"),
                ("Idle", self.idle_var, "SecondaryMetric.TLabel"),
                ("Offline", self.offline_var, "SecondaryMetric.TLabel"),
            )
        ):
            block = ttk.Frame(away_totals)
            block.grid(row=0, column=column, sticky="w", padx=(0, 22))
            label_style = (
                "TotalAwayCaption.TLabel"
                if caption == "Total Away"
                else "Subtle.TLabel"
            )
            ttk.Label(block, text=caption, style=label_style).grid(
                row=0, column=0, sticky="w"
            )
            ttk.Label(block, textvariable=variable, style=value_style).grid(
                row=1, column=0, sticky="w"
            )

        ttk.Separator(summary_panel, orient="vertical").grid(
            row=0,
            column=1,
            sticky="ns",
            padx=(12, 16),
        )
        settings = ttk.Frame(summary_panel)
        settings.grid(row=0, column=2, sticky="nsw")
        ttk.Label(
            settings,
            text="Workday length",
            style="Subtle.TLabel",
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        self.hours_var = tk.StringVar(value=f"{self.tracker.workday_hours():g}")
        self.hours_spin = ttk.Spinbox(
            settings,
            from_=0.5,
            to=24,
            increment=0.5,
            textvariable=self.hours_var,
            width=6,
            command=self._save_hours,
        )
        self.hours_spin.grid(row=1, column=0, sticky="w", pady=(2, 8), ipady=2)
        ttk.Label(settings, text="hours", style="Subtle.TLabel").grid(
            row=1, column=1, sticky="w", padx=(6, 0), pady=(2, 8)
        )
        self.hours_spin.bind("<FocusOut>", self._save_hours)
        self.hours_spin.bind("<Return>", self._save_hours)

        ttk.Label(
            settings,
            text="Away threshold",
            style="Subtle.TLabel",
        ).grid(row=2, column=0, columnspan=2, sticky="w")
        self.threshold_var = tk.StringVar(value=str(self.tracker.threshold_minutes()))
        self.threshold_spin = ttk.Spinbox(
            settings,
            from_=1,
            to=240,
            increment=1,
            textvariable=self.threshold_var,
            width=5,
            command=self._save_threshold,
        )
        self.threshold_spin.grid(row=3, column=0, sticky="w", pady=(2, 0), ipady=2)
        ttk.Label(settings, text="minutes", style="Subtle.TLabel").grid(
            row=3, column=1, sticky="w", padx=(6, 0), pady=(2, 0)
        )
        self.threshold_spin.bind("<FocusOut>", self._save_threshold)
        self.threshold_spin.bind("<Return>", self._save_threshold)

        table_header = ttk.Frame(main)
        table_header.grid(row=2, column=0, sticky="ew")
        ttk.Label(table_header, text="Away events", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            table_header,
            text="Extends day is the part after your start time. It pushes your finish later. Delete a row to count that time as worked.",
            style="Subtle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 6))

        columns = ("kind", "started", "ended", "duration", "counted")
        table = ttk.Frame(main)
        table.grid(row=3, column=0, sticky="nsew")
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            table,
            columns=columns,
            show="headings",
            selectmode="browse",
            height=8,
        )
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.table_scrollbar = ttk.Scrollbar(
            table,
            orient="vertical",
            command=self.tree.yview,
        )
        self.table_scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=self.table_scrollbar.set)
        headings = {
            "kind": ("Type", 90),
            "started": ("Started", 180),
            "ended": ("Ended", 180),
            "duration": ("Duration", 110),
            "counted": ("Extends day", 110),
        }
        for name, (label, width) in headings.items():
            anchor = "w" if name in ("started", "ended") else "center"
            self.tree.heading(name, text=label)
            self.tree.column(name, width=width, anchor=anchor, stretch=True)
        self.tree.tag_configure("idle", background="#fff8ee")
        self.tree.tag_configure("offline", background="#f3f7fb")
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._sync_buttons())
        self.tree.bind("<Double-1>", lambda _event: self._edit_selected())
        self.tree.bind("<Delete>", lambda _event: self._delete_selected())

        actions = ttk.Frame(main)
        actions.grid(row=4, column=0, sticky="w", pady=(8, 12))
        self.edit_button = ttk.Button(actions, text="Edit", command=self._edit_selected)
        self.edit_button.grid(row=0, column=0, padx=(0, 8))
        self.delete_button = ttk.Button(
            actions,
            text="Delete",
            command=self._delete_selected,
        )
        self.delete_button.grid(row=0, column=1)
        self._sync_buttons()

        self.activity_label = ttk.Label(
            main,
            text="Activity",
            style="Subtle.TLabel",
        )
        self.activity_label.grid(row=5, column=0, sticky="nw")
        self.log = tk.Text(main, height=6, wrap="word", state="disabled")
        self.log.grid(row=6, column=0, sticky="nsew", pady=(4, 0))
        self._log(
            "Idle is time away while the computer is on. "
            "Offline is sleep, shutdown, or this window being closed. "
            "Minimizing keeps tracking."
        )

    def _schedule(self) -> None:
        if not self._polling:
            return
        self._tick()
        self.root.after(self.poll_ms, self._schedule)

    def _open_settings(self) -> None:
        if self._settings_dialog is not None and self._settings_dialog.winfo_exists():
            self._settings_dialog.lift()
            return
        if startup.is_supported():
            try:
                enabled = startup.is_enabled()
            except OSError as exc:
                logging.exception("Could not read Windows startup setting")
                messagebox.showerror(
                    "Settings",
                    f"Could not read the Windows startup setting:\n{exc}",
                    parent=self.root,
                )
                return
        else:
            enabled = False
        self._settings_dialog = StartupSettingsDialog(
            self.root,
            enabled=enabled,
            theme=self._theme_preference,
            close_behavior=self._close_behavior,
            on_startup_change=self._set_startup_enabled,
            on_theme_change=self._set_theme_preference,
            on_close_behavior_change=self._set_close_behavior,
            windows_supported=startup.is_supported(),
        )

    def _set_startup_enabled(self, enabled: bool) -> None:
        try:
            startup.set_enabled(enabled)
        except (OSError, RuntimeError) as exc:
            logging.exception("Could not update Windows startup setting")
            messagebox.showerror(
                "Settings",
                f"Could not update the Windows startup setting:\n{exc}",
                parent=self.root,
            )
            raise

    def _start_tray(self) -> None:
        if self._tray is not None:
            return
        if not self.root.winfo_viewable():
            self.root.after(100, self._start_tray)
            return
        try:
            from hourly_tracker.tray import SystemTray

            self._tray = SystemTray(self.show_from_tray, self.quit_from_tray)
            self._tray.start()
        except Exception:
            logging.exception("System tray could not be started")

    def _minimize_to_tray(self) -> None:
        self.root.withdraw()
        self._start_tray()

    def show_from_tray(self) -> None:
        def show() -> None:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()

        self.root.after(0, show)

    def quit_from_tray(self) -> None:
        self.root.after(0, self._quit)

    def _tick(self) -> None:
        now = dt.datetime.now()
        try:
            idle = self._idle_provider()
        except Exception:
            logging.exception("Could not read system idle time")
            idle = None
            if not self._idle_error_logged:
                self._log("Couldn't read system idle time.")
                self._idle_error_logged = True
        else:
            self._idle_error_logged = False
        self._last_idle = idle
        try:
            messages = self.tracker.tick(now, idle)
        except Exception:
            logging.exception("Tracker tick failed")
            self._log("Tracker hit an error. Details are in the log file.")
            self.refresh()
            return
        for message in messages:
            self._log(message)
            if message.startswith("Workday complete"):
                self.root.bell()
        self.refresh()

    def refresh(self) -> None:
        self._refreshing = True
        try:
            now = dt.datetime.now()
            summary = self.tracker.summary(now)
            self._update_workday_notifications(now, summary)
            self._rows = self.tracker.rows(now)
            self.day_var.set(format_day(summary.day))
            self.status_label.configure(
                text=STATUS_TEXT[summary.status],
                style=STATUS_STYLE[summary.status],
            )
            if self._last_idle is None:
                idle_now = "Current idle unavailable"
            else:
                idle_now = (
                    f"Current idle {format_hms(self._last_idle)}"
                    f" · threshold {self.tracker.threshold_minutes()}m"
                )
            self.idle_now_var.set(idle_now)
            self.worked_var.set(format_duration(summary.worked))
            self.remaining_var.set(format_duration(summary.remaining))
            self.end_var.set(format_clock(summary.projected_end))
            self.idle_var.set(format_duration(summary.idle))
            self.offline_var.set(format_duration(summary.offline))
            self.away_var.set(format_duration(summary.away))
            self.start_var.set(format_start_field(summary.start, now.date()))
            focused_widget = self.root.tk.call("focus")
            if focused_widget != str(self.hours_spin):
                self.hours_var.set(f"{self.tracker.workday_hours():g}")
            if focused_widget != str(self.threshold_spin):
                self.threshold_var.set(str(self.tracker.threshold_minutes()))
            self._fill_tree()
        finally:
            self._refreshing = False

    def _update_workday_notifications(self, now: dt.datetime, summary) -> None:
        if now < summary.projected_end:
            return

        notification = (
            "Workday complete",
            f"Your workday was completed at {format_clock(summary.projected_end)}. "
            "Time to stop working.",
        )

        if self._notified_workday_day != summary.day:
            show_desktop_notification(*notification)
            self._notified_workday_day = summary.day
            self._next_workday_reminder = now + dt.timedelta(minutes=20)
            return

        if (
            self._next_workday_reminder is not None
            and now >= self._next_workday_reminder
        ):
            show_desktop_notification(*notification)
            while now >= self._next_workday_reminder:
                self._next_workday_reminder += dt.timedelta(minutes=20)

    def _fill_tree(self) -> None:
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for row in self._rows:
            ended = "ongoing" if row.ended_at is None else format_stamp(row.ended_at)
            self.tree.insert(
                "",
                "end",
                iid=str(row.id),
                values=(
                    row.kind.capitalize(),
                    format_stamp(row.started_at),
                    ended,
                    format_duration(row.duration),
                    format_duration(row.counted),
                ),
                tags=(row.kind,),
            )
        if selected and self.tree.exists(selected[0]):
            self.tree.selection_set(selected[0])
            self.tree.focus(selected[0])
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        state = "normal" if self.tree.selection() else "disabled"
        self.edit_button.configure(state=state)
        self.delete_button.configure(state=state)

    def _selected_row(self) -> AwayRow | None:
        selection = self.tree.selection()
        if not selection:
            return None
        try:
            event_id = int(selection[0])
        except ValueError:
            return None
        for row in self._rows:
            if row.id == event_id:
                return row
        return None

    def _save_hours(self, *_args) -> None:
        if self._refreshing:
            return
        text = self.hours_var.get().strip()
        if not text:
            return
        try:
            value = float(text)
            if value == self.tracker.workday_hours():
                return
            self.tracker.set_workday_hours(value)
        except (TrackerError, ValueError) as exc:
            messagebox.showerror("Hourly Tracker", str(exc), parent=self.root)
        self.refresh()

    def _save_threshold(self, *_args) -> None:
        if self._refreshing:
            return
        text = self.threshold_var.get().strip()
        if not text:
            return
        try:
            value = int(float(text))
            if value == self.tracker.threshold_minutes():
                return
            self.tracker.set_threshold_minutes(value)
        except (TrackerError, ValueError) as exc:
            messagebox.showerror("Hourly Tracker", str(exc), parent=self.root)
        self.refresh()

    def _edit_selected(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        dialog = EditAwayDialog(self.root, row, dt.datetime.now())
        self.root.wait_window(dialog)
        if dialog.result is None:
            return
        kind, started_at, ended_at = dialog.result
        try:
            self.tracker.update_event(
                row.id,
                kind=kind,
                started_at=started_at,
                ended_at=ended_at,
                now=dt.datetime.now(),
                idle_seconds=self._last_idle,
            )
        except TrackerError as exc:
            messagebox.showerror("Hourly Tracker", str(exc), parent=self.root)
            return
        self._log(f"Updated {kind} event.")
        self.refresh()

    def _delete_selected(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        counted = format_duration(row.counted)
        confirmed = messagebox.askyesno(
            "Delete away time",
            f"Delete this {row.kind} event ({counted} counted)?\n\n"
            "That time will be added back to your worked hours.",
            parent=self.root,
        )
        if not confirmed:
            return
        try:
            self.tracker.delete_event(row.id, dt.datetime.now(), self._last_idle)
        except TrackerError as exc:
            messagebox.showerror("Hourly Tracker", str(exc), parent=self.root)
            return
        self._log(f"Deleted {row.kind} event. {counted} returned to worked time.")
        self.refresh()

    def _log(self, message: str) -> None:
        stamp = format_clock(dt.datetime.now())
        self.log.configure(state="normal")
        self.log.insert("end", f"{stamp}  {message}\n")
        self._log_lines += 1
        if self._log_lines > 200:
            self.log.delete("1.0", "2.0")
            self._log_lines -= 1
        self.log.configure(state="disabled")
        self.log.see("end")

    def _on_close(self) -> None:
        if self._close_behavior == "tray" and self._tray is not None:
            self._minimize_to_tray()
            return
        self._quit()

    def _quit(self) -> None:
        self._polling = False
        if self._theme_poll_id is not None:
            self.root.after_cancel(self._theme_poll_id)
            self._theme_poll_id = None
        if self._tray is not None:
            self._tray.stop()
        try:
            self.tracker.shutdown(dt.datetime.now())
        except Exception:
            logging.exception("Shutdown failed")
        self.root.destroy()


class StartupSettingsDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        enabled: bool,
        theme: str,
        close_behavior: str,
        on_startup_change: Callable[[bool], None],
        on_theme_change: Callable[[str], bool],
        on_close_behavior_change: Callable[[str], bool],
        windows_supported: bool,
    ):
        super().__init__(parent)
        self.title("Settings")
        self.resizable(False, False)
        self.transient(parent)
        self.on_startup_change = on_startup_change
        self.on_theme_change = on_theme_change
        self.on_close_behavior_change = on_close_behavior_change
        self._saved_theme = theme
        self._saved_close_behavior = close_behavior
        self.startup_var = tk.BooleanVar(self, value=enabled)

        frame = ttk.Frame(self, padding=16)
        frame.grid(row=0, column=0, sticky="nsew")
        ttk.Label(frame, text="Settings", style="Title.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 12)
        )
        if windows_supported:
            ttk.Checkbutton(
                frame,
                text="Start Hourly Tracker when I sign in to Windows",
                variable=self.startup_var,
                command=self._save_startup,
            ).grid(row=1, column=0, sticky="w")
        else:
            ttk.Label(
                frame,
                text="Startup settings are only available on Windows.",
                style="Subtle.TLabel",
            ).grid(row=1, column=0, sticky="w")
        ttk.Label(frame, text="When I click the close button").grid(
            row=2, column=0, sticky="w", pady=(14, 4)
        )
        self.close_behavior_var = tk.StringVar(
            self,
            value=self._close_behavior_label(close_behavior),
        )
        close_behavior_picker = ttk.Combobox(
            frame,
            textvariable=self.close_behavior_var,
            values=("Minimize to tray", "Quit Hourly Tracker"),
            state="readonly",
            width=22,
        )
        close_behavior_picker.grid(row=3, column=0, sticky="w")
        close_behavior_picker.bind(
            "<<ComboboxSelected>>", self._save_close_behavior
        )
        ttk.Label(frame, text="Appearance").grid(
            row=4, column=0, sticky="w", pady=(14, 4)
        )
        self.theme_var = tk.StringVar(self, value=theme.capitalize())
        theme_picker = ttk.Combobox(
            frame,
            textvariable=self.theme_var,
            values=("System", "Light", "Dark"),
            state="readonly",
            width=18,
        )
        theme_picker.grid(row=5, column=0, sticky="w")
        theme_picker.bind("<<ComboboxSelected>>", self._save_theme)
        ttk.Button(frame, text="Close", command=self.destroy).grid(
            row=6, column=0, sticky="e", pady=(16, 0)
        )

    @staticmethod
    def _close_behavior_label(behavior: str) -> str:
        return "Minimize to tray" if behavior == "tray" else "Quit Hourly Tracker"

    def _save_startup(self) -> None:
        enabled = self.startup_var.get()
        try:
            self.on_startup_change(enabled)
        except (OSError, RuntimeError):
            self.startup_var.set(not enabled)

    def _save_theme(self, _event=None) -> None:
        preference = self.theme_var.get().lower()
        if self.on_theme_change(preference):
            self._saved_theme = preference
        else:
            self.theme_var.set(self._saved_theme.capitalize())

    def _save_close_behavior(self, _event=None) -> None:
        behavior = (
            "tray"
            if self.close_behavior_var.get() == "Minimize to tray"
            else "quit"
        )
        if self.on_close_behavior_change(behavior):
            self._saved_close_behavior = behavior
        else:
            self.close_behavior_var.set(
                self._close_behavior_label(self._saved_close_behavior)
            )


class EditAwayDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, row: AwayRow, now: dt.datetime):
        super().__init__(parent)
        self.row = row
        self.now = now.replace(microsecond=0)
        self.result: tuple[str, dt.datetime, dt.datetime | None] | None = None
        self.title("Edit away event")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        frame = ttk.Frame(self, padding=16)
        frame.grid(row=0, column=0, sticky="nsew")
        ttk.Label(frame, text="Type").grid(row=0, column=0, sticky="w")
        self.kind_var = tk.StringVar(value=row.kind.capitalize())
        kind = ttk.Combobox(
            frame,
            textvariable=self.kind_var,
            values=("Idle", "Offline"),
            state="readonly",
            width=22,
        )
        kind.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        ttk.Label(frame, text="Start (YYYY-MM-DD HH:MM:SS)").grid(row=2, column=0, sticky="w")
        self.start_var = tk.StringVar(value=format_editor(row.started_at))
        ttk.Entry(frame, textvariable=self.start_var, width=26).grid(
            row=3, column=0, sticky="ew", pady=(0, 10)
        )

        self.ongoing_var = tk.BooleanVar(value=row.ended_at is None)
        ongoing = ttk.Checkbutton(
            frame,
            text="Still ongoing",
            variable=self.ongoing_var,
            command=self._toggle_end,
        )
        if row.ended_at is None:
            ongoing.grid(row=4, column=0, sticky="w", pady=(0, 6))

        ttk.Label(frame, text="End (YYYY-MM-DD HH:MM:SS)").grid(row=5, column=0, sticky="w")
        end_value = row.ended_at or self.now
        self.end_var = tk.StringVar(value=format_editor(end_value))
        self.end_entry = ttk.Entry(frame, textvariable=self.end_var, width=26)
        self.end_entry.grid(row=6, column=0, sticky="ew", pady=(0, 12))

        buttons = ttk.Frame(frame)
        buttons.grid(row=7, column=0, sticky="e")
        ttk.Button(buttons, text="Cancel", command=self.destroy).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="Save", command=self._save).grid(row=0, column=1)
        self.bind("<Escape>", lambda _event: self.destroy())
        self.bind("<Return>", lambda _event: self._save())
        self._toggle_end()

    def _toggle_end(self) -> None:
        state = "disabled" if self.ongoing_var.get() else "normal"
        self.end_entry.configure(state=state)

    def _save(self) -> None:
        try:
            started_at = parse_timestamp(self.start_var.get())
            if self.ongoing_var.get() and self.row.ended_at is None:
                ended_at = None
            else:
                ended_at = parse_timestamp(self.end_var.get())
        except ValueError as exc:
            messagebox.showerror("Edit away event", str(exc), parent=self)
            return
        self.result = (self.kind_var.get().lower(), started_at, ended_at)
        self.destroy()
