"""Workday model.

Idle time is keyboard and mouse silence while this process is running and the
machine is awake. Offline time is a gap in the heartbeat: sleep, shutdown, or
the app being closed. Both are stored as away events. Deleting an event puts
that time back into the hours worked.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Callable

from hourly_tracker.formatting import format_clock, format_stamp, most_recent_start
from hourly_tracker.storage import AwayEvent, Storage

DEFAULT_WORKDAY_HOURS = 9.0
DEFAULT_THRESHOLD_MINUTES = 20
MIN_OFFLINE_GAP = dt.timedelta(seconds=30)
RETURN_IDLE_SECONDS = 2.0

LoginProvider = Callable[[], dt.datetime | None]


class TrackerError(ValueError):
    """The requested change would make the away log inconsistent."""


@dataclass(frozen=True)
class DaySummary:
    day: dt.date
    start: dt.datetime
    workday: dt.timedelta
    threshold: dt.timedelta
    idle: dt.timedelta
    offline: dt.timedelta
    away: dt.timedelta
    worked: dt.timedelta
    remaining: dt.timedelta
    projected_end: dt.datetime
    status: str


@dataclass(frozen=True)
class AwayRow:
    id: int
    kind: str
    started_at: dt.datetime
    ended_at: dt.datetime | None
    duration: dt.timedelta
    counted: dt.timedelta


def clean(value: dt.datetime) -> dt.datetime:
    return value.replace(microsecond=0)


def merge_duration(
    intervals: list[tuple[dt.datetime, dt.datetime]],
) -> dt.timedelta:
    if not intervals:
        return dt.timedelta(0)
    ordered = sorted(intervals)
    total = dt.timedelta(0)
    cursor_start, cursor_end = ordered[0]
    for start, end in ordered[1:]:
        if start <= cursor_end:
            if end > cursor_end:
                cursor_end = end
        else:
            total += cursor_end - cursor_start
            cursor_start, cursor_end = start, end
    return total + (cursor_end - cursor_start)


def clip_interval(
    start: dt.datetime,
    end: dt.datetime,
    window_start: dt.datetime,
    window_end: dt.datetime,
) -> tuple[dt.datetime, dt.datetime] | None:
    clipped_start = max(start, window_start)
    clipped_end = min(end, window_end)
    if clipped_end <= clipped_start:
        return None
    return clipped_start, clipped_end


def iter_day_slices(
    start: dt.datetime,
    end: dt.datetime,
) -> list[tuple[dt.datetime, dt.datetime]]:
    slices: list[tuple[dt.datetime, dt.datetime]] = []
    cursor = start
    while cursor < end:
        midnight = dt.datetime.combine(
            cursor.date() + dt.timedelta(days=1),
            dt.time.min,
        )
        piece_end = min(end, midnight)
        if piece_end > cursor:
            slices.append((cursor, piece_end))
        cursor = piece_end
    return slices


def coerce_start(
    day: dt.date,
    login: dt.datetime | None,
) -> dt.datetime | None:
    """Place an OS logon time on `day` using its clock time.

    Returns None when there is no login time and the caller should use "now".
    The caller rolls a result that is still in the future back to yesterday.
    """
    if login is None:
        return None
    if login.date() > day:
        return None
    return dt.datetime.combine(day, login.time()).replace(second=0, microsecond=0)


class Tracker:
    def __init__(
        self,
        storage: Storage,
        login_time: LoginProvider | None = None,
    ):
        self.storage = storage
        self._login_time = login_time or (lambda: None)
        self._idle_baseline = _load_float(storage, "runtime/idle_baseline")
        self._ignore_idle_streak = (
            storage.get_setting("runtime/ignore_idle_streak", "0") == "1"
        )
        # Each process starts blind to idle time that already elapsed. The
        # first sample becomes the baseline so a restart cannot copy the OS
        # idle timer back over events this process did not observe.
        self._arm_baseline = True
        self._open_idle_id: int | None = None

    def tick(self, now: dt.datetime, idle_seconds: float | None) -> list[str]:
        now = clean(now)
        last = self.storage.get_heartbeat()
        if last is not None and now < last:
            return []

        self._ensure_start(now)
        messages: list[str] = []
        self._consume_gap(now, messages)
        self._roll_open_idle_into_today(now, messages)
        self._consume_idle(now, idle_seconds, messages)
        self.storage.set_heartbeat(now)
        self._persist_runtime()
        messages.extend(self._completion_messages(now))
        return messages

    def shutdown(self, now: dt.datetime) -> None:
        """Stop observing. The next launch treats the gap as offline."""
        now = clean(now)
        self._close_open_idle(now, [], returned=False)
        self.storage.set_heartbeat(now)
        self._persist_runtime()

    def summary(self, now: dt.datetime) -> DaySummary:
        now = clean(now)
        start = self._ensure_start(now)
        workday = dt.timedelta(hours=self.workday_hours())
        if now <= start:
            idle = offline = away = worked = dt.timedelta(0)
        else:
            idle = self._merged("idle", start, now)
            offline = self._merged("offline", start, now)
            away = self._merged(None, start, now)
            worked = (now - start) - away
            if worked < dt.timedelta(0):
                worked = dt.timedelta(0)
        projected_end = start + workday + away
        remaining = workday - worked
        if remaining < dt.timedelta(0):
            remaining = dt.timedelta(0)
        if self._has_open_idle():
            status = "idle"
        elif now >= projected_end:
            status = "complete"
        else:
            status = "working"
        return DaySummary(
            day=now.date(),
            start=start,
            workday=workday,
            threshold=dt.timedelta(minutes=self.threshold_minutes()),
            idle=idle,
            offline=offline,
            away=away,
            worked=worked,
            remaining=remaining,
            projected_end=projected_end,
            status=status,
        )

    def rows(self, now: dt.datetime) -> list[AwayRow]:
        now = clean(now)
        start = self._ensure_start(now)
        day_start = dt.datetime.combine(now.date(), dt.time.min)
        day_end = day_start + dt.timedelta(days=1)
        # Include the stretch since start when the workday began yesterday.
        day_start = start if start < day_start else day_start
        rows: list[AwayRow] = []
        for event in self.storage.events_overlapping(day_start, day_end):
            effective_end = event.ended_at or now
            if event.ended_at is None and effective_end < event.started_at:
                effective_end = event.started_at
            counted_window_end = now if now > start else start
            clipped = clip_interval(
                event.started_at,
                effective_end,
                start,
                counted_window_end,
            )
            counted = clipped[1] - clipped[0] if clipped else dt.timedelta(0)
            rows.append(
                AwayRow(
                    id=event.id,
                    kind=event.kind,
                    started_at=event.started_at,
                    ended_at=event.ended_at,
                    duration=effective_end - event.started_at,
                    counted=counted,
                )
            )
        rows.sort(key=lambda row: row.started_at, reverse=True)
        return rows

    def set_start_time(self, when: dt.datetime, now: dt.datetime | None = None) -> None:
        when = when.replace(second=0, microsecond=0)
        if now is not None:
            anchored = most_recent_start(when, clean(now))
            if anchored.date() != when.date():
                self.storage.delete_setting(_start_key(when.date()))
            when = anchored
        self.storage.set_setting(_start_key(when.date()), _dump(when))

    def set_workday_hours(self, hours: float) -> None:
        if hours <= 0 or hours > 24:
            raise TrackerError("Workday length must be between 0 and 24 hours.")
        self.storage.set_setting("workday_hours", f"{hours:g}")

    def set_threshold_minutes(self, minutes: int) -> None:
        if minutes < 1 or minutes > 240:
            raise TrackerError("Away threshold must be between 1 and 240 minutes.")
        self.storage.set_setting("idle_threshold_minutes", str(int(minutes)))

    def workday_hours(self) -> float:
        raw = self.storage.get_setting("workday_hours", str(DEFAULT_WORKDAY_HOURS))
        try:
            hours = float(raw or DEFAULT_WORKDAY_HOURS)
        except ValueError:
            hours = DEFAULT_WORKDAY_HOURS
        return hours

    def threshold_minutes(self) -> int:
        raw = self.storage.get_setting(
            "idle_threshold_minutes",
            str(DEFAULT_THRESHOLD_MINUTES),
        )
        try:
            minutes = int(float(raw or DEFAULT_THRESHOLD_MINUTES))
        except ValueError:
            minutes = DEFAULT_THRESHOLD_MINUTES
        return minutes

    def delete_event(
        self,
        event_id: int,
        now: dt.datetime,
        idle_seconds: float | None,
    ) -> None:
        event = self.storage.get_event(event_id)
        if event is None:
            raise TrackerError("That away event no longer exists.")
        was_open = event.ended_at is None and event.kind == "idle"
        self.storage.delete_event(event_id)
        if self._open_idle_id == event_id:
            self._open_idle_id = None
        if was_open:
            self._ignore_idle_streak = True
        else:
            self._suppress_if_overlaps_streak(event, clean(now), idle_seconds)
        self._persist_runtime()

    def update_event(
        self,
        event_id: int,
        *,
        kind: str,
        started_at: dt.datetime,
        ended_at: dt.datetime | None,
        now: dt.datetime,
        idle_seconds: float | None,
    ) -> None:
        if kind not in ("idle", "offline"):
            raise TrackerError("Type must be idle or offline.")
        now = clean(now)
        started_at = clean(started_at)
        if ended_at is not None:
            ended_at = clean(ended_at)
            if ended_at <= started_at:
                raise TrackerError("End time must be after the start time.")
            if ended_at > now + dt.timedelta(minutes=1):
                raise TrackerError("End time can't be in the future.")
        if started_at > now:
            raise TrackerError("Start time can't be in the future.")
        existing = self.storage.get_event(event_id)
        if existing is None:
            raise TrackerError("That away event no longer exists.")
        self._reject_overlap(event_id, started_at, ended_at or now, now)
        self.storage.update_event(event_id, kind, started_at, ended_at)
        was_open = existing.ended_at is None and existing.id == self._open_idle_id
        if existing.ended_at is None and existing.kind == "idle":
            was_open = True
        if was_open and (ended_at is not None or kind != "idle"):
            self._open_idle_id = None
            self._ignore_idle_streak = True
        elif was_open:
            self._open_idle_id = event_id
        else:
            self._suppress_if_overlaps_streak(existing, now, idle_seconds)
        self._persist_runtime()

    def _ensure_start(self, now: dt.datetime) -> dt.datetime:
        now = clean(now)
        today_raw = self.storage.get_setting(_start_key(now.date()))
        if today_raw:
            stored = clean(dt.datetime.fromisoformat(today_raw))
            start = most_recent_start(stored, now)
            if start != stored:
                # Drop the future clock time (11:57 PM later tonight) and keep
                # the occurrence that already happened.
                self.storage.delete_setting(_start_key(stored.date()))
                self.storage.set_setting(_start_key(start.date()), _dump(start))
            return start

        coerced = coerce_start(now.date(), self._login_time())
        if coerced is None:
            start = now.replace(second=0, microsecond=0)
        else:
            start = most_recent_start(coerced, now)
        existing = self.storage.get_setting(_start_key(start.date()))
        if existing:
            return clean(dt.datetime.fromisoformat(existing))
        self.storage.set_setting(_start_key(start.date()), _dump(start))
        return start

    def _consume_gap(self, now: dt.datetime, messages: list[str]) -> None:
        last = self.storage.get_heartbeat()
        if last is None:
            self._arm_baseline = True
            return
        gap = now - last
        if gap < self._gap_cutoff():
            self._sync_open_idle()
            return
        # The process was not observing this stretch: sleep, power off, or quit.
        self._close_open_at(last)
        self._open_idle_id = None
        self._ignore_idle_streak = False
        self._record_offline(last, now, messages)
        self._arm_baseline = True

    def _consume_idle(
        self,
        now: dt.datetime,
        idle_seconds: float | None,
        messages: list[str],
    ) -> None:
        if idle_seconds is None:
            return
        idle_seconds = max(0.0, float(idle_seconds))
        if self._arm_baseline:
            # The first sample after this process starts is the baseline. Idle
            # that already elapsed is not copied into a new event. An idle
            # event left open by a crash is closed when the user is back.
            self._arm_baseline = False
            if self._open_idle_id is not None and idle_seconds < RETURN_IDLE_SECONDS:
                self._idle_baseline = 0.0
                self._ignore_idle_streak = False
                self._close_open_idle(now, messages, returned=True)
                return
            self._idle_baseline = idle_seconds
            return
        if idle_seconds < self._idle_baseline:
            self._idle_baseline = 0.0
        effective = idle_seconds - self._idle_baseline
        if effective < RETURN_IDLE_SECONDS:
            self._ignore_idle_streak = False
            self._close_open_idle(now, messages, returned=True)
            return
        if self._ignore_idle_streak:
            return
        if effective < self.threshold_minutes() * 60:
            return
        if self._open_idle_id is not None:
            return
        start = now - dt.timedelta(seconds=effective)
        midnight = dt.datetime.combine(now.date(), dt.time.min)
        if start < midnight:
            start = midnight
        if start >= now:
            return
        event = self.storage.add_event("idle", start, None)
        self._open_idle_id = event.id
        messages.append(f"Idle since {format_clock(start)}.")

    def _roll_open_idle_into_today(
        self,
        now: dt.datetime,
        messages: list[str],
    ) -> None:
        if self._open_idle_id is None:
            return
        event = self.storage.get_event(self._open_idle_id)
        if event is None or event.ended_at is not None:
            self._open_idle_id = None
            return
        midnight = dt.datetime.combine(now.date(), dt.time.min)
        if event.started_at >= midnight:
            return
        self.storage.close_event(event.id, midnight)
        continued = self.storage.add_event("idle", midnight, None)
        self._open_idle_id = continued.id
        messages.append("Continued idle into the new day.")

    def _close_open_idle(
        self,
        now: dt.datetime,
        messages: list[str],
        *,
        returned: bool,
    ) -> None:
        if self._open_idle_id is None:
            return
        event = self.storage.get_event(self._open_idle_id)
        self._open_idle_id = None
        if event is None or event.ended_at is not None:
            return
        if now <= event.started_at:
            self.storage.delete_event(event.id)
            return
        self.storage.close_event(event.id, now)
        if returned:
            messages.append(f"Back at {format_clock(now)}.")

    def _close_open_at(self, when: dt.datetime) -> None:
        when = clean(when)
        for event in self.storage.open_events():
            if when <= event.started_at:
                self.storage.delete_event(event.id)
            else:
                self.storage.close_event(event.id, when)

    def _record_offline(
        self,
        start: dt.datetime,
        end: dt.datetime,
        messages: list[str],
    ) -> None:
        start = clean(start)
        end = clean(end)
        if end <= start:
            return
        for piece_start, piece_end in iter_day_slices(start, end):
            self.storage.add_event("offline", piece_start, piece_end)
        messages.append(f"Offline from {format_stamp(start)} to {format_stamp(end)}.")

    def _gap_cutoff(self) -> dt.timedelta:
        threshold = dt.timedelta(minutes=self.threshold_minutes())
        if threshold < MIN_OFFLINE_GAP:
            return MIN_OFFLINE_GAP
        return threshold

    def _merged(
        self,
        kind: str | None,
        window_start: dt.datetime,
        window_end: dt.datetime,
    ) -> dt.timedelta:
        intervals: list[tuple[dt.datetime, dt.datetime]] = []
        for event in self.storage.events_overlapping(window_start, window_end):
            if kind is not None and event.kind != kind:
                continue
            end = event.ended_at or window_end
            clipped = clip_interval(event.started_at, end, window_start, window_end)
            if clipped is not None:
                intervals.append(clipped)
        return merge_duration(intervals)

    def _has_open_idle(self) -> bool:
        self._sync_open_idle()
        return self._open_idle_id is not None

    def _sync_open_idle(self) -> None:
        if self._open_idle_id is not None:
            event = self.storage.get_event(self._open_idle_id)
            if event is not None and event.ended_at is None and event.kind == "idle":
                return
            self._open_idle_id = None
        for event in self.storage.open_events():
            if event.kind == "idle":
                self._open_idle_id = event.id
                return

    def _reject_overlap(
        self,
        event_id: int,
        start: dt.datetime,
        end: dt.datetime,
        now: dt.datetime,
    ) -> None:
        for other in self.storage.events_overlapping(start, end):
            if other.id == event_id:
                continue
            other_end = other.ended_at or now
            if start < other_end and other.started_at < end:
                raise TrackerError("That range overlaps another away event.")

    def _suppress_if_overlaps_streak(
        self,
        event: AwayEvent,
        now: dt.datetime,
        idle_seconds: float | None,
    ) -> None:
        if event.kind != "idle" or idle_seconds is None:
            return
        effective = max(0.0, float(idle_seconds) - self._idle_baseline)
        if effective < self.threshold_minutes() * 60:
            return
        streak_start = now - dt.timedelta(seconds=effective)
        event_end = event.ended_at or now
        if event.started_at < now and event_end > streak_start:
            self._ignore_idle_streak = True

    def _completion_messages(self, now: dt.datetime) -> list[str]:
        current = self.summary(now)
        setting = f"announced_end:{current.day.isoformat()}"
        previous = self.storage.get_setting(setting, "") or ""
        key = _dump(current.projected_end)
        if now < current.projected_end:
            if previous:
                self.storage.set_setting(setting, "")
            return []
        if previous == key:
            return []
        moved_later = True
        if previous:
            try:
                moved_later = current.projected_end > dt.datetime.fromisoformat(previous)
            except ValueError:
                moved_later = True
        self.storage.set_setting(setting, key)
        if not moved_later:
            return []
        clock = format_clock(current.projected_end)
        return [f"Workday complete at {clock}."]

    def _persist_runtime(self) -> None:
        self.storage.set_setting("runtime/idle_baseline", f"{self._idle_baseline:.3f}")
        self.storage.set_setting(
            "runtime/ignore_idle_streak",
            "1" if self._ignore_idle_streak else "0",
        )
        self.storage.set_setting(
            "runtime/arm_baseline",
            "1" if self._arm_baseline else "0",
        )


def _start_key(day: dt.date) -> str:
    return f"start:{day.isoformat()}"


def _dump(value: dt.datetime) -> str:
    return clean(value).isoformat(timespec="seconds")


def _load_float(storage: Storage, key: str) -> float:
    raw = storage.get_setting(key, "0") or "0"
    try:
        return float(raw)
    except ValueError:
        return 0.0
