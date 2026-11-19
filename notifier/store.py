from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

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
CREATE TABLE IF NOT EXISTS companies (
    name       TEXT PRIMARY KEY,
    first_crawl TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS job_status (
    job_id TEXT PRIMARY KEY,
    status TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: str = "jobs.db"):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(jobs)")}
        if "posted_at" not in cols:
            self.conn.execute("ALTER TABLE jobs ADD COLUMN posted_at TEXT")

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def upsert(self, job: Job, matched: bool) -> bool:
        """Insert the job if unseen. Returns True when it is new."""
        now = self._now()
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO jobs (id, company, title, url, location, matched, first_seen, last_seen, posted_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (job.id, job.company, job.title, job.url, job.location, int(matched), now, now, job.posted_at),
        )
        is_new = cur.rowcount == 1
        if not is_new:
            self.conn.execute(
                "UPDATE jobs SET last_seen = ?, matched = ?, posted_at = COALESCE(?, posted_at) WHERE id = ?",
                (now, int(matched), job.posted_at, job.id),
            )
        return is_new

    def first_crawl(self, company: str) -> bool:
        """Record that `company` has been crawled. Returns True the first time."""
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO companies (name, first_crawl) VALUES (?, ?)", (company, self._now())
        )
        return cur.rowcount == 1

    def commit(self) -> None:
        self.conn.commit()

    def matched_jobs(self, since_hours: float | None = None) -> list[sqlite3.Row]:
        """Matching jobs, newest first. `since_hours` keeps only those posted within that window,
        using the board's posting date when known and otherwise when we first saw it."""
        sql = "SELECT *, COALESCE(posted_at, first_seen) AS posted FROM jobs WHERE matched = 1"
        args: tuple = ()
        if since_hours is not None:
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat(timespec="seconds")
            sql += " AND COALESCE(posted_at, first_seen) >= ?"
            args = (cutoff,)
        return self.conn.execute(sql + " ORDER BY posted DESC, company, title", args).fetchall()

    def statuses(self) -> dict[str, str]:
        return {r["job_id"]: r["status"] for r in self.conn.execute("SELECT job_id, status FROM job_status")}

    def set_status(self, job_id: str, status: str | None) -> None:
        if status:
            self.conn.execute(
                "INSERT INTO job_status (job_id, status) VALUES (?, ?) "
                "ON CONFLICT(job_id) DO UPDATE SET status = excluded.status",
                (job_id, status),
            )
        else:
            self.conn.execute("DELETE FROM job_status WHERE job_id = ?", (job_id,))
        self.conn.commit()

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
