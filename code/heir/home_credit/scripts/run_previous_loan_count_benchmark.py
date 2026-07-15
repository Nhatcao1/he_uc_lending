#!/usr/bin/env python3
"""Benchmark encrypted previous-loan counts per anonymous applicant row."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from code.heir.home_credit.prepare import prepare_previous_loan_count_tensors
from code.heir.home_credit.report import write_previous_loan_count_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark HEIR CKKS previous-loan counts per applicant.")
    parser.add_argument("--input", default="data/home_credit/application_train.csv")
    parser.add_argument("--previous-application", default="data/home_credit/previous_application.csv")
    parser.add_argument("--application-row-limit", type=int, default=0, help="0 means all application rows.")
    parser.add_argument("--previous-row-limit", type=int, default=0, help="0 means all previous_application rows.")
    parser.add_argument("--output-root", default="benchmark_runs/home_credit_previous_loan_count")
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


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as input_file:
        return list(csv.DictReader(input_file))


def path_size_bytes(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        return sum(child.stat().st_size for child in path.rglob("*") if child.is_file())
    return 0


def collect_artifact_sizes(run_dir: Path) -> dict[str, int]:
    return {
        "run_dir_total": path_size_bytes(run_dir),
        "encrypted_input_tensor_dir": path_size_bytes(run_dir / "tensors"),
        "client_private_mapping": path_size_bytes(run_dir / "client_private" / "applicant_mapping.csv"),
        "pandas_reference": path_size_bytes(run_dir / "pandas_reference.csv"),
        "heir_decrypted_previous_loan_count": path_size_bytes(
            run_dir / "heir_decrypted_previous_loan_count.csv"
        ),
        "heir_accuracy": path_size_bytes(run_dir / "heir_accuracy.csv"),
        "heir_generated_ckks_dir": path_size_bytes(run_dir / "heir_generated_ckks"),
    }


def compare_counts(
    reference_rows: list[dict[str, str]], actual_rows: list[dict[str, str]], tolerance: float
) -> dict[str, Any]:
    actual_by_index = {row["app_index"]: float(row["previous_loan_count"]) for row in actual_rows}
    details: list[dict[str, Any]] = []
    failures: list[str] = []
    for row in reference_rows:
        index = row["app_index"]
        expected = float(row["previous_loan_count"])
        if index not in actual_by_index:
            details.append(
                {
                    "app_index": index,
                    "expected_previous_loan_count": expected,
                    "actual_previous_loan_count": "",
                    "absolute_error": "",
                    "passed": False,
                }
            )
            failures.append(f"missing HEIR result for anonymous app index {index}")
            continue
        actual = actual_by_index[index]
        error = abs(expected - actual)
        passed = error <= tolerance
        details.append(
            {
                "app_index": index,
                "expected_previous_loan_count": expected,
                "actual_previous_loan_count": actual,
                "absolute_error": error,
                "passed": passed,
            }
        )
        if not passed:
            failures.append(f"app {index}: expected {expected}, actual {actual}, error {error}")
    errors = [float(item["absolute_error"]) for item in details if item["absolute_error"] != ""]
    return {
        "passed": not failures,
        "tolerance": tolerance,
        "checked_rows": len(reference_rows),
        "max_absolute_error": max(errors) if errors else None,
        "mean_absolute_error": sum(errors) / len(errors) if errors else None,
        "failures": failures[:20],
        "details": details,
    }


def write_accuracy_csv(path: Path, accuracy: dict[str, Any]) -> None:
    fields = [
        "app_index",
        "expected_previous_loan_count",
        "actual_previous_loan_count",
        "absolute_error",
        "passed",
    ]
    with path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(accuracy["details"])


def main() -> None:
    args = parse_args()
    run_name = args.run_name or f"previous_loan_count_{int(time.time())}"
    run_dir = Path(args.output_root) / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    summary = prepare_previous_loan_count_tensors(
        application_path=Path(args.input),
        previous_application_path=Path(args.previous_application),
        application_row_limit=args.application_row_limit,
        previous_row_limit=args.previous_row_limit,
        output_dir=run_dir,
    )
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

    if args.backend == "heir-generated-ckks":
        from code.heir.home_credit.backends.previous_loan_count_ckks import (
            run_previous_loan_count_generated_ckks_backend,
        )

        backend_timings, result, backend_log = run_previous_loan_count_generated_ckks_backend(
            run_dir=run_dir,
            generated_dir=Path(args.heir_generated_dir),
            openfhe_dir=args.openfhe_dir,
            vector_size=args.heir_vector_size,
            heir_opt=args.heir_opt,
            heir_translate=args.heir_translate,
            heir_opt_pipeline=args.heir_opt_pipeline,
            application_count=int(summary["application_rows"]),
            slots_per_application=int(summary["slots_per_application"]),
        )
        timings.update(backend_timings)
        (run_dir / "heir_generated_ckks.log").write_text(backend_log, encoding="utf-8")
        reference_rows = read_csv(run_dir / "pandas_reference.csv")
        actual_rows = read_csv(run_dir / "heir_decrypted_previous_loan_count.csv")
        accuracy = compare_counts(reference_rows, actual_rows, args.accuracy_tolerance)
        write_accuracy_csv(run_dir / "heir_accuracy.csv", accuracy)
        summary["heir_result"] = result
        summary["heir_correctness"] = accuracy
        summary["backend_status"] = "heir_generated_ckks_completed"

    summary["timings_seconds"] = timings
    summary["artifact_sizes_bytes"] = collect_artifact_sizes(run_dir)
    (run_dir / "benchmark_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    reference_rows = read_csv(run_dir / "pandas_reference.csv")
    mapping_rows = read_csv(run_dir / "client_private" / "applicant_mapping.csv")
    actual_rows = (
        read_csv(run_dir / "heir_decrypted_previous_loan_count.csv")
        if (run_dir / "heir_decrypted_previous_loan_count.csv").is_file()
        else []
    )
    actual_by_index = {row["app_index"]: float(row["previous_loan_count"]) for row in actual_rows}
    mapping_by_index = {row["app_index"]: row for row in mapping_rows}
    write_previous_loan_count_report(
        run_dir / "benchmark_report.md", summary, reference_rows, actual_by_index, mapping_by_index
    )
    print(json.dumps(summary, indent=2))
    accuracy = summary.get("heir_correctness")
    if isinstance(accuracy, dict) and accuracy.get("passed") is False:
        raise SystemExit(
            "CKKS accuracy acceptance failed: per-applicant previous-loan counts exceed "
            f"{args.accuracy_tolerance}. See {run_dir / 'heir_accuracy.csv'}"
        )


if __name__ == "__main__":
    main()
