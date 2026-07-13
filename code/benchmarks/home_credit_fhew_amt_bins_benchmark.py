#!/usr/bin/env python3
"""Benchmark FHEW server-side AMT bin counting for Home Credit.

This runner intentionally tests the slower but stricter path where the source
does not prepare bin masks. The source encrypts amount bits and a valid bit;
the HE server receives plaintext min/max/bin metadata and computes encrypted
bin membership plus encrypted count bits.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import subprocess
import time
from pathlib import Path


AMT_METADATA = {
    "AMT_CREDIT": {"min": 45000, "max": 4050000, "bit_width": 24},
    "AMT_GOODS_PRICE": {"min": 40500, "max": 4050000, "bit_width": 24},
    "AMT_INCOME_TOTAL": {"min": 25650, "max": 117000000, "bit_width": 27},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark FHEW AMT histogram bin counting.")
    parser.add_argument("--input", default="data/home_credit/application_train.csv")
    parser.add_argument("--column", default="AMT_CREDIT", choices=sorted(AMT_METADATA))
    parser.add_argument("--row-limit", type=int, default=5)
    parser.add_argument("--min-value", type=int, default=None)
    parser.add_argument("--max-value", type=int, default=None)
    parser.add_argument("--bin-count", type=int, default=5)
    parser.add_argument("--bit-width", type=int, default=None)
    parser.add_argument("--security", default="TOY", choices=["TOY", "STD128"])
    parser.add_argument("--build-dir", default="build")
    parser.add_argument("--output-root", default="benchmark_runs/home_credit_fhew_amt_bins")
    parser.add_argument("--run-name", default="")
    parser.add_argument("--keep-existing", action="store_true")
    return parser.parse_args()


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


def path_size_bytes(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        return sum(child.stat().st_size for child in path.rglob("*") if child.is_file())
    return 0


def human_bytes(value: object) -> str:
    try:
        size = float(value)
    except (TypeError, ValueError):
        return ""
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    unit = 0
    while size >= 1024 and unit < len(units) - 1:
        size /= 1024
        unit += 1
    if unit == 0:
        return f"{int(size)} {units[unit]}"
    return f"{size:.2f} {units[unit]}"


def is_missing(value: str | None) -> bool:
    if value is None:
        return True
    cleaned = value.strip().lower()
    return not cleaned or cleaned in {"nan", "null", "none"}


def make_bins(min_value: int, max_value: int, bin_count: int) -> list[dict[str, int | str]]:
    span = max_value - min_value + 1
    width = math.ceil(span / bin_count)
    bins: list[dict[str, int | str]] = []
    for index in range(bin_count):
        lower = min_value + index * width
        upper = max_value + 1 if index + 1 == bin_count else lower + width
        bins.append(
            {
                "bin_index": index,
                "label": f"{lower}_{upper}",
                "lower_inclusive": lower,
                "upper_exclusive": upper,
                "count": 0,
            }
        )
    return bins


def plaintext_reference(
    input_path: Path,
    column: str,
    row_limit: int,
    min_value: int,
    max_value: int,
    bin_count: int,
) -> tuple[list[dict[str, object]], int, int, float]:
    started = time.perf_counter()
    bins = make_bins(min_value, max_value, bin_count)
    row_count = 0
    valid_count = 0
    with input_path.open("r", encoding="utf-8-sig", newline="") as input_file:
        reader = csv.DictReader(input_file)
        for row in reader:
            if row_limit and row_count >= row_limit:
                break
            row_count += 1
            raw = row.get(column)
            if is_missing(raw):
                continue
            value = int(round(float(str(raw))))
            valid_count += 1
            for item in bins:
                lower = int(item["lower_inclusive"])
                upper = int(item["upper_exclusive"])
                if lower <= value < upper:
                    item["count"] = int(item["count"]) + 1
                    break

    rows: list[dict[str, object]] = []
    for item in bins:
        count = int(item["count"])
        rows.append(
            {
                "result_type": "bin_count",
                "bin_index": item["bin_index"],
                "label": item["label"],
                "lower_inclusive": item["lower_inclusive"],
                "upper_exclusive": item["upper_exclusive"],
                "count": count,
                "row_count": row_count,
                "valid_count": valid_count,
                "percent_of_valid": count / valid_count if valid_count else 0.0,
                "percent_of_rows": count / row_count if row_count else 0.0,
            }
        )
    rows.append(
        {
            "result_type": "valid_count",
            "bin_index": -1,
            "label": "valid_count",
            "lower_inclusive": 0,
            "upper_exclusive": 0,
            "count": valid_count,
            "row_count": row_count,
            "valid_count": valid_count,
            "percent_of_valid": 1.0 if valid_count else 0.0,
            "percent_of_rows": valid_count / row_count if row_count else 0.0,
        }
    )
    return rows, row_count, valid_count, time.perf_counter() - started


def write_reference(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = [
        "result_type",
        "bin_index",
        "label",
        "lower_inclusive",
        "upper_exclusive",
        "count",
        "row_count",
        "valid_count",
        "percent_of_valid",
        "percent_of_rows",
    ]
    with path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def read_decrypted(path: Path) -> dict[tuple[str, int], dict[str, object]]:
    rows: dict[tuple[str, int], dict[str, object]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as input_file:
        reader = csv.DictReader(input_file)
        for row in reader:
            key = (row["result_type"], int(row["bin_index"]))
            rows[key] = row
    return rows


def compare_results(reference: list[dict[str, object]], decrypted: dict[tuple[str, int], dict[str, object]]) -> list[str]:
    failures: list[str] = []
    for expected in reference:
        key = (str(expected["result_type"]), int(expected["bin_index"]))
        actual = decrypted.get(key)
        if actual is None:
            failures.append(f"missing decrypted row: {key}")
            continue
        expected_count = int(expected["count"])
        actual_count = int(actual["count"])
        if expected_count != actual_count:
            failures.append(f"{key} count: expected {expected_count}, got {actual_count}")
    extra = sorted(set(decrypted) - {(str(row["result_type"]), int(row["bin_index"])) for row in reference})
    for key in extra:
        failures.append(f"unexpected decrypted row: {key}")
    return failures


def collect_artifact_sizes(run_dir: Path, encrypted_fhew_dir: Path, key_dir: Path, server_dir: Path) -> dict[str, int]:
    return {
        "run_dir_total": path_size_bytes(run_dir),
        "encrypted_fhew_bundle_total": path_size_bytes(encrypted_fhew_dir),
        "amount_bits": path_size_bytes(encrypted_fhew_dir / "amount_bits"),
        "valid_bits": path_size_bytes(encrypted_fhew_dir / "valid_bits"),
        "constants": path_size_bytes(encrypted_fhew_dir / "constants"),
        "fhew_context": path_size_bytes(encrypted_fhew_dir / "cryptoContext.bin"),
        "refresh_key": path_size_bytes(encrypted_fhew_dir / "refreshKey.bin"),
        "switch_key": path_size_bytes(encrypted_fhew_dir / "ksKey.bin"),
        "client_key_dir": path_size_bytes(key_dir),
        "server_output_dir": path_size_bytes(server_dir),
    }


def markdown_table(headers: list[str], rows: list[list[object]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(item) for item in row) + " |")
    return "\n".join(lines)


def write_markdown_report(path: Path, summary: dict[str, object], reference: list[dict[str, object]]) -> None:
    timings = summary["timings_seconds"]
    assert isinstance(timings, dict)
    artifact_sizes = summary["artifact_sizes_bytes"]
    assert isinstance(artifact_sizes, dict)
    metadata = summary["metadata"]
    assert isinstance(metadata, dict)
    artifacts = summary["artifacts"]
    assert isinstance(artifacts, dict)

    timing_rows = [[key, f"{float(value):.6f}"] for key, value in timings.items()]
    size_rows = [[key, human_bytes(value), value] for key, value in artifact_sizes.items()]
    result_rows = []
    valid_count = int(summary["valid_rows"])
    for row in reference:
        if row["result_type"] != "bin_count":
            continue
        count = int(row["count"])
        result_rows.append(
            [
                row["label"],
                row["lower_inclusive"],
                row["upper_exclusive"],
                count,
                f"{(count / valid_count * 100.0) if valid_count else 0.0:.2f}%",
            ]
        )

    report = f"""# Home Credit FHEW AMT Bin Benchmark

