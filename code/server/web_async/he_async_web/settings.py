"""Runtime settings for the async HE web server."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]


def _path_from_env(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    if not value:
        return default
    return Path(value).expanduser().resolve()


@dataclass(frozen=True)
class Settings:
    repo_root: Path = REPO_ROOT
    jobs_dir: Path = _path_from_env("HE_ASYNC_JOBS_DIR", REPO_ROOT / "server_jobs" / "async")
    build_dir: Path = _path_from_env("HE_ASYNC_BUILD_DIR", REPO_ROOT / "build")
    db_path: Path = _path_from_env(
        "HE_ASYNC_DB_PATH",
        _path_from_env("HE_ASYNC_JOBS_DIR", REPO_ROOT / "server_jobs" / "async") / "jobs.db",
    )
    redis_url: str = os.environ.get("HE_REDIS_URL", "redis://127.0.0.1:6379/0")
    queue_name: str = os.environ.get("HE_ASYNC_QUEUE", "he-jobs")
    auth_token: str = os.environ.get("HE_RECEIVER_TOKEN", "")
    max_upload_bytes: int = int(os.environ.get("HE_WEB_MAX_UPLOAD_BYTES", str(512 * 1024 * 1024)))
    job_timeout_seconds: int = int(os.environ.get("HE_ASYNC_JOB_TIMEOUT_SECONDS", str(6 * 60 * 60)))
    log_tail_bytes: int = int(os.environ.get("HE_ASYNC_LOG_TAIL_BYTES", str(96 * 1024)))
    result_ttl_seconds: int = int(os.environ.get("HE_ASYNC_RESULT_TTL_SECONDS", str(7 * 24 * 60 * 60)))


def get_settings() -> Settings:
    return Settings()

