"""SQLite store. Remembers every job ever fetched so each run can report
only the ones it hasn't seen before.

All fetched jobs are stored, not just the ones passing the filters, so
changing filters later still works against your full history.
"""

import sqlite3
from dataclasses import astuple, fields
from datetime import datetime

from .models import Job

JOB_COLUMNS = [f.name for f in fields(Job)]

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id            TEXT PRIMARY KEY,
    source        TEXT NOT NULL,
    company       TEXT NOT NULL,
    title         TEXT NOT NULL,
    location      TEXT NOT NULL,
    country       TEXT,
    remote        INTEGER NOT NULL,
    posted_on     TEXT,
    url           TEXT NOT NULL,
    work_auth     TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_first_seen ON jobs (first_seen_at);
"""


class Store:
    def __init__(self, path):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self):
        """Add columns introduced after a database was first created."""
        existing = {r["name"] for r in self.conn.execute("PRAGMA table_info(jobs)")}
        with self.conn:
            for column in JOB_COLUMNS:
                if column not in existing:
                    self.conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} TEXT")

    def upsert(self, jobs: list[Job]) -> list[Job]:
        """Save jobs; return the ones that were never seen before."""
        now = datetime.now().isoformat(timespec="seconds")
        new = []
        with self.conn:
            for job in jobs:
                exists = self.conn.execute("SELECT 1 FROM jobs WHERE id = ?", (job.id,)).fetchone()
                if exists:
                    self.conn.execute(
                        f"UPDATE jobs SET {', '.join(c + ' = ?' for c in JOB_COLUMNS[1:])}, last_seen_at = ? WHERE id = ?",
                        (*astuple(job)[1:], now, job.id),
                    )
                else:
                    self.conn.execute(
                        f"INSERT INTO jobs ({', '.join(JOB_COLUMNS)}, first_seen_at, last_seen_at) "
                        f"VALUES ({', '.join('?' * (len(JOB_COLUMNS) + 2))})",
                        (*astuple(job), now, now),
                    )
                    new.append(job)
        return new

    def all_jobs(self) -> list[tuple[Job, str]]:
        """Every stored job with its first_seen_at, newest posting first."""
        rows = self.conn.execute(
            "SELECT * FROM jobs ORDER BY posted_on DESC, first_seen_at DESC"
        ).fetchall()
        return [
            (Job(**{c: (bool(r[c]) if c == "remote" else r[c]) for c in JOB_COLUMNS}), r["first_seen_at"])
            for r in rows
        ]

    def close(self):
        self.conn.close()
