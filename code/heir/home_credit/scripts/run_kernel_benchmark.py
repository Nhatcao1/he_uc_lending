#!/usr/bin/env python3
"""Run a HEIR Home Credit benchmark package through optional external commands."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from code.heir.home_credit.prepare import prepare_target_group_tensors
from code.heir.home_credit.report import write_report
from code.heir.home_credit.runner import run_template
from code.heir.home_credit.workloads import TARGET_GROUP_WORKLOADS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare and optionally run HEIR Home Credit EDA benchmark.")
    parser.add_argument("--input", default="data/home_credit/application_train.csv")
    parser.add_argument("--workload", default="app_target_by_education_type", choices=sorted(TARGET_GROUP_WORKLOADS))
    parser.add_argument("--row-limit", type=int, default=0, help="0 means all rows.")
    parser.add_argument("--output-root", default="benchmark_runs/home_credit_heir_eda")
    parser.add_argument("--run-name", default="")
    parser.add_argument("--backend", default="prepare-only", choices=["prepare-only", "external"])
    parser.add_argument("--heir-compile-cmd", default="", help="Optional command template for HEIR compilation.")
    parser.add_argument("--heir-eval-cmd", default="", help="Optional command template for HEIR evaluation.")
    return parser.parse_args()


def read_reference(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as input_file:
        return list(csv.DictReader(input_file))


def path_size_bytes(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        total = 0
        for child in path.rglob("*"):
            if child.is_file():
                total += child.stat().st_size
        return total
    return 0


def collect_artifact_sizes(run_dir: Path) -> dict[str, int]:
    return {
        "run_dir_total": path_size_bytes(run_dir),
        "tensor_dir": path_size_bytes(run_dir / "tensors"),
        "tensor_manifest": path_size_bytes(run_dir / "tensor_manifest.csv"),
        "pandas_reference": path_size_bytes(run_dir / "pandas_reference.csv"),
        "workload_spec": path_size_bytes(run_dir / "heir_workload_spec.json"),
        "heir_result_json": path_size_bytes(run_dir / "heir_result.json"),
        "compiled_dir": path_size_bytes(run_dir / "compiled"),
    }


def main() -> None:
    args = parse_args()
    repo = Path.cwd()
    run_name = args.run_name or f"{args.workload}_{args.row_limit or 'all'}_{int(time.time())}"
    run_dir = Path(args.output_root) / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    summary = prepare_target_group_tensors(Path(args.input), args.workload, args.row_limit, run_dir)
    summary["workload_spec"] = str(run_dir / "heir_workload_spec.json")
    summary["backend_status"] = "prepared_only"
    summary["heir_compile_cmd"] = args.heir_compile_cmd
    summary["heir_eval_cmd"] = args.heir_eval_cmd

    context = {
        "run_dir": str(run_dir),
        "workload": args.workload,
        "workload_spec": str(run_dir / "heir_workload_spec.json"),
        "tensor_manifest": str(run_dir / "tensor_manifest.csv"),
        "pandas_reference": str(run_dir / "pandas_reference.csv"),
        "heir_output_json": str(run_dir / "heir_result.json"),
        "compiled_dir": str(run_dir / "compiled"),
    }
    timings = dict(summary.get("timings_seconds", {}))

    if args.backend == "external":
        if not args.heir_eval_cmd:
            raise SystemExit("--backend external requires --heir-eval-cmd")
        if args.heir_compile_cmd:
            timings["heir_compile_seconds"], compile_output = run_template(args.heir_compile_cmd, context, repo)
            (run_dir / "heir_compile.log").write_text(compile_output, encoding="utf-8")
        timings["heir_eval_seconds"], eval_output = run_template(args.heir_eval_cmd, context, repo)
        (run_dir / "heir_eval.log").write_text(eval_output, encoding="utf-8")
        summary["backend_status"] = "external_commands_completed"

    summary["timings_seconds"] = timings
    summary["artifact_sizes_bytes"] = collect_artifact_sizes(run_dir)
    (run_dir / "benchmark_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    reference_rows = read_reference(Path(summary["pandas_reference"]))
    write_report(run_dir / "benchmark_report.md", summary, reference_rows)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
