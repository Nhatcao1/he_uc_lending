"""Execution helpers that wrap existing C++ OpenFHE server binaries."""

from __future__ import annotations

import json
import socket
import subprocess
import zipfile
from pathlib import Path

from .job_types import JOB_TYPES
from .settings import Settings, get_settings
from .storage import (
    directory_size,
    get_job,
    job_dir,
    list_output_files,
    log_path,
    now_iso,
    output_dir,
    result_bundle_path,
    update_job,
    work_dir,
)


def validate_required_files(settings: Settings, job_id: str) -> None:
    job = get_job(settings, job_id)
    cfg = JOB_TYPES[job["job_type"]]
    root = work_dir(settings, job_id)
    missing: list[str] = []
    for item in cfg["required"]:
        if item.endswith("/"):
            if not (root / item.rstrip("/")).is_dir():
                missing.append(item)
        elif not (root / item).is_file():
            missing.append(item)
    if missing:
        raise ValueError(f"missing required encrypted artifacts: {', '.join(missing)}")


def build_command(settings: Settings, job_id: str) -> list[str]:
    job = get_job(settings, job_id)
    cfg = JOB_TYPES[job["job_type"]]
    executable = settings.build_dir / str(cfg["binary"])
    if not executable.exists():
        raise FileNotFoundError(f"missing build executable: {executable}")

    root = work_dir(settings, job_id)
    command = [str(executable)]
    for arg in cfg["command"]:
        if str(arg).startswith("--"):
            command.append(str(arg))
        elif str(arg).startswith("literal:"):
            command.append(str(arg).split(":", 1)[1])
        else:
            command.append(str(root / str(arg)))
    return command


def create_result_bundle(settings: Settings, job_id: str) -> Path:
    job = get_job(settings, job_id)
    bundle_path = result_bundle_path(settings, job_id)
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    out_root = output_dir(settings, job_id)
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("job_status.json", json.dumps(job, indent=2))
        job_log = log_path(settings, job_id)
        if job_log.exists():
            bundle.write(job_log, "server_log.txt")
        if out_root.exists():
            for path in sorted(out_root.rglob("*")):
                if path.is_file():
                    bundle.write(path, path.relative_to(out_root).as_posix())
    return bundle_path


def run_cpp_job(job_id: str, settings: Settings | None = None) -> dict[str, object]:
    settings = settings or get_settings()
    job = get_job(settings, job_id)
    if job["status"] == "cancelled":
        return job

    try:
        validate_required_files(settings, job_id)
        command = build_command(settings, job_id)
        update_job(
            settings,
            job_id,
            status="running",
            started_at=now_iso(),
            worker=socket.gethostname(),
            command=command,
            error=None,
        )

        job_log = log_path(settings, job_id)
        job_log.parent.mkdir(parents=True, exist_ok=True)
        with job_log.open("w", encoding="utf-8") as log:
            log.write("$ " + " ".join(command) + "\n\n")
            proc = subprocess.run(
                command,
                cwd=settings.repo_root,
                text=True,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )

        outputs = list_output_files(settings, job_id)
        out_bytes = directory_size(output_dir(settings, job_id))
        if proc.returncode != 0:
            return update_job(
                settings,
                job_id,
                status="failed",
                finished_at=now_iso(),
                returncode=proc.returncode,
                output_files=outputs,
                output_bytes=out_bytes,
                error=f"server binary exited with {proc.returncode}",
            )

        bundle = create_result_bundle(settings, job_id)
        return update_job(
            settings,
            job_id,
            status="succeeded",
            finished_at=now_iso(),
            returncode=proc.returncode,
            output_files=outputs,
            output_bytes=out_bytes,
            result_bundle=str(bundle),
            error=None,
        )
    except Exception as exc:  # noqa: BLE001 - user needs the failed status in UI
        return update_job(settings, job_id, status="failed", finished_at=now_iso(), error=str(exc))


def read_log_tail(settings: Settings, job_id: str) -> str:
    path = log_path(settings, job_id)
    if not path.exists():
        return ""
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > settings.log_tail_bytes:
            handle.seek(size - settings.log_tail_bytes)
        return handle.read().decode("utf-8", errors="replace")

