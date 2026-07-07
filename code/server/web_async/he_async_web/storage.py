"""SQLite job metadata and filesystem artifact helpers."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .job_types import JOB_TYPES, visible_job_types
from .settings import Settings


DB_LOCK = threading.Lock()


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def job_dir(settings: Settings, job_id: str) -> Path:
    return settings.jobs_dir / job_id


def work_dir(settings: Settings, job_id: str) -> Path:
    return job_dir(settings, job_id) / "work"


def log_path(settings: Settings, job_id: str) -> Path:
    return job_dir(settings, job_id) / "server_log.txt"


def output_dir(settings: Settings, job_id: str) -> Path:
    return work_dir(settings, job_id) / "output"


def result_bundle_path(settings: Settings, job_id: str) -> Path:
    return job_dir(settings, job_id) / "result_bundle.zip"


def connect(settings: Settings) -> sqlite3.Connection:
    settings.jobs_dir.mkdir(parents=True, exist_ok=True)
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(settings: Settings) -> None:
    with DB_LOCK, connect(settings) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                rq_job_id TEXT,
                job_type TEXT NOT NULL,
                label TEXT NOT NULL,
                scheme TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                note TEXT,
                input_file_count INTEGER DEFAULT 0,
                input_bytes INTEGER DEFAULT 0,
                output_bytes INTEGER DEFAULT 0,
                worker TEXT,
                command_json TEXT,
                input_files_json TEXT,
                output_files_json TEXT,
                result_bundle TEXT,
                error TEXT,
                returncode INTEGER
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at)")


def _row_to_job(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["command"] = json.loads(item.pop("command_json") or "[]")
    item["input_files"] = json.loads(item.pop("input_files_json") or "[]")
    item["output_files"] = json.loads(item.pop("output_files_json") or "[]")
    return item


def create_job_record(
    settings: Settings,
    *,
    job_id: str,
    job_type: str,
    note: str,
    input_files: list[str],
    input_bytes: int,
) -> dict[str, Any]:
    cfg = JOB_TYPES[job_type]
    created = now_iso()
    with DB_LOCK, connect(settings) as conn:
        conn.execute(
            """
            INSERT INTO jobs (
                job_id, job_type, label, scheme, status, created_at, updated_at,
                note, input_file_count, input_bytes, input_files_json, output_files_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                job_type,
                cfg["label"],
                cfg["scheme"],
                "uploaded",
                created,
                created,
                note,
                len(input_files),
                input_bytes,
                json.dumps(input_files),
                "[]",
            ),
        )
    return get_job(settings, job_id)


def update_job(settings: Settings, job_id: str, **updates: Any) -> dict[str, Any]:
    if not updates:
        return get_job(settings, job_id)
    updates["updated_at"] = now_iso()
    normalized: dict[str, Any] = {}
    for key, value in updates.items():
        if key == "command":
            normalized["command_json"] = json.dumps(value)
        elif key == "input_files":
            normalized["input_files_json"] = json.dumps(value)
        elif key == "output_files":
            normalized["output_files_json"] = json.dumps(value)
        else:
            normalized[key] = value
    assignments = ", ".join(f"{key} = ?" for key in normalized)
    values = list(normalized.values()) + [job_id]
    with DB_LOCK, connect(settings) as conn:
        conn.execute(f"UPDATE jobs SET {assignments} WHERE job_id = ?", values)
    return get_job(settings, job_id)


def get_job(settings: Settings, job_id: str) -> dict[str, Any]:
    with connect(settings) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    if row is None:
        raise KeyError(f"job not found: {job_id}")
    return _row_to_job(row)


def list_jobs(settings: Settings, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 500))
    with connect(settings) as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [_row_to_job(row) for row in rows]


def list_completed_jobs(settings: Settings, *, limit: int = 100) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 500))
    with connect(settings) as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE status = 'succeeded' ORDER BY finished_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_row_to_job(row) for row in rows]


def list_output_files(settings: Settings, job_id: str) -> list[str]:
    root = output_dir(settings, job_id)
    if not root.exists():
        return []
    return [path.relative_to(root).as_posix() for path in sorted(root.rglob("*")) if path.is_file()]


def directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def use_case_results(settings: Settings) -> list[dict[str, Any]]:
    jobs = list_jobs(settings, limit=500)
    grouped: dict[str, dict[str, Any]] = {}
    for job_type, cfg in visible_job_types().items():
        grouped[job_type] = {
            "job_type": job_type,
            "label": cfg["label"],
            "family": cfg.get("family", ""),
            "scheme": cfg.get("scheme", ""),
            "latest_job_id": "",
            "latest_status": "not_started",
            "latest_updated_at": "",
            "latest_output_files": [],
            "counts": {},
        }

    for job in jobs:
        item = grouped.get(str(job.get("job_type", "")))
        if not item:
            continue
        status = str(job.get("status", "unknown"))
        item["counts"][status] = item["counts"].get(status, 0) + 1
        updated = str(job.get("updated_at", ""))
        if updated >= item["latest_updated_at"]:
            item["latest_job_id"] = job.get("job_id", "")
            item["latest_status"] = status
            item["latest_updated_at"] = updated
            item["latest_output_files"] = job.get("output_files", [])
    return list(grouped.values())
