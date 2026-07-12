#!/usr/bin/env python3
"""Local core-HE benchmark for Home Credit EDA workloads.

This runner intentionally avoids the web path. It is meant for server-side
benchmarking where raw Home Credit CSVs are available in a trusted test folder.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import subprocess
import time
from collections import Counter
from pathlib import Path


MISSING_BUCKET = "__MISSING__"
OTHER_BUCKET = "__OTHER__"

WORKLOADS = {
    "app_target_by_education_type": {
        "column": "NAME_EDUCATION_TYPE",
        "analysis": "application_default_rates",
        "category_mode": "all",
    },
    "app_target_by_income_type": {
        "column": "NAME_INCOME_TYPE",
        "analysis": "application_default_rates",
        "category_mode": "all",
    },
    "app_target_by_occupation_type": {
        "column": "OCCUPATION_TYPE",
        "analysis": "application_default_rates",
        "category_mode": "top_k",
        "k": 20,
        "other_bucket": True,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark Home Credit core HE EDA locally.")
    parser.add_argument("--input", default="data/home_credit/application_train.csv")
    parser.add_argument("--workload", default="app_target_by_education_type", choices=sorted(WORKLOADS))
    parser.add_argument("--row-limit", type=int, default=0, help="0 means all rows.")
    parser.add_argument("--slots", type=int, default=4096)
    parser.add_argument("--build-dir", default="build")
    parser.add_argument("--output-root", default="benchmark_runs/home_credit_core_eda")
    parser.add_argument("--run-name", default="", help="Optional run directory name.")
    parser.add_argument("--tolerance", type=float, default=1e-3)
    parser.add_argument("--keep-existing", action="store_true", help="Do not delete an existing run directory.")
    return parser.parse_args()


def normalize_category(value: str | None) -> str:
    if value is None:
        return MISSING_BUCKET
    cleaned = str(value).strip()
    if not cleaned or cleaned.lower() in {"nan", "none", "null"}:
        return MISSING_BUCKET
    return cleaned


def parse_target(value: str | None) -> int:
    if value is None:
        return 0
    try:
        parsed = float(str(value).strip())
    except ValueError:
        return 0
    return 1 if math.isfinite(parsed) and int(parsed) == 1 else 0


def iter_rows(path: Path, row_limit: int):
    with path.open("r", encoding="utf-8-sig", newline="") as input_file:
        reader = csv.DictReader(input_file)
        for index, row in enumerate(reader):
            if row_limit and index >= row_limit:
                break
            yield row


def selected_labels(counts: Counter[str], cfg: dict[str, object]) -> list[str]:
    mode = str(cfg.get("category_mode", "all"))
    if mode == "all":
        return sorted(counts)
    if mode == "top_k":
        labels = [label for label, _ in counts.most_common(int(cfg.get("k", 20)))]
        if MISSING_BUCKET in counts and MISSING_BUCKET not in labels:
            labels.append(MISSING_BUCKET)
        if bool(cfg.get("other_bucket", True)):
            labels.append(OTHER_BUCKET)
        return labels
    raise ValueError(f"unsupported category mode: {mode}")


def label_for(raw_value: str | None, labels: list[str]) -> str:
    normalized = normalize_category(raw_value)
    if normalized in labels:
        return normalized
    if OTHER_BUCKET in labels:
        return OTHER_BUCKET
    return normalized


def plaintext_reference(input_path: Path, row_limit: int, cfg: dict[str, object]) -> tuple[list[dict[str, object]], float]:
    started = time.perf_counter()
    column = str(cfg["column"])
    counts: Counter[str] = Counter()
    rows = list(iter_rows(input_path, row_limit))
    for row in rows:
        counts[normalize_category(row.get(column))] += 1
    labels = selected_labels(counts, cfg)

    grouped = {label: {"count": 0, "default_count": 0} for label in labels}
    for row in rows:
        label = label_for(row.get(column), labels)
        bucket = grouped.setdefault(label, {"count": 0, "default_count": 0})
        bucket["count"] += 1
        bucket["default_count"] += parse_target(row.get("TARGET"))

    total = sum(int(item["count"]) for item in grouped.values())
    report: list[dict[str, object]] = []
    for label, values in sorted(grouped.items(), key=lambda item: int(item[1]["count"]), reverse=True):
        count = int(values["count"])
        default_count = int(values["default_count"])
        report.append(
            {
                "group": column,
                "label": label,
                "count": count,
                "percent": count / total if total else 0.0,
                "default_count": default_count,
                "default_rate": default_count / count if count else 0.0,
            }
        )
    return report, time.perf_counter() - started


def run_command(command: list[str], cwd: Path) -> tuple[float, str]:
    started = time.perf_counter()
    completed = subprocess.run(command, cwd=cwd, check=True, text=True, capture_output=True)  # noqa: S603
    elapsed = time.perf_counter() - started
    output = "\n".join(part for part in (completed.stdout.strip(), completed.stderr.strip()) if part)
    return elapsed, output


def parse_timing_lines(output: str, prefix: str) -> dict[str, float]:
    timings: dict[str, float] = {}
    for line in output.splitlines():
        parts = line.strip().split()
        if len(parts) == 3 and parts[0] == "TIMING":
            try:
                timings[f"{prefix}.{parts[1]}"] = float(parts[2])
            except ValueError:
                continue
    return timings


def filter_aggregate_manifest(source: Path, destination: Path, analysis: str, group: str) -> int:
    with source.open("r", encoding="utf-8-sig", newline="") as input_file:
        reader = csv.DictReader(input_file)
        fieldnames = reader.fieldnames or []
        rows = [row for row in reader if row.get("analysis") == analysis and row.get("group") == group]
    if not rows:
        raise ValueError(f"no aggregate manifest rows for analysis={analysis} group={group}")
    with destination.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def read_decrypted_aggregate(path: Path) -> dict[str, dict[str, float]]:
    grouped: dict[str, dict[str, float]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as input_file:
        reader = csv.DictReader(input_file)
        for row in reader:
            label = row["label"]
            operation = row["operation"]
            value = float(row["value"])
            bucket = grouped.setdefault(label, {})
            if operation == "count":
                bucket["count"] = value
            elif operation == "default_count":
                bucket["default_count"] = value
    return grouped


def compare_results(reference: list[dict[str, object]], decrypted: dict[str, dict[str, float]], tolerance: float) -> list[str]:
    failures: list[str] = []
    for expected in reference:
        label = str(expected["label"])
        actual = decrypted.get(label)
        if actual is None:
            failures.append(f"missing decrypted label: {label}")
            continue
        for field in ("count", "default_count"):
            expected_value = float(expected[field])
            actual_value = float(actual.get(field, float("nan")))
            if not math.isfinite(actual_value) or abs(expected_value - actual_value) > tolerance:
                failures.append(f"{label} {field}: expected {expected_value}, got {actual_value}")
    extra = sorted(set(decrypted) - {str(row["label"]) for row in reference})
    for label in extra:
        failures.append(f"unexpected decrypted label: {label}")
    return failures


def write_reference(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = ["group", "label", "count", "percent", "default_count", "default_rate"]
    with path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    repo = Path.cwd()
    input_path = Path(args.input)
    cfg = WORKLOADS[args.workload]
    run_name = args.run_name or f"{args.workload}_{args.row_limit or 'all'}_{int(time.time())}"
    run_dir = Path(args.output_root) / run_name
    if run_dir.exists() and not args.keep_existing:
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    prepared_dir = run_dir / "prepared"
    encrypted_dir = run_dir / "encrypted"
    key_dir = run_dir / "keys"
    server_dir = run_dir / "server_output" / args.workload
    filtered_manifest = run_dir / "aggregate_manifest.filtered.csv"
    decrypted_csv = run_dir / "decrypted.csv"
    reference_csv = run_dir / "plaintext_reference.csv"

    timings: dict[str, float] = {}
    reference, timings["python_reference_seconds"] = plaintext_reference(input_path, args.row_limit, cfg)
    write_reference(reference_csv, reference)

    prepare_command = [
        "python3",
        "code/client/home_credit/prepare_home_credit_basic_eda.py",
        "--input",
        str(input_path),
        "--output-dir",
        str(prepared_dir),
        "--row-limit",
        str(args.row_limit),
    ]
    timings["prepare_wall_seconds"], prepare_output = run_command(prepare_command, repo)

    encrypt_command = [
        str(Path(args.build_dir) / "encrypt_home_credit_payload"),
        "--prepared-dir",
        str(prepared_dir),
        "--server-output-dir",
        str(encrypted_dir),
        "--client-key-dir",
        str(key_dir),
        "--slots",
        str(args.slots),
    ]
    timings["encrypt_wall_seconds"], encrypt_output = run_command(encrypt_command, repo)
    timings.update(parse_timing_lines(encrypt_output, "encrypt"))

    manifest_rows = filter_aggregate_manifest(
        encrypted_dir / "aggregate_manifest.csv",
        filtered_manifest,
        str(cfg["analysis"]),
        str(cfg["column"]),
    )

    server_command = [
        str(Path(args.build_dir) / "server_home_credit_aggregate"),
        "--context",
        str(encrypted_dir / "crypto_context.bin"),
        "--eval-sum-keys",
        str(encrypted_dir / "eval_sum_keys.bin"),
        "--eval-mult-keys",
        str(encrypted_dir / "eval_mult_keys.bin"),
        "--manifest",
        str(filtered_manifest),
        "--input-dir",
        str(encrypted_dir / "vectors"),
        "--output-dir",
        str(server_dir),
        "--analysis-filter",
        str(cfg["analysis"]),
    ]
    timings["he_server_wall_seconds"], server_output = run_command(server_command, repo)
    timings.update(parse_timing_lines(server_output, "he_server"))

    decrypt_command = [
        str(Path(args.build_dir) / "decrypt_ckks_results"),
        "--context",
        str(encrypted_dir / "crypto_context.bin"),
        "--secret-key",
        str(key_dir / "secret_key.bin"),
        "--manifest",
        str(server_dir / "aggregate_summary_manifest.csv"),
        "--input-dir",
        str(server_dir),
        "--output-csv",
        str(decrypted_csv),
        "--manifest-type",
        "aggregate",
    ]
    timings["decrypt_wall_seconds"], decrypt_output = run_command(decrypt_command, repo)
    timings.update(parse_timing_lines(decrypt_output, "decrypt"))

    decrypted = read_decrypted_aggregate(decrypted_csv)
    failures = compare_results(reference, decrypted, args.tolerance)
    passed = not failures

    summary = {
        "workload": args.workload,
        "input": str(input_path),
        "row_limit": args.row_limit,
        "slots": args.slots,
        "run_dir": str(run_dir),
        "selected_group": cfg["column"],
        "reference_rows": len(reference),
        "filtered_manifest_rows": manifest_rows,
        "correctness": "passed" if passed else "failed",
        "failures": failures[:20],
        "timings_seconds": timings,
        "artifacts": {
            "plaintext_reference": str(reference_csv),
            "decrypted_csv": str(decrypted_csv),
            "prepared_dir": str(prepared_dir),
            "encrypted_dir": str(encrypted_dir),
            "server_output_dir": str(server_dir),
        },
    }
    (run_dir / "benchmark_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
