"""
SQLite database for job tracking.
"""
import json
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


def reset_stale_jobs():
    """Reset jobs stuck in pending/processing after server restart."""
    conn = get_conn()
    msg = json.dumps({"status": "error", "message": "Сервер был перезапущен. Запустите анализ снова."})
    conn.execute(
        "UPDATE jobs SET status = 'error', result = ?, updated_at = ? WHERE status IN ('pending','processing')",
        (msg, datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()


def get_active_job(filename: str) -> dict | None:
    """Return the first pending/processing job for a filename, or None."""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM jobs WHERE filename = ? AND status IN ('pending','processing') ORDER BY created_at DESC LIMIT 1",
        (filename,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


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
