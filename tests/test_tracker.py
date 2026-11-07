"""Tracker rules for idle, offline, and correcting away time."""

from __future__ import annotations

import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hourly_tracker.formatting import (
    format_duration,
    most_recent_start,
    parse_clock,
    parse_start,
    parse_timestamp,
)
from hourly_tracker.idle import get_idle_seconds
from hourly_tracker.login_time import get_login_time
from hourly_tracker.storage import Storage
from hourly_tracker.tracker import (
    Tracker,
    TrackerError,
    coerce_start,
    iter_day_slices,
    merge_duration,
)


class TrackerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def make_tracker(self, login=None, threshold=1):
        storage = Storage(Path(self._tmp.name) / "test.db")
        self.addCleanup(storage.close)
        tracker = Tracker(storage, login_time=login or (lambda: None))
        if threshold is not None:
            tracker.set_threshold_minutes(threshold)
        return tracker

    def events(self, tracker):
        start = dt.datetime(2000, 1, 1)
        return tracker.storage.events_overlapping(start, dt.datetime(2100, 1, 1))

    def test_first_sample_does_not_backfill_idle(self):
        day = dt.datetime(2026, 11, 6, 9, 0, 0)
        tracker = self.make_tracker(lambda: day)
        tracker.tick(day, idle_seconds=3 * 3600)
        self.assertEqual(self.events(tracker), [])
        summary = tracker.summary(day)
        self.assertEqual(summary.away, dt.timedelta(0))
        self.assertEqual(summary.status, "working")

    def test_idle_starts_at_threshold_and_closes_on_return(self):
        start = dt.datetime(2026, 11, 6, 8, 0, 0)
        tracker = self.make_tracker(lambda: start)
        tracker.tick(start, 0)
        tracker.tick(start + dt.timedelta(seconds=30), 30)
        self.assertEqual(self.events(tracker), [])

        opened = start + dt.timedelta(seconds=60)
        messages = tracker.tick(opened, 60)
        self.assertTrue(any("Idle since" in message for message in messages))
        event = self.events(tracker)[0]
        self.assertEqual(event.kind, "idle")
        self.assertEqual(event.started_at, start)
        self.assertIsNone(event.ended_at)
        self.assertEqual(tracker.summary(opened).status, "idle")

        back = opened + dt.timedelta(seconds=10)
        messages = tracker.tick(back, 0)
        self.assertTrue(any(message.startswith("Back at") for message in messages))
        event = self.events(tracker)[0]
        self.assertEqual(event.ended_at, back)

        now = start + dt.timedelta(hours=1)
        summary = tracker.summary(now)
        self.assertEqual(summary.idle, back - start)
        self.assertEqual(summary.offline, dt.timedelta(0))
        self.assertEqual(summary.away, back - start)
        self.assertEqual(summary.worked, (now - start) - (back - start))

    def test_long_gap_is_offline_and_not_also_idle(self):
        start = dt.datetime(2026, 11, 6, 12, 0, 0)
        tracker = self.make_tracker(lambda: start, threshold=20)
        tracker.tick(start, 0)
        woke = start + dt.timedelta(hours=2)
        messages = tracker.tick(woke, idle_seconds=2 * 3600)
        self.assertTrue(any(message.startswith("Offline from") for message in messages))
        events = self.events(tracker)
        self.assertEqual([event.kind for event in events], ["offline"])
        self.assertEqual(events[0].started_at, start)
        self.assertEqual(events[0].ended_at, woke)
        summary = tracker.summary(woke)
        self.assertEqual(summary.offline, dt.timedelta(hours=2))
        self.assertEqual(summary.idle, dt.timedelta(0))
        self.assertEqual(summary.worked, dt.timedelta(0))

    def test_short_gap_is_not_offline(self):
        start = dt.datetime(2026, 11, 6, 12, 0, 0)
        tracker = self.make_tracker(lambda: start, threshold=20)
        tracker.tick(start, 0)
        tracker.tick(start + dt.timedelta(seconds=20), 0)
        self.assertEqual(self.events(tracker), [])

    def test_sleep_closes_open_idle_before_offline_span(self):
        start = dt.datetime(2026, 11, 6, 10, 0, 0)
        tracker = self.make_tracker(lambda: start)
        opened = self._open_idle(tracker, start)
        asleep = opened + dt.timedelta(seconds=10)
        tracker.tick(asleep, 70)
        woke = asleep + dt.timedelta(minutes=30)
        tracker.tick(woke, idle_seconds=70)
        events = self.events(tracker)
        idle = next(event for event in events if event.kind == "idle")
        offline = next(event for event in events if event.kind == "offline")
        self.assertEqual(idle.ended_at, asleep)
        self.assertEqual(offline.started_at, asleep)
        self.assertEqual(offline.ended_at, woke)

    def test_delete_puts_time_back_into_worked_hours(self):
        start = dt.datetime(2026, 11, 6, 8, 0, 0)
        tracker = self.make_tracker(lambda: start)
        tracker.set_workday_hours(8)
        self._open_idle(tracker, start)
        back = start + dt.timedelta(seconds=70)
        tracker.tick(back, 0)
        now = start + dt.timedelta(hours=4)
        before = tracker.summary(now)
        self.assertEqual(before.away, dt.timedelta(seconds=70))
        self.assertEqual(before.projected_end, start + dt.timedelta(hours=8, seconds=70))
        self.assertEqual(before.worked, dt.timedelta(hours=4) - before.away)

        tracker.delete_event(self.events(tracker)[0].id, now, 0)
        after = tracker.summary(now)
        self.assertEqual(after.away, dt.timedelta(0))
        self.assertEqual(after.worked, dt.timedelta(hours=4))
        self.assertEqual(after.projected_end, start + dt.timedelta(hours=8))
        self.assertGreater(after.worked, before.worked)
        self.assertEqual(self.events(tracker), [])

    def test_update_changes_counted_duration_and_rejects_overlap(self):
        start = dt.datetime(2026, 11, 6, 8, 0, 0)
        tracker = self.make_tracker(lambda: start)
        self._open_idle(tracker, start)
        first_end = start + dt.timedelta(seconds=70)
        tracker.tick(first_end, 0)
        second = first_end + dt.timedelta(seconds=40)
        tracker.tick(second, 0)
        tracker.tick(second + dt.timedelta(seconds=30), 30)
        second_end = second + dt.timedelta(seconds=70)
        tracker.tick(second + dt.timedelta(seconds=60), 60)
        tracker.tick(second_end, 0)
        events = self.events(tracker)
        self.assertEqual(len(events), 2)

        now = start + dt.timedelta(hours=2)
        tracker.update_event(
            events[0].id,
            kind="idle",
            started_at=events[0].started_at,
            ended_at=events[0].started_at + dt.timedelta(seconds=30),
            now=now,
            idle_seconds=0,
        )
        self.assertEqual(
            tracker.summary(now).idle,
            dt.timedelta(seconds=30) + (second_end - second),
        )
        with self.assertRaises(TrackerError):
            tracker.update_event(
                events[0].id,
                kind="idle",
                started_at=events[0].started_at,
                ended_at=second + dt.timedelta(seconds=10),
                now=now,
                idle_seconds=0,
            )
        with self.assertRaises(TrackerError):
            tracker.update_event(
                events[0].id,
                kind="idle",
                started_at=events[0].started_at,
                ended_at=events[0].started_at,
                now=now,
                idle_seconds=0,
            )

    def test_deleting_open_idle_does_not_recreate_it(self):
        start = dt.datetime(2026, 11, 6, 8, 0, 0)
        tracker = self.make_tracker(lambda: start)
        opened = self._open_idle(tracker, start)
        event_id = self.events(tracker)[0].id
        tracker.delete_event(event_id, opened, idle_seconds=60)
        tracker.tick(opened + dt.timedelta(seconds=20), 80)
        self.assertEqual(self.events(tracker), [])

        back = opened + dt.timedelta(seconds=30)
        tracker.tick(back, 0)
        self._open_idle(tracker, back)
        self.assertEqual(len(self.events(tracker)), 1)

    def test_restart_keeps_open_idle_without_duplicating_it(self):
        start = dt.datetime(2026, 11, 6, 8, 0, 0)
        tracker = self.make_tracker(lambda: start)
        opened = self._open_idle(tracker, start)
        resumed = Tracker(tracker.storage, login_time=lambda: start)
        resumed.tick(opened + dt.timedelta(seconds=15), 75)
        events = self.events(resumed)
        self.assertEqual(len(events), 1)
        self.assertIsNone(events[0].ended_at)
        self.assertEqual(resumed.summary(opened + dt.timedelta(seconds=15)).status, "idle")

    def test_restart_closes_open_idle_when_user_is_back(self):
        start = dt.datetime(2026, 11, 6, 8, 0, 0)
        tracker = self.make_tracker(lambda: start)
        opened = self._open_idle(tracker, start)
        resumed = Tracker(tracker.storage, login_time=lambda: start)
        back = opened + dt.timedelta(seconds=10)
        messages = resumed.tick(back, 0)
        self.assertTrue(any(message.startswith("Back at") for message in messages))
        event = self.events(resumed)[0]
        self.assertEqual(event.ended_at, back)

    def test_shutdown_then_reopen_records_offline(self):
        start = dt.datetime(2026, 11, 6, 9, 0, 0)
        tracker = self.make_tracker(lambda: start, threshold=20)
        tracker.tick(start, 0)
        closed = start + dt.timedelta(minutes=5)
        tracker.shutdown(closed)
        resumed = Tracker(tracker.storage, login_time=lambda: start)
        reopened = closed + dt.timedelta(hours=1)
        resumed.tick(reopened, 0)
        events = self.events(resumed)
        self.assertEqual([event.kind for event in events], ["offline"])
        self.assertEqual(events[0].started_at, closed)
        self.assertEqual(events[0].ended_at, reopened)

    def test_overnight_gap_splits_at_midnight(self):
        start = dt.datetime(2026, 11, 6, 23, 50, 0)
        tracker = self.make_tracker(lambda: start, threshold=20)
        tracker.tick(start, 0)
        morning = dt.datetime(2026, 11, 7, 2, 0, 0)
        tracker.tick(morning, 0)
        events = self.events(tracker)
        self.assertEqual(
            [(event.started_at, event.ended_at) for event in events],
            [
                (start, dt.datetime(2026, 11, 7, 0, 0, 0)),
                (dt.datetime(2026, 11, 7, 0, 0, 0), morning),
            ],
        )
        summary = tracker.summary(morning)
        self.assertEqual(summary.start, start)
        self.assertEqual(summary.offline, morning - start)
        self.assertEqual(summary.worked, dt.timedelta(0))

    def test_open_idle_rolls_into_the_new_day(self):
        start = dt.datetime(2026, 11, 6, 23, 58, 0)
        tracker = self.make_tracker(lambda: start)
        tracker.tick(start, 0)
        tracker.tick(start + dt.timedelta(seconds=30), 30)
        tracker.tick(start + dt.timedelta(seconds=60), 60)
        tracker.tick(start + dt.timedelta(seconds=100), 100)
        rolled = dt.datetime(2026, 11, 7, 0, 0, 20)
        messages = tracker.tick(rolled, 140)
        self.assertTrue(any("new day" in message for message in messages))
        events = self.events(tracker)
        self.assertEqual(events[0].ended_at, dt.datetime(2026, 11, 7, 0, 0, 0))
        self.assertEqual(events[1].started_at, dt.datetime(2026, 11, 7, 0, 0, 0))
        self.assertIsNone(events[1].ended_at)

    def test_time_before_start_is_not_counted(self):
        start = dt.datetime(2026, 11, 6, 8, 0, 0)
        tracker = self.make_tracker(lambda: start)
        opened = self._open_idle(tracker, start)
        back = opened + dt.timedelta(seconds=30)
        tracker.tick(back, 0)
        tracker.set_start_time(start + dt.timedelta(seconds=60))
        now = start + dt.timedelta(hours=1)
        summary = tracker.summary(now)
        self.assertEqual(summary.idle, dt.timedelta(seconds=30))
        row = tracker.rows(now)[0]
        self.assertEqual(row.duration, back - start)
        self.assertEqual(row.counted, dt.timedelta(seconds=30))

    def test_evening_start_after_midnight_counts_as_time_worked(self):
        login = dt.datetime(2026, 11, 6, 23, 57, 0)
        tracker = self.make_tracker(lambda: login)
        now = dt.datetime(2026, 11, 7, 0, 15, 0)
        tracker.storage.set_setting("start:2026-11-07", "2026-11-07T23:57:00")
        first = dt.datetime(2026, 11, 7, 0, 1, 54)
        second = dt.datetime(2026, 11, 7, 0, 3, 15)
        third = dt.datetime(2026, 11, 7, 0, 4, 24)
        tracker.storage.add_event("idle", first, second)
        tracker.storage.add_event("idle", second, third)
        tracker.set_workday_hours(8)

        summary = tracker.summary(now)
        idle = third - first
        self.assertEqual(summary.start, login)
        self.assertEqual(summary.idle, idle)
        self.assertEqual(summary.away, idle)
        self.assertEqual(summary.worked, (now - login) - idle)
        self.assertEqual(summary.remaining, dt.timedelta(hours=8) - summary.worked)
        self.assertNotEqual(summary.worked, dt.timedelta(0))
        for row in tracker.rows(now):
            self.assertEqual(row.counted, row.duration)
            self.assertGreater(row.counted, dt.timedelta(0))

    def test_previous_session_uses_today_at_that_clock_time(self):
        login = dt.datetime(2026, 11, 5, 8, 30, 0)
        tracker = self.make_tracker(lambda: login, threshold=20)
        now = dt.datetime(2026, 11, 6, 9, 0, 0)
        tracker.tick(now, 0)
        summary = tracker.summary(now)
        self.assertEqual(summary.start, dt.datetime(2026, 11, 6, 8, 30, 0))
        self.assertEqual(summary.worked, dt.timedelta(minutes=30))
        tracker.set_start_time(dt.datetime(2026, 11, 6, 8, 0, 0))
        tracker.tick(now + dt.timedelta(seconds=5), 0)
        self.assertEqual(
            tracker.summary(now).start,
            dt.datetime(2026, 11, 6, 8, 0, 0),
        )

    def test_missing_login_uses_the_current_minute(self):
        tracker = self.make_tracker(threshold=20)
        now = dt.datetime(2026, 11, 6, 9, 15, 45)
        tracker.tick(now, 0)
        self.assertEqual(
            tracker.summary(now).start,
            dt.datetime(2026, 11, 6, 9, 15, 0),
        )

    def test_clock_moving_backwards_does_not_record_a_gap(self):
        start = dt.datetime(2026, 11, 6, 10, 0, 0)
        tracker = self.make_tracker(lambda: start, threshold=20)
        tracker.tick(start, 0)
        tracker.tick(start - dt.timedelta(hours=1), 0)
        self.assertEqual(self.events(tracker), [])
        self.assertEqual(tracker.storage.get_heartbeat(), start)

    def test_completion_is_announced_once(self):
        start = dt.datetime(2026, 11, 6, 8, 0, 0)
        tracker = self.make_tracker(lambda: start, threshold=240)
        tracker.set_workday_hours(1)
        tracker.tick(start, 0)
        done = start + dt.timedelta(hours=1, minutes=5)
        messages = tracker.tick(done, 0)
        self.assertTrue(any(message.startswith("Workday complete") for message in messages))
        self.assertEqual(tracker.summary(done).status, "complete")
        self.assertEqual(tracker.summary(done).remaining, dt.timedelta(0))
        again = tracker.tick(done + dt.timedelta(minutes=1), 0)
        self.assertFalse(any(message.startswith("Workday complete") for message in again))

    def test_projected_end_uses_workday_length(self):
        start = dt.datetime(2026, 11, 6, 8, 0, 0)
        tracker = self.make_tracker(lambda: start, threshold=20)
        tracker.tick(start, 0)
        tracker.set_workday_hours(7.5)
        summary = tracker.summary(start + dt.timedelta(hours=2))
        self.assertEqual(summary.projected_end, start + dt.timedelta(hours=7.5))
        self.assertEqual(summary.remaining, dt.timedelta(hours=5.5))
        with self.assertRaises(TrackerError):
            tracker.set_workday_hours(0)
        with self.assertRaises(TrackerError):
            tracker.set_threshold_minutes(0)

    def test_merge_and_day_slices(self):
        origin = dt.datetime(2026, 11, 6, 8, 0, 0)
        intervals = [
            (origin, origin + dt.timedelta(hours=1)),
            (origin + dt.timedelta(minutes=30), origin + dt.timedelta(hours=2)),
        ]
        self.assertEqual(merge_duration(intervals), dt.timedelta(hours=2))
        slices = iter_day_slices(
            dt.datetime(2026, 11, 6, 23, 0, 0),
            dt.datetime(2026, 11, 7, 1, 0, 0),
        )
        self.assertEqual(len(slices), 2)
        self.assertEqual(slices[0][1], slices[1][0])
        self.assertIsNone(coerce_start(origin.date(), None))
        self.assertEqual(
            coerce_start(origin.date(), dt.datetime(2026, 11, 5, 8, 30, 40)),
            dt.datetime(2026, 11, 6, 8, 30, 0),
        )

    def _open_idle(self, tracker, start):
        """Cross a 1-minute threshold in steps too short to look offline."""
        tracker.tick(start, 0)
        tracker.tick(start + dt.timedelta(seconds=30), 30)
        opened = start + dt.timedelta(seconds=60)
        tracker.tick(opened, 60)
        self.assertIsNone(self.events(tracker)[-1].ended_at)
        return opened


