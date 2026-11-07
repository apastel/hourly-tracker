"""SQLite storage for settings and away events."""

from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass
from pathlib import Path


def _dump(value: dt.datetime) -> str:
    return value.replace(microsecond=0).isoformat(timespec="seconds")


def _load(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value)


@dataclass(frozen=True)
class AwayEvent:
    id: int
    kind: str
    started_at: dt.datetime
    ended_at: dt.datetime | None


class Storage:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=3000")
        self._create()

    def close(self) -> None:
        self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.conn.close()

    def _create(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS away_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL CHECK (kind IN ('idle', 'offline')),
                started_at TEXT NOT NULL,
                ended_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_away_started
                ON away_events(started_at);
            """
        )
        self.conn.commit()

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return default
        return str(row["value"])

    def delete_setting(self, key: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM settings WHERE key = ?", (key,))

    def set_setting(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO settings(key, value) VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def get_heartbeat(self) -> dt.datetime | None:
        raw = self.get_setting("heartbeat")
        if not raw:
            return None
        return _load(raw)

    def set_heartbeat(self, when: dt.datetime) -> None:
        self.set_setting("heartbeat", _dump(when))

    def add_event(
        self,
        kind: str,
        started_at: dt.datetime,
        ended_at: dt.datetime | None,
    ) -> AwayEvent:
        ended = None if ended_at is None else _dump(ended_at)
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO away_events(kind, started_at, ended_at)
                VALUES(?, ?, ?)
                """,
                (kind, _dump(started_at), ended),
            )
            event_id = int(cursor.lastrowid)
        event = self.get_event(event_id)
        if event is None:
            raise RuntimeError(f"Away event {event_id} was not saved")
        return event

    def get_event(self, event_id: int) -> AwayEvent | None:
        row = self.conn.execute(
            "SELECT * FROM away_events WHERE id = ?",
            (event_id,),
        ).fetchone()
        if row is None:
            return None
        return self._event_from_row(row)

    def update_event(
        self,
        event_id: int,
        kind: str,
        started_at: dt.datetime,
        ended_at: dt.datetime | None,
    ) -> None:
        ended = None if ended_at is None else _dump(ended_at)
        with self.conn:
            cursor = self.conn.execute(
                """
                UPDATE away_events
                SET kind = ?, started_at = ?, ended_at = ?
                WHERE id = ?
                """,
                (kind, _dump(started_at), ended, event_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(event_id)

    def close_event(self, event_id: int, ended_at: dt.datetime) -> None:
        with self.conn:
            cursor = self.conn.execute(
                """
                UPDATE away_events
                SET ended_at = ?
                WHERE id = ? AND ended_at IS NULL
                """,
                (_dump(ended_at), event_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(event_id)

    def delete_event(self, event_id: int) -> None:
        with self.conn:
            cursor = self.conn.execute(
                "DELETE FROM away_events WHERE id = ?",
                (event_id,),
            )
            if cursor.rowcount != 1:
                raise KeyError(event_id)

    def open_events(self) -> list[AwayEvent]:
        rows = self.conn.execute(
            """
            SELECT * FROM away_events
            WHERE ended_at IS NULL
            ORDER BY started_at
            """
        ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def events_overlapping(
        self,
        window_start: dt.datetime,
        window_end: dt.datetime,
    ) -> list[AwayEvent]:
        rows = self.conn.execute(
            """
            SELECT * FROM away_events
            WHERE started_at < ?
              AND (ended_at IS NULL OR ended_at > ?)
            ORDER BY started_at
            """,
            (_dump(window_end), _dump(window_start)),
        ).fetchall()
        return [self._event_from_row(row) for row in rows]

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> AwayEvent:
        ended = row["ended_at"]
        return AwayEvent(
            id=int(row["id"]),
            kind=str(row["kind"]),
            started_at=_load(str(row["started_at"])),
            ended_at=None if ended is None else _load(str(ended)),
        )
