#!/usr/bin/env python3
"""Run a single-column Home Credit missing-count HEIR CKKS benchmark."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from code.heir.home_credit.prepare import prepare_single_missing_count_tensors
from code.heir.home_credit.report import write_single_missing_count_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark one encrypted Home Credit missing-value count.")
    parser.add_argument("--input", default="data/home_credit/application_train.csv")
    parser.add_argument("--column", default="OCCUPATION_TYPE")
    parser.add_argument("--row-limit", type=int, default=0, help="0 means all application rows.")
    parser.add_argument("--output-root", default="benchmark_runs/home_credit_single_missing_count")
    parser.add_argument("--run-name", default="")
    parser.add_argument("--backend", choices=["prepare-only", "heir-generated-ckks"], default="heir-generated-ckks")
    parser.add_argument("--heir-generated-dir", default="/root/heir-work")
    parser.add_argument("--openfhe-dir", default="")
    parser.add_argument("--heir-opt", default="heir-opt")
    parser.add_argument("--heir-translate", default="heir-translate")
    parser.add_argument("--heir-opt-pipeline", default="")
    parser.add_argument("--heir-vector-size", type=int, default=8192)
    parser.add_argument("--accuracy-tolerance", type=float, default=1e-4)
    return parser.parse_args()


def read_reference(path: Path) -> dict[str, str]:
    with path.open("r", encoding="utf-8-sig", newline="") as input_file:
        row = next(csv.DictReader(input_file), None)
    if row is None:
        raise ValueError(f"empty pandas reference: {path}")
    return row


def path_size_bytes(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
    return 0


def main() -> None:
    args = parse_args()
    run_name = args.run_name or f"single_missing_count_{args.column.lower()}_{int(time.time())}"
    run_dir = Path(args.output_root) / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    summary = prepare_single_missing_count_tensors(Path(args.input), args.column, args.row_limit, run_dir)
    summary.update(
        {
            "backend_status": "prepared_only",
            "heir_generated_dir": args.heir_generated_dir,
            "openfhe_dir": args.openfhe_dir,
            "heir_vector_size": args.heir_vector_size,
            "heir_scheme": "CKKS",
            "heir_opt_pipeline": args.heir_opt_pipeline,
            "accuracy_tolerance": args.accuracy_tolerance,
        }
    )
    timings = dict(summary["timings_seconds"])
    reference = read_reference(run_dir / "pandas_reference.csv")
    summary["pandas_reference_row"] = reference

    if args.backend == "heir-generated-ckks":
        from code.heir.home_credit.backends.single_missing_count_ckks import (
            run_single_missing_count_generated_ckks_backend,
        )

        backend_timings, result, backend_log = run_single_missing_count_generated_ckks_backend(
            run_dir=run_dir,
            generated_dir=Path(args.heir_generated_dir),
            openfhe_dir=args.openfhe_dir,
            vector_size=args.heir_vector_size,
            heir_opt=args.heir_opt,
            heir_translate=args.heir_translate,
            heir_opt_pipeline=args.heir_opt_pipeline,
        )
        timings.update(backend_timings)
        (run_dir / "heir_generated_ckks.log").write_text(backend_log, encoding="utf-8")
        expected = float(reference["missing_count"])
        actual = float(result["missing_count"])
        error = abs(expected - actual)
        correctness: dict[str, Any] = {
            "passed": error <= args.accuracy_tolerance,
            "tolerance": args.accuracy_tolerance,
            "expected_missing_count": expected,
            "actual_missing_count": actual,
            "absolute_error": error,
        }
        with (run_dir / "heir_accuracy.csv").open("w", encoding="utf-8", newline="") as output_file:
            writer = csv.DictWriter(output_file, fieldnames=list(correctness))
            writer.writeheader()
            writer.writerow(correctness)
        summary["heir_result"] = result
        summary["heir_correctness"] = correctness
        summary["backend_status"] = "heir_generated_ckks_completed"

    summary["timings_seconds"] = timings
    summary["artifact_sizes_bytes"] = {
        "run_dir_total": path_size_bytes(run_dir),
        "tensor_dir": path_size_bytes(run_dir / "tensors"),
        "pandas_reference": path_size_bytes(run_dir / "pandas_reference.csv"),
        "heir_accuracy": path_size_bytes(run_dir / "heir_accuracy.csv"),
        "heir_generated_ckks_dir": path_size_bytes(run_dir / "heir_generated_ckks"),
    }
    (run_dir / "benchmark_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_single_missing_count_report(run_dir / "benchmark_report.md", summary)
    print(json.dumps(summary, indent=2))
    correctness = summary.get("heir_correctness")
    if isinstance(correctness, dict) and correctness.get("passed") is False:
        raise SystemExit(
            "CKKS accuracy acceptance failed: encrypted missing count exceeds "
            f"{args.accuracy_tolerance}. See {run_dir / 'heir_accuracy.csv'}"
        )


if __name__ == "__main__":
    main()
