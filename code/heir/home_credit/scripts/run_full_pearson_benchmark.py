#!/usr/bin/env python3
"""Benchmark one full Pearson correlation under HEIR CKKS plus Chebyshev CKKS."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from code.heir.home_credit.prepare import prepare_single_pearson_tensors
from code.heir.home_credit.report import write_full_pearson_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark one full HEIR CKKS Pearson pair.")
    parser.add_argument("--input", default="data/home_credit/application_train.csv")
    parser.add_argument("--feature-x", default="AMT_CREDIT")
    parser.add_argument("--feature-y", default="AMT_GOODS_PRICE")
    parser.add_argument("--row-limit", type=int, default=10000, help="0 means all rows.")
    parser.add_argument("--output-root", default="benchmark_runs/home_credit_full_pearson")
    parser.add_argument("--run-name", default="")
    parser.add_argument("--backend", choices=["prepare-only", "heir-generated-ckks"], default="heir-generated-ckks")
    parser.add_argument("--heir-generated-dir", default="/root/heir-work")
    parser.add_argument("--openfhe-dir", default="")
    parser.add_argument("--heir-opt", default="heir-opt")
    parser.add_argument("--heir-translate", default="heir-translate")
    parser.add_argument("--heir-opt-pipeline", default="")
    parser.add_argument("--heir-vector-size", type=int, default=8192)
    parser.add_argument("--chebyshev-degree", type=int, default=15)
    parser.add_argument("--moment-tolerance", type=float, default=1e-4)
    parser.add_argument("--correlation-tolerance", type=float, default=0.02)
    return parser.parse_args()


def read_reference(path: Path) -> dict[str, str]:
    with path.open("r", encoding="utf-8-sig", newline="") as input_file:
        row = next(csv.DictReader(input_file), None)
    if row is None:
        raise ValueError("empty Pearson reference")
    return row


def size(path: Path) -> int:
    if path.is_file(): return path.stat().st_size
    if path.is_dir(): return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
    return 0


def compare_result(reference: dict[str, str], result: dict[str, object], moment_tolerance: float,
                   correlation_tolerance: float) -> dict[str, object]:
    """Check all decrypted sufficient statistics as well as final CKKS r."""
    expected = {
        "count": float(reference["complete_rows"]),
        "mean_x": float(reference["normalized_mean_x"]),
        "mean_y": float(reference["normalized_mean_y"]),
        "mean_xy": float(reference["normalized_mean_xy"]),
        "mean_x2": float(reference["normalized_mean_x2"]),
        "mean_y2": float(reference["normalized_mean_y2"]),
        "correlation": float(reference["correlation"]),
    }
    rows = []
    failures = []
    for metric, expected_value in expected.items():
        actual_value = float(result.get(metric, "nan"))
        error = abs(expected_value - actual_value)
        tolerance = correlation_tolerance if metric == "correlation" else moment_tolerance
        passed = error <= tolerance
        rows.append({
            "metric": metric,
            "expected": expected_value,
            "actual": actual_value,
            "absolute_error": error,
            "tolerance": tolerance,
            "passed": passed,
        })
        if not passed:
            failures.append(f"{metric}: expected {expected_value}, actual {actual_value}, error {error}")
    return {
        "passed": not failures,
        "moment_tolerance": moment_tolerance,
        "correlation_tolerance": correlation_tolerance,
        "correlation_absolute_error": next(row["absolute_error"] for row in rows if row["metric"] == "correlation"),
        "max_absolute_error": max(float(row["absolute_error"]) for row in rows),
        "failures": failures,
        "details": rows,
    }


def write_accuracy_csv(path: Path, accuracy: dict[str, object]) -> None:
    details = accuracy.get("details", [])
    if not isinstance(details, list):
        return
    fields = ["metric", "expected", "actual", "absolute_error", "tolerance", "passed"]
    with path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(row for row in details if isinstance(row, dict))


def main() -> None:
    args = parse_args()
    run_name = args.run_name or f"pearson_{args.feature_x.lower()}_{args.feature_y.lower()}_{int(time.time())}"
    run_dir = Path(args.output_root) / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    summary = prepare_single_pearson_tensors(Path(args.input), args.feature_x, args.feature_y, args.row_limit, run_dir)
    reference = read_reference(run_dir / "pandas_reference.csv")
    summary.update({"pandas_reference_row": reference, "backend_status": "prepared_only", "heir_generated_dir": args.heir_generated_dir,
                    "openfhe_dir": args.openfhe_dir, "heir_vector_size": args.heir_vector_size, "chebyshev_degree": args.chebyshev_degree,
                    "moment_tolerance": args.moment_tolerance, "correlation_tolerance": args.correlation_tolerance})
    timings = dict(summary["timings_seconds"])
    if args.backend == "heir-generated-ckks":
        from code.heir.home_credit.backends.full_pearson_ckks import run_full_pearson_generated_ckks_backend
        backend_timings, result, backend_log = run_full_pearson_generated_ckks_backend(
            run_dir, Path(args.heir_generated_dir), args.openfhe_dir, args.heir_vector_size, args.heir_opt,
            args.heir_translate, args.heir_opt_pipeline, float(reference["inverse_sqrt_scale"]), args.chebyshev_degree)
        timings.update(backend_timings)
        (run_dir / "heir_generated_ckks.log").write_text(backend_log, encoding="utf-8")
        summary["heir_result"] = result
        summary["heir_correctness"] = compare_result(
            reference, result, args.moment_tolerance, args.correlation_tolerance
        )
        write_accuracy_csv(run_dir / "heir_accuracy.csv", summary["heir_correctness"])
        summary["backend_status"] = "heir_generated_ckks_completed"
    summary["timings_seconds"] = timings
    summary["artifact_sizes_bytes"] = {"run_dir_total": size(run_dir), "tensor_dir": size(run_dir / "tensors"),
                                       "pandas_reference": size(run_dir / "pandas_reference.csv"),
                                       "heir_accuracy": size(run_dir / "heir_accuracy.csv"),
                                       "heir_generated_ckks_dir": size(run_dir / "heir_generated_ckks")}
    (run_dir / "benchmark_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_full_pearson_report(run_dir / "benchmark_report.md", summary)
    print(json.dumps(summary, indent=2))
    accuracy = summary.get("heir_correctness")
    if isinstance(accuracy, dict) and accuracy.get("passed") is False:
        raise SystemExit("Full-HE Pearson approximation exceeded correlation tolerance; see benchmark_report.md")


if __name__ == "__main__":
    main()
