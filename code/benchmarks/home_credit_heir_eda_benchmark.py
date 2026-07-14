#!/usr/bin/env python3
"""Compatibility entrypoint for the HEIR Home Credit EDA benchmark."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from code.heir.home_credit.scripts.run_kernel_benchmark import main  # noqa: E402


if __name__ == "__main__":
    main()

