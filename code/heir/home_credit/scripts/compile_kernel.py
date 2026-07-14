#!/usr/bin/env python3
"""Create a HEIR kernel request package from a Home Credit workload spec.

This is intentionally a lightweight adapter. It does not assume a specific
server HEIR binary name. The generated JSON gives the server-side HEIR wrapper a
stable contract to compile the first fixed-shape kernel.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from code.heir.home_credit.kernels.masked_default_count import KERNEL_INTENT  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write HEIR kernel request metadata.")
    parser.add_argument("--spec", required=True, help="Path to heir_workload_spec.json.")
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    spec_path = Path(args.spec)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    kernel = str(spec.get("kernel", "masked_default_count"))
    request = {
        "kernel": kernel,
        "intent": KERNEL_INTENT.get(kernel, ""),
        "workload": spec.get("workload"),
        "column": spec.get("column"),
        "tensor_manifest": spec.get("tensor_manifest"),
        "inputs": [
            {"name": "group_mask", "encrypted": True, "shape": ["rows"], "dtype": "f64-or-ckks"},
            {"name": "target_mask", "encrypted": True, "shape": ["rows"], "dtype": "f64-or-ckks"},
        ],
        "outputs": [
            {"name": "group_count", "encrypted": True, "dtype": "f64-or-ckks"},
            {"name": "default_count", "encrypted": True, "dtype": "f64-or-ckks"},
        ],
        "pseudocode": [
            "group_count = sum(group_mask)",
            "default_count = sum(group_mask * target_mask)",
        ],
    }
    (output_dir / "heir_kernel_request.json").write_text(json.dumps(request, indent=2), encoding="utf-8")
    print(json.dumps(request, indent=2))


if __name__ == "__main__":
    main()
