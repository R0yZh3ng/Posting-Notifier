from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .models import Job

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id         TEXT PRIMARY KEY,
    company    TEXT NOT NULL,
    title      TEXT NOT NULL,
    url        TEXT NOT NULL,
    location   TEXT NOT NULL DEFAULT '',
    matched    INTEGER NOT NULL DEFAULT 0,
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: str = "jobs.db"):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def upsert(self, job: Job, matched: bool) -> bool:
        """Insert the job if unseen. Returns True when it is new."""
        now = self._now()
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO jobs (id, company, title, url, location, matched, first_seen, last_seen)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (job.id, job.company, job.title, job.url, job.location, int(matched), now, now),
        )
        is_new = cur.rowcount == 1
        if not is_new:
            self.conn.execute("UPDATE jobs SET last_seen = ?, matched = ? WHERE id = ?", (now, int(matched), job.id))
        return is_new

    def commit(self) -> None:
        self.conn.commit()

    def matched_jobs(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM jobs WHERE matched = 1 ORDER BY first_seen DESC, company, title"
        ).fetchall()

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
