"""SQLite persistence helpers for agent sessions, memories, and crisis logs."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

_DB_PATH: Path | None = None


def init_db(db_path: Path) -> None:
    """Initialize the SQLite database and create required tables."""
    global _DB_PATH

    _DB_PATH = Path(db_path)
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                started_at TEXT NOT NULL,
                last_active_at TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL DEFAULT 0,
                turn_count INTEGER NOT NULL DEFAULT 0,
                summary TEXT,
                risk_flags TEXT NOT NULL DEFAULT '[]'
            );

            CREATE TABLE IF NOT EXISTS memory_entries (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                content TEXT NOT NULL,
                memory_type TEXT NOT NULL,
                confidence REAL NOT NULL,
                source_turn INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS crisis_events (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                risk_level TEXT NOT NULL,
                matched_pattern TEXT,
                user_input_hash TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                human_handoff_status TEXT NOT NULL DEFAULT 'pending'
            );

            CREATE INDEX IF NOT EXISTS idx_memory_entries_user_updated
                ON memory_entries (user_id, updated_at DESC);

            CREATE INDEX IF NOT EXISTS idx_crisis_events_user_occurred
                ON crisis_events (user_id, occurred_at DESC);
            """
        )


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    """Open a SQLite connection and commit or roll back the transaction."""
    if _DB_PATH is None:
        raise RuntimeError("call init_db() before using database helpers")

    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_session(session_id: str, user_id: str) -> None:
    now = _now()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO sessions (id, user_id, started_at, last_active_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                user_id = excluded.user_id,
                last_active_at = excluded.last_active_at
            """,
            (session_id, user_id, now, now),
        )


def update_session_turn(session_id: str, duration_minutes: int) -> None:
    with _connect() as conn:
        conn.execute(
            """
            UPDATE sessions
            SET turn_count = turn_count + 1,
                duration_minutes = ?,
                last_active_at = ?
            WHERE id = ?
            """,
            (duration_minutes, _now(), session_id),
        )


def save_session_summary(session_id: str, summary: str) -> None:
    with _connect() as conn:
        conn.execute(
            """
            UPDATE sessions
            SET summary = ?,
                last_active_at = ?
            WHERE id = ?
            """,
            (summary, _now(), session_id),
        )


def insert_memory(
    entry_id: str,
    user_id: str,
    session_id: str,
    content: str,
    memory_type: str,
    confidence: float,
    source_turn: int,
) -> None:
    now = _now()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO memory_entries (
                id,
                user_id,
                session_id,
                content,
                memory_type,
                confidence,
                source_turn,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry_id,
                user_id,
                session_id,
                content,
                memory_type,
                confidence,
                source_turn,
                now,
                now,
            ),
        )


def get_memories(user_id: str, limit: int = 20) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                user_id,
                session_id,
                content,
                memory_type,
                confidence,
                source_turn,
                created_at,
                updated_at
            FROM memory_entries
            WHERE user_id = ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()

    return [dict(row) for row in rows]


def log_crisis_event(
    event_id: str,
    user_id: str,
    session_id: str,
    risk_level: str,
    matched_pattern: str | None,
    user_input_hash: str,
) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO crisis_events (
                id,
                user_id,
                session_id,
                risk_level,
                matched_pattern,
                user_input_hash,
                occurred_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                user_id,
                session_id,
                risk_level,
                matched_pattern,
                user_input_hash,
                _now(),
            ),
        )