class FormattingTest(unittest.TestCase):
    def test_duration_and_timestamps(self):
        self.assertEqual(format_duration(dt.timedelta(0)), "0m")
        self.assertEqual(format_duration(dt.timedelta(seconds=70)), "1m 10s")
        self.assertEqual(format_duration(dt.timedelta(hours=1, minutes=5)), "1h 05m")
        day = dt.date(2026, 11, 6)
        self.assertEqual(parse_clock("8:30 AM", day), dt.datetime(2026, 11, 6, 8, 30))
        self.assertEqual(parse_clock("08:30", day), dt.datetime(2026, 11, 6, 8, 30))
        self.assertEqual(
            parse_timestamp("2026-11-06 14:04:05"),
            dt.datetime(2026, 11, 6, 14, 4, 5),
        )
        now = dt.datetime(2026, 11, 7, 0, 15)
        self.assertEqual(
            most_recent_start(dt.datetime(2026, 11, 7, 23, 57), now),
            dt.datetime(2026, 11, 6, 23, 57),
        )
        self.assertEqual(parse_start("11:57 PM", now), dt.datetime(2026, 11, 6, 23, 57))
        self.assertEqual(
            parse_start("Nov 6, 11:57 PM", now),
            dt.datetime(2026, 11, 6, 23, 57),
        )


class PlatformProbeTest(unittest.TestCase):
    def test_idle_probe_returns_a_duration(self):
        seconds = get_idle_seconds()
        self.assertGreaterEqual(seconds, 0)
        self.assertLess(seconds, 60 * 60 * 24 * 50)

    def test_login_probe_does_not_crash(self):
        value = get_login_time()
        if sys.platform == "win32":
            self.assertIsInstance(value, dt.datetime)
            self.assertLessEqual(value, dt.datetime.now() + dt.timedelta(minutes=1))
        else:
            self.assertTrue(value is None or isinstance(value, dt.datetime))


if __name__ == "__main__":
    unittest.main()