## Case

| Field | Value |
| --- | --- |
| Workload | `fhew_amt_bin_count` |
| Input | `{summary['input']}` |
| Column | `{summary['column']}` |
| Rows requested | `{summary['row_limit']}` |
| Rows scanned | `{summary['row_count']}` |
| Valid rows | `{summary['valid_rows']}` |
| Min metadata | `{metadata['min_value']}` |
| Max metadata | `{metadata['max_value']}` |
| Bin count | `{metadata['bin_count']}` |
| FHEW bit width | `{metadata['bit_width']}` |
| Security profile | `{metadata['security']}` |
| Correctness | **{summary['correctness']}** |

## What This EDA Computes

This case computes a histogram/bin-count table for an amount column without
source-prepared bin masks. The HE server receives plaintext range metadata and
computes bin membership from encrypted amount bits.

## Data Preparation Before Encryption

The source side reads `{summary['column']}`, converts each non-null amount into
integer bits, and creates one encrypted valid bit per row. Missing values are
encoded as all-zero amount bits with `valid=0`.

The source does not prepare `bin_0_mask`, `bin_1_mask`, or other histogram masks.

## HE Operation Path

```text
For each row and each bin:
  lower_ok = encrypted(value >= plaintext_lower)
  upper_ok = encrypted(value < plaintext_upper)
  membership = lower_ok AND upper_ok AND valid_bit

For each bin:
  encrypted_count_bits = binary_add(encrypted_count_bits, membership)
```

