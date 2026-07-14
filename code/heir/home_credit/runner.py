"""Command adapter for server-side HEIR experiments."""

from __future__ import annotations

import shlex
import subprocess
import time
from pathlib import Path
from typing import Any


def run_command(command: list[str], cwd: Path) -> tuple[float, str]:
    started = time.perf_counter()
    completed = subprocess.run(command, cwd=cwd, check=True, text=True, capture_output=True)  # noqa: S603
    elapsed = time.perf_counter() - started
    return elapsed, completed.stdout + completed.stderr


def run_template(command_template: str, context: dict[str, Any], cwd: Path) -> tuple[float, str]:
    command = command_template.format(**context)
    return run_command(shlex.split(command), cwd)


def probe_tool(command: list[str], cwd: Path) -> tuple[float, str, str]:
    started = time.perf_counter()
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True)  # noqa: S603
    elapsed = time.perf_counter() - started
    output = completed.stdout + completed.stderr
    status = "ok" if completed.returncode == 0 else f"exit_{completed.returncode}"
    return elapsed, status, output
