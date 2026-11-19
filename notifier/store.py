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
CREATE TABLE IF NOT EXISTS applications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT UNIQUE,          -- links to jobs.id; NULL for manually added applications
    company     TEXT NOT NULL,
    title       TEXT NOT NULL,
    url         TEXT NOT NULL DEFAULT '',
    location    TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'saved',
    applied_at  TEXT,                 -- YYYY-MM-DD
    follow_up   TEXT,                 -- YYYY-MM-DD
    contact     TEXT NOT NULL DEFAULT '',
    salary      TEXT NOT NULL DEFAULT '',
    notes       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
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
        self._migrate_statuses()

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

    # ---- hidden jobs ---------------------------------------------------------------------
    def hidden_ids(self) -> set[str]:
        return {r["job_id"] for r in self.conn.execute("SELECT job_id FROM job_status WHERE status = 'hidden'")}

    def set_hidden(self, job_id: str, hidden: bool) -> None:
        if hidden:
            self.conn.execute("INSERT OR REPLACE INTO job_status (job_id, status) VALUES (?, 'hidden')", (job_id,))
        else:
            self.conn.execute("DELETE FROM job_status WHERE job_id = ?", (job_id,))
        self.conn.commit()

    def _migrate_statuses(self) -> None:
        """Older versions kept saved/applied in job_status; move them into applications."""
        old = self.conn.execute("SELECT job_id, status FROM job_status WHERE status IN ('saved','applied')").fetchall()
        for r in old:
            self.track_job(r["job_id"], r["status"])
        if old:
            self.conn.execute("DELETE FROM job_status WHERE status IN ('saved','applied')")
            self.conn.commit()

    # ---- applications --------------------------------------------------------------------
    STAGES = ("saved", "applied", "oa", "interview", "offer", "rejected", "withdrawn")
    FIELDS = ("company", "title", "url", "location", "status", "applied_at", "follow_up", "contact", "salary", "notes")

    def applications(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM applications ORDER BY updated_at DESC").fetchall()
        return [dict(r) for r in rows]

    def track_job(self, job_id: str, status: str) -> int | None:
        """Start (or move) tracking a crawled job. Returns the application id."""
        job = self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if job is None:
            return None
        now = self._now()
        today = now[:10]
        existing = self.conn.execute("SELECT id, applied_at FROM applications WHERE job_id = ?", (job_id,)).fetchone()
        if existing:
            applied = existing["applied_at"] or (today if status != "saved" else None)
            self.conn.execute("UPDATE applications SET status=?, applied_at=?, updated_at=? WHERE id=?",
                              (status, applied, now, existing["id"]))
            self.conn.commit()
            return existing["id"]
        cur = self.conn.execute(
            "INSERT INTO applications (job_id, company, title, url, location, status, applied_at, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (job_id, job["company"], job["title"], job["url"], job["location"], status,
             today if status != "saved" else None, now, now))
        self.conn.commit()
        return cur.lastrowid

    def add_application(self, data: dict) -> int:
        now = self._now()
        status = data.get("status") if data.get("status") in self.STAGES else "saved"
        cur = self.conn.execute(
            "INSERT INTO applications (company, title, url, location, status, applied_at, follow_up, contact,"
            " salary, notes, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (data.get("company", "").strip() or "Unknown", data.get("title", "").strip() or "Untitled",
             data.get("url", ""), data.get("location", ""), status,
             data.get("applied_at") or (now[:10] if status != "saved" else None), data.get("follow_up") or None,
             data.get("contact", ""), data.get("salary", ""), data.get("notes", ""), now, now))
        self.conn.commit()
        return cur.lastrowid

    def update_application(self, app_id: int, data: dict) -> bool:
        sets, args = [], []
        for k in self.FIELDS:
            if k not in data:
                continue
            v = data[k]
            if k == "status" and v not in self.STAGES:
                continue
            if k in ("applied_at", "follow_up"):
                v = v or None
            elif not isinstance(v, str):
                continue
            sets.append(f"{k} = ?")
            args.append(v)
        if not sets:
            return False
        if data.get("status") in ("applied", "oa", "interview", "offer") and "applied_at" not in data:
            sets.append("applied_at = COALESCE(applied_at, ?)")
            args.append(self._now()[:10])
        sets.append("updated_at = ?")
        args += [self._now(), app_id]
        cur = self.conn.execute(f"UPDATE applications SET {', '.join(sets)} WHERE id = ?", args)
        self.conn.commit()
        return cur.rowcount == 1

    def delete_application(self, app_id: int) -> None:
        self.conn.execute("DELETE FROM applications WHERE id = ?", (app_id,))
        self.conn.commit()

    def application_job_ids(self) -> dict[str, dict]:
        return {r["job_id"]: {"id": r["id"], "status": r["status"]}
                for r in self.conn.execute("SELECT id, job_id, status FROM applications WHERE job_id IS NOT NULL")}

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
