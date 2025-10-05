"""Low-level SQLite access."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


class Database:
    """Encapsulates access to the SQLite database file."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def initialise(self) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS log_webhook (
                    wa_id TEXT PRIMARY KEY,
                    input TEXT NOT NULL,
                    message TEXT NOT NULL,
                    status TEXT NOT NULL,
                    timestamp TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS log_answers (
                    wa_id TEXT NOT NULL,
                    answer TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS flow_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wa_id TEXT NOT NULL,
                    flow_name TEXT NOT NULL,
                    step_index INTEGER NOT NULL DEFAULT 0,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    context TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY (wa_id) REFERENCES log_webhook (wa_id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_flow_sessions_wa_flow
                ON flow_sessions (wa_id, flow_name)
                """
            )
            if not _column_exists(conn, "log_webhook", "timestamp"):
                conn.execute("ALTER TABLE log_webhook ADD COLUMN timestamp TEXT")
            conn.commit()
