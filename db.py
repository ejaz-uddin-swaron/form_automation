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
            company     TEXT,
            status      TEXT    NOT NULL DEFAULT 'pending',
            submitted_at TEXT,
            notes       TEXT
        )
        """
    )
    # Check if 'company' column exists for backward compatibility
    cur = conn.execute("PRAGMA table_info(submissions)")
    cols = [row[1] for row in cur.fetchall()]
    if "company" not in cols:
        conn.execute("ALTER TABLE submissions ADD COLUMN company TEXT")
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
        company: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT INTO submissions (url, company, status, submitted_at, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (url, company, status, now, notes),
        )
        self._conn.commit()

    # ── Read ──────────────────────────────────────────────────
    def is_already_done(self, url: str) -> bool:
        """Check if this URL was already successfully submitted or resolved."""
        cur = self._conn.execute(
            "SELECT 1 FROM submissions WHERE url = ? AND status IN ('submitted', 'captcha_blocked', 'no_form') LIMIT 1",
            (url,),
        )
        return cur.fetchone() is not None

    def all_rows(self) -> list[tuple]:
        cur = self._conn.execute(
            "SELECT id, url, company, status, submitted_at, notes FROM submissions ORDER BY id"
        )
        return cur.fetchall()

    def close(self) -> None:
        self._conn.close()
