import sqlite3
from pathlib import Path
from typing import Optional

from config import DATABASE_PATH, DEFAULT_TIMEZONE


def _connect() -> sqlite3.Connection:
    Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS work_sessions (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                work_date  TEXT    NOT NULL,
                check_in   TEXT,
                check_out  TEXT,
                UNIQUE(user_id, work_date)
            );
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id  INTEGER PRIMARY KEY,
                timezone TEXT NOT NULL DEFAULT 'Europe/Moscow'
            );
        """)


def get_user_timezone(user_id: int) -> str:
    with _connect() as conn:
        row = conn.execute(
            "SELECT timezone FROM user_settings WHERE user_id = ?", (user_id,)
        ).fetchone()
    return row["timezone"] if row else DEFAULT_TIMEZONE


def set_user_timezone(user_id: int, tz: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO user_settings (user_id, timezone) VALUES (?, ?)"
            " ON CONFLICT(user_id) DO UPDATE SET timezone = excluded.timezone",
            (user_id, tz),
        )


def upsert_check_in(user_id: int, work_date: str, check_in_utc: str) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO work_sessions (user_id, work_date, check_in)
               VALUES (?, ?, ?)
               ON CONFLICT(user_id, work_date)
               DO UPDATE SET check_in = excluded.check_in""",
            (user_id, work_date, check_in_utc),
        )


def upsert_check_out(user_id: int, work_date: str, check_out_utc: str) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO work_sessions (user_id, work_date, check_out)
               VALUES (?, ?, ?)
               ON CONFLICT(user_id, work_date)
               DO UPDATE SET check_out = excluded.check_out""",
            (user_id, work_date, check_out_utc),
        )


def get_session(user_id: int, work_date: str) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM work_sessions WHERE user_id = ? AND work_date = ?",
            (user_id, work_date),
        ).fetchone()
    return dict(row) if row else None


def get_sessions_range(user_id: int, date_from: str, date_to: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """SELECT * FROM work_sessions
               WHERE user_id = ? AND work_date >= ? AND work_date <= ?
               ORDER BY work_date""",
            (user_id, date_from, date_to),
        ).fetchall()
    return [dict(r) for r in rows]
