"""Command adapter for server-side HEIR experiments."""

from __future__ import annotations

import shlex
import subprocess
import time
from pathlib import Path
from typing import Any


def run_template(command_template: str, context: dict[str, Any], cwd: Path) -> tuple[float, str]:
    command = command_template.format(**context)
    started = time.perf_counter()
    completed = subprocess.run(shlex.split(command), cwd=cwd, check=True, text=True, capture_output=True)  # noqa: S603
    elapsed = time.perf_counter() - started
    return elapsed, completed.stdout + completed.stderr

