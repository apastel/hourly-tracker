"""Desktop window: workday summary and an editable away-time table."""

from __future__ import annotations

import datetime as dt
import logging
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from hourly_tracker.formatting import (
    format_clock,
    format_day,
    format_duration,
    format_editor,
    format_hms,
    format_stamp,
    format_start_field,
    parse_start,
    parse_timestamp,
)
from hourly_tracker.idle import get_idle_seconds
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
        self._hiding_to_tray = False

        self.root.title("Hourly Tracker")
        self.root.minsize(760, 560)
        self.root.geometry("860x640")
        self._configure_style()
        self._build()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<Unmap>", self._on_unmap)
        self.root.after(100, self._start_tray)
        self._refreshing = False
        if auto_poll:
            self._schedule()
        else:
            self.refresh()

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
        base = ("Segoe UI", 10)
        style.configure(".", font=base)
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure("Subtle.TLabel", foreground="#5c6570")
        style.configure("Metric.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure(
            "Working.TLabel",
            foreground="#1b7f3a",
            font=("Segoe UI", 16, "bold"),
        )
        style.configure(
            "Idle.TLabel",
            foreground="#b86e00",
            font=("Segoe UI", 16, "bold"),
        )
        style.configure(
            "Complete.TLabel",
            foreground="#1a56c4",
            font=("Segoe UI", 16, "bold"),
        )

    def _build(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main = ttk.Frame(self.root, padding=16)
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(4, weight=1)
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
        self.status_label = ttk.Label(header, text="Working", style="Working.TLabel")
        self.status_label.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.idle_now_var = tk.StringVar()
        ttk.Label(header, textvariable=self.idle_now_var, style="Subtle.TLabel").grid(
            row=1, column=1, sticky="e", pady=(4, 0)
        )

        totals = ttk.Frame(main)
        totals.grid(row=1, column=0, sticky="ew", pady=(16, 8))
        self.worked_var = tk.StringVar(value="0m")
        self.remaining_var = tk.StringVar(value="0m")
        self.end_var = tk.StringVar(value="—")
        self.idle_var = tk.StringVar(value="0m")
        self.offline_var = tk.StringVar(value="0m")
        self.away_var = tk.StringVar(value="0m")
        for column, (caption, variable) in enumerate(
            (
                ("Worked", self.worked_var),
                ("Remaining", self.remaining_var),
                ("Projected end", self.end_var),
                ("Idle", self.idle_var),
                ("Offline", self.offline_var),
                ("Away", self.away_var),
            )
        ):
            block = ttk.Frame(totals)
            block.grid(row=0, column=column, sticky="w", padx=(0, 22))
            ttk.Label(block, text=caption, style="Subtle.TLabel").grid(row=0, column=0, sticky="w")
            ttk.Label(block, textvariable=variable, style="Metric.TLabel").grid(
                row=1, column=0, sticky="w"
            )

        settings = ttk.Frame(main)
        settings.grid(row=2, column=0, sticky="w", pady=(8, 12))
        ttk.Label(settings, text="Start").grid(row=0, column=0, padx=(0, 6))
        self.start_var = tk.StringVar()
        self.start_entry = ttk.Entry(settings, textvariable=self.start_var, width=18)
        self.start_entry.grid(row=0, column=1, padx=(0, 16))
        self.start_entry.bind("<FocusOut>", self._save_start)
        self.start_entry.bind("<Return>", self._save_start)

        ttk.Label(settings, text="Workday").grid(row=0, column=2, padx=(0, 6))
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
        self.hours_spin.grid(row=0, column=3, padx=(0, 6))
        ttk.Label(settings, text="hours").grid(row=0, column=4, padx=(0, 16))
        self.hours_spin.bind("<FocusOut>", self._save_hours)
        self.hours_spin.bind("<Return>", self._save_hours)

        ttk.Label(settings, text="Away after").grid(row=0, column=5, padx=(0, 6))
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
        self.threshold_spin.grid(row=0, column=6, padx=(0, 6))
        ttk.Label(settings, text="minutes").grid(row=0, column=7)
        self.threshold_spin.bind("<FocusOut>", self._save_threshold)
        self.threshold_spin.bind("<Return>", self._save_threshold)

        table_header = ttk.Frame(main)
        table_header.grid(row=3, column=0, sticky="ew")
        ttk.Label(table_header, text="Away events", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            table_header,
            text="Extends day is the part after your start time. It pushes your finish later. Delete a row to count that time as worked.",
            style="Subtle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 6))

        columns = ("kind", "started", "ended", "duration", "counted")
        self.tree = ttk.Treeview(
            main,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        self.tree.grid(row=4, column=0, sticky="nsew")
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
        actions.grid(row=5, column=0, sticky="w", pady=(8, 12))
        self.edit_button = ttk.Button(actions, text="Edit", command=self._edit_selected)
        self.edit_button.grid(row=0, column=0, padx=(0, 8))
        self.delete_button = ttk.Button(
            actions,
            text="Delete",
            command=self._delete_selected,
        )
        self.delete_button.grid(row=0, column=1)
        self._sync_buttons()

        ttk.Label(main, text="Activity", style="Subtle.TLabel").grid(
            row=6, column=0, sticky="nw"
        )
        self.log = tk.Text(main, height=6, wrap="word", state="disabled")
        self.log.grid(row=6, column=0, sticky="nsew", pady=(18, 0))
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

    def _on_unmap(self, _event=None) -> None:
        if self._hiding_to_tray:
            return
        if self.root.state() == "iconic":
            self.root.after_idle(self._minimize_to_tray)

    def _minimize_to_tray(self) -> None:
        self._hiding_to_tray = True
        self.root.withdraw()
        self._hiding_to_tray = False
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
            if self.root.focus_get() is not self.start_entry:
                self.start_var.set(format_start_field(summary.start, now.date()))
            if self.root.focus_get() is not self.hours_spin:
                self.hours_var.set(f"{self.tracker.workday_hours():g}")
            if self.root.focus_get() is not self.threshold_spin:
                self.threshold_var.set(str(self.tracker.threshold_minutes()))
            self._fill_tree()
        finally:
            self._refreshing = False

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

    def _save_start(self, *_args) -> None:
        if self._refreshing:
            return
        text = self.start_var.get().strip()
        if not text:
            return
        now = dt.datetime.now()
        try:
            start = parse_start(text, now)
            current = self.tracker.summary(now).start
            if start == current.replace(second=0, microsecond=0):
                return
            self.tracker.set_start_time(start, now=now)
        except (TrackerError, ValueError) as exc:
            messagebox.showerror("Hourly Tracker", str(exc), parent=self.root)
            self.refresh()
            return
        self._log(f"Start time set to {text}.")
        self.refresh()

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
        if self._tray is not None:
            self.root.iconify()
            return
        self._quit()

    def _quit(self) -> None:
        self._polling = False
        if self._tray is not None:
            self._tray.stop()
        try:
            self.tracker.shutdown(dt.datetime.now())
        except Exception:
            logging.exception("Shutdown failed")
        self.root.destroy()


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
