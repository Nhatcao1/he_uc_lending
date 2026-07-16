#!/usr/bin/env python3
"""Compatibility entrypoint for one-pair full HEIR CKKS Pearson benchmark."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from code.heir.home_credit.scripts.run_full_pearson_benchmark import main  # noqa: E402

if __name__ == "__main__":
    main()
