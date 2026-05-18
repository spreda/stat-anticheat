"""
SQLite database for job tracking.
"""
import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent.parent / "uploads" / "jobs.db"


def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            file_path TEXT NOT NULL,
            filename TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            result TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def create_job(job_id: str, file_path: str, filename: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO jobs (id, file_path, filename) VALUES (?, ?, ?)",
        (job_id, file_path, filename)
    )
    conn.commit()
    conn.close()


def update_job(job_id: str, status: str, result: str | None = None):
    conn = get_conn()
    conn.execute(
        "UPDATE jobs SET status = ?, result = ?, updated_at = ? WHERE id = ?",
        (status, result, datetime.utcnow().isoformat(), job_id)
    )
    conn.commit()
    conn.close()


def get_job(job_id: str) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_job_stats() -> dict:
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) as c FROM jobs").fetchone()["c"]
    done = conn.execute("SELECT COUNT(*) as c FROM jobs WHERE status = 'done'").fetchone()["c"]
    error = conn.execute("SELECT COUNT(*) as c FROM jobs WHERE status = 'error'").fetchone()["c"]
    avg = conn.execute("SELECT AVG(CAST((julianday(updated_at) - julianday(created_at)) * 86400 AS REAL)) as avg FROM jobs WHERE status IN ('done','error') AND updated_at IS NOT NULL AND created_at IS NOT NULL").fetchone()["avg"]
    conn.close()
    return {
        "total_jobs": total,
        "done_jobs": done,
        "error_jobs": error,
        "avg_time": round(avg or 0, 1),
    }
