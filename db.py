"""
db.py – Lightweight SQLite persistence for submission results.

Each row tracks one URL attempt: status, timestamp, and free-text notes.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS submissions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            url         TEXT    NOT NULL,
            status      TEXT    NOT NULL DEFAULT 'pending',
            submitted_at TEXT,
            notes       TEXT
        )
        """
    )
    conn.commit()
    return conn


class ResultsDB:
    """Thin wrapper around the submissions table."""

    def __init__(self, db_path: Path) -> None:
        self._conn = _connect(db_path)

    # ── Write ─────────────────────────────────────────────────
    def upsert(
        self,
        url: str,
        status: str,
        notes: Optional[str] = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT INTO submissions (url, status, submitted_at, notes)
            VALUES (?, ?, ?, ?)
            """,
            (url, status, now, notes),
        )
        self._conn.commit()

    # ── Read ──────────────────────────────────────────────────
    def all_rows(self) -> list[tuple]:
        cur = self._conn.execute(
            "SELECT id, url, status, submitted_at, notes FROM submissions ORDER BY id"
        )
        return cur.fetchall()

    def close(self) -> None:
        self._conn.close()