## Timing Summary

{markdown_table(["Metric", "Seconds"], timing_rows)}

## Artifact Size Summary

{markdown_table(["Artifact", "Size", "Bytes"], size_rows)}

## Result Preview

{markdown_table(["Bin", "Lower", "Upper", "Count", "Percent of valid"], result_rows)}

## Artifacts

| Artifact | Path |
| --- | --- |
| JSON summary | `{path.parent / 'benchmark_summary.json'}` |
| Plaintext reference | `{artifacts['plaintext_reference']}` |
| Decrypted HE result | `{artifacts['decrypted_csv']}` |
| Encrypted FHEW bundle | `{artifacts['encrypted_fhew_dir']}` |
| HE server output | `{artifacts['server_output_dir']}` |

## Notes

- This is a feasibility benchmark for encrypted comparison, not a scalable full
  Home Credit histogram implementation yet.
- Runtime scales with `rows * bins * bit_width` Boolean gates.
- The server knows the plaintext min/max/bin metadata but does not see row-level
  amount values or row-level bin membership.
"""
    path.write_text(report, encoding="utf-8")


def main() -> None:
    args = parse_args()
    if args.row_limit <= 0:
        raise SystemExit("FHEW AMT benchmark requires a positive --row-limit")
    if args.bin_count <= 0:
        raise SystemExit("--bin-count must be positive")

    defaults = AMT_METADATA[args.column]
    min_value = int(defaults["min"] if args.min_value is None else args.min_value)
    max_value = int(defaults["max"] if args.max_value is None else args.max_value)
    bit_width = int(defaults["bit_width"] if args.bit_width is None else args.bit_width)
    if max_value < min_value:
        raise SystemExit("--max-value must be >= --min-value")

    repo = Path.cwd()
    input_path = Path(args.input)
    run_name = args.run_name or f"fhew_{args.column.lower()}_{args.row_limit}_bins{args.bin_count}_{int(time.time())}"
    run_dir = Path(args.output_root) / run_name
    if run_dir.exists() and not args.keep_existing:
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    encrypted_root = run_dir / "encrypted"
    encrypted_fhew_dir = encrypted_root / "amt" / "fhew"
    key_dir = run_dir / "keys"
    server_dir = run_dir / "server_output"
    decrypted_csv = run_dir / "decrypted_counts.csv"
    reference_csv = run_dir / "plaintext_reference.csv"
    markdown_report = run_dir / f"fhew_{args.column.lower()}_bin_count_report.md"

    timings: dict[str, float] = {}
    reference, row_count, valid_count, timings["python_reference_seconds"] = plaintext_reference(
        input_path,
        args.column,
        args.row_limit,
        min_value,
        max_value,
        args.bin_count,
    )
    write_reference(reference_csv, reference)

    encrypt_command = [
        str(Path(args.build_dir) / "encrypt_home_credit_fhew_amt"),
        "--input",
        str(input_path),
        "--column",
        args.column,
        "--server-output-dir",
        str(encrypted_root),
        "--client-key-dir",
        str(key_dir),
        "--row-limit",
        str(args.row_limit),
        "--bit-width",
        str(bit_width),
        "--security",
        args.security,
    ]
    timings["encrypt_wall_seconds"], encrypt_output = run_command(encrypt_command, repo)
    timings.update(parse_timing_lines(encrypt_output, "encrypt"))

    server_command = [
        str(Path(args.build_dir) / "server_home_credit_fhew_amt_bins"),
        "--context",
        str(encrypted_fhew_dir / "cryptoContext.bin"),
        "--refresh-key",
        str(encrypted_fhew_dir / "refreshKey.bin"),
        "--switch-key",
        str(encrypted_fhew_dir / "ksKey.bin"),
        "--amount-manifest",
        str(encrypted_fhew_dir / "fhew_amt_amount_manifest.csv"),
        "--valid-manifest",
        str(encrypted_fhew_dir / "fhew_amt_valid_manifest.csv"),
        "--input-dir",
        str(encrypted_fhew_dir),
        "--output-dir",
        str(server_dir),
        "--min",
        str(min_value),
        "--max",
        str(max_value),
        "--bin-count",
        str(args.bin_count),
    ]
    timings["he_server_wall_seconds"], server_output = run_command(server_command, repo)
    timings.update(parse_timing_lines(server_output, "he_server"))

    decrypt_command = [
        str(Path(args.build_dir) / "decrypt_home_credit_fhew_amt_bins"),
        "--context",
        str(key_dir / "fhew_crypto_context.bin"),
        "--secret-key",
        str(key_dir / "fhew_secret_key.bin"),
        "--manifest",
        str(server_dir / "fhew_amt_bin_count_manifest.csv"),
        "--input-dir",
        str(server_dir),
        "--output-csv",
        str(decrypted_csv),
    ]
    timings["decrypt_wall_seconds"], _decrypt_output = run_command(decrypt_command, repo)

    decrypted = read_decrypted(decrypted_csv)
    failures = compare_results(reference, decrypted)
    passed = not failures

    server_metadata = {}
    metadata_path = server_dir / "fhew_amt_bin_run_metadata.json"
    if metadata_path.exists():
        server_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    summary = {
        "workload": "fhew_amt_bin_count",
        "input": str(input_path),
        "column": args.column,
        "row_limit": args.row_limit,
        "row_count": row_count,
        "valid_rows": valid_count,
        "run_dir": str(run_dir),
        "correctness": "passed" if passed else "failed",
        "failures": failures[:20],
        "metadata": {
            "min_value": min_value,
            "max_value": max_value,
            "bin_count": args.bin_count,
            "bit_width": bit_width,
            "security": args.security,
            "source_metadata_defaults": args.min_value is None and args.max_value is None,
        },
        "server_metadata": server_metadata,
        "timings_seconds": timings,
        "artifact_sizes_bytes": collect_artifact_sizes(run_dir, encrypted_fhew_dir, key_dir, server_dir),
        "artifacts": {
            "plaintext_reference": str(reference_csv),
            "decrypted_csv": str(decrypted_csv),
            "markdown_report": str(markdown_report),
            "encrypted_fhew_dir": str(encrypted_fhew_dir),
            "server_output_dir": str(server_dir),
            "key_dir": str(key_dir),
        },
    }
    (run_dir / "benchmark_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_markdown_report(markdown_report, summary, reference)

    print(json.dumps(summary, indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
