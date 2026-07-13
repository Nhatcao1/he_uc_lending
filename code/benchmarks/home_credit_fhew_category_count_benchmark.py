#!/usr/bin/env python3
"""Benchmark FHEW category counting for Home Credit application EDA.

This runner tests the metadata/code path: source encrypts category-code bits,
not one-hot masks. The HE server compares encrypted codes to plaintext label
codes and returns encrypted count bits for every label.
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

WORKLOADS = {
    "app_suite_type": {
        "section": "5.4",
        "label": "Who Accompanied Client",
        "column": "NAME_TYPE_SUITE",
        "bit_width": 4,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark FHEW category count EDA.")
    parser.add_argument("--input", default="data/home_credit/application_train.csv")
    parser.add_argument("--workload", default="app_suite_type", choices=sorted(WORKLOADS))
    parser.add_argument("--row-limit", type=int, default=5)
    parser.add_argument("--bit-width", type=int, default=None)
    parser.add_argument("--security", default="TOY", choices=["TOY", "STD128"])
    parser.add_argument("--build-dir", default="build")
    parser.add_argument("--output-root", default="benchmark_runs/home_credit_fhew_category_count")
    parser.add_argument("--run-name", default="")
    parser.add_argument("--keep-existing", action="store_true")
    return parser.parse_args()


def normalize_category(value: str | None) -> str:
    if value is None:
        return MISSING_BUCKET
    cleaned = str(value).strip()
    if not cleaned or cleaned.lower() in {"nan", "none", "null"}:
        return MISSING_BUCKET
    return cleaned


def iter_rows(path: Path, row_limit: int):
    with path.open("r", encoding="utf-8-sig", newline="") as input_file:
        reader = csv.DictReader(input_file)
        for index, row in enumerate(reader):
            if row_limit and index >= row_limit:
                break
            yield row


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


def plaintext_reference(input_path: Path, column: str, row_limit: int) -> tuple[list[dict[str, object]], int, float]:
    started = time.perf_counter()
    counts: Counter[str] = Counter()
    row_count = 0
    for row in iter_rows(input_path, row_limit):
        counts[normalize_category(row.get(column))] += 1
        row_count += 1

    report = []
    for code, (label, count) in enumerate(sorted(counts.items())):
        report.append(
            {
                "code": code,
                "label": label,
                "count": count,
                "row_count": row_count,
                "percent": count / row_count if row_count else 0.0,
            }
        )
    return report, row_count, time.perf_counter() - started


def write_reference(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = ["code", "label", "count", "row_count", "percent"]
    with path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def read_decrypted(path: Path) -> dict[int, dict[str, object]]:
    rows: dict[int, dict[str, object]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as input_file:
        reader = csv.DictReader(input_file)
        for row in reader:
            rows[int(row["code"])] = row
    return rows


def compare_results(reference: list[dict[str, object]], decrypted: dict[int, dict[str, object]]) -> list[str]:
    failures: list[str] = []
    for expected in reference:
        code = int(expected["code"])
        actual = decrypted.get(code)
        if actual is None:
            failures.append(f"missing decrypted code: {code}")
            continue
        if str(expected["label"]) != actual["label"]:
            failures.append(f"code {code} label: expected {expected['label']}, got {actual['label']}")
        if int(expected["count"]) != int(actual["count"]):
            failures.append(f"code {code} count: expected {expected['count']}, got {actual['count']}")
    extra = sorted(set(decrypted) - {int(row["code"]) for row in reference})
    for code in extra:
        failures.append(f"unexpected decrypted code: {code}")
    return failures


def collect_artifact_sizes(run_dir: Path, encrypted_fhew_dir: Path, key_dir: Path, server_dir: Path) -> dict[str, int]:
    return {
        "run_dir_total": path_size_bytes(run_dir),
        "encrypted_fhew_bundle_total": path_size_bytes(encrypted_fhew_dir),
        "category_bits": path_size_bytes(encrypted_fhew_dir / "category_bits"),
        "constants": path_size_bytes(encrypted_fhew_dir / "constants"),
        "fhew_context": path_size_bytes(encrypted_fhew_dir / "cryptoContext.bin"),
        "refresh_key": path_size_bytes(encrypted_fhew_dir / "refreshKey.bin"),
        "switch_key": path_size_bytes(encrypted_fhew_dir / "ksKey.bin"),
        "label_metadata": path_size_bytes(encrypted_fhew_dir / "fhew_category_label_metadata.csv"),
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
    result_rows = [
        [row["code"], row["label"], row["count"], f"{float(row['percent']) * 100.0:.2f}%"]
        for row in sorted(reference, key=lambda item: int(item["count"]), reverse=True)
    ]

    report = f"""# Home Credit FHEW Category Count Benchmark

## Case

| Field | Value |
| --- | --- |
| Notebook section | `{summary['section']}` |
| Notebook EDA | `{summary['label']}` |
| Workload | `{summary['workload']}` |
| Input | `{summary['input']}` |
| Column | `{summary['column']}` |
| Rows requested | `{summary['row_limit']}` |
| Rows scanned | `{summary['row_count']}` |
| Label count | `{summary['label_count']}` |
| FHEW bit width | `{metadata['bit_width']}` |
| Security profile | `{metadata['security']}` |
| Correctness | **{summary['correctness']}** |

## What This EDA Computes

This case computes category counts and percentages for `{summary['column']}`.
The source provides metadata mapping category labels to numeric codes and
encrypts category-code bits. The source does not prepare one-hot masks.

## Data Preparation Before Encryption

```text
raw category -> normalized label -> metadata code -> encrypted code bits
```

Null or blank category values are normalized to `__MISSING__`.

## HE Operation Path

```text
For each row and each known label code:
  membership = encrypted(category_code == plaintext_label_code)

For each label:
  encrypted_count_bits = binary_add(encrypted_count_bits, membership)
```

## Timing Summary

{markdown_table(["Metric", "Seconds"], timing_rows)}

## Artifact Size Summary

{markdown_table(["Artifact", "Size", "Bytes"], size_rows)}

## Result Preview

{markdown_table(["Code", "Label", "Count", "Percent"], result_rows)}

## Artifacts

| Artifact | Path |
| --- | --- |
| JSON summary | `{path.parent / 'benchmark_summary.json'}` |
| Plaintext reference | `{artifacts['plaintext_reference']}` |
| Decrypted HE result | `{artifacts['decrypted_csv']}` |
| Encrypted FHEW bundle | `{artifacts['encrypted_fhew_dir']}` |
| HE server output | `{artifacts['server_output_dir']}` |

## Notes

- This benchmark uses FHEW encrypted equality, not CKKS one-hot masks.
- Runtime scales with `rows * labels * code_bit_width` Boolean gates.
- The HE server sees plaintext label-code metadata, but not row-level category
  values.
"""
    path.write_text(report, encoding="utf-8")


def main() -> None:
    args = parse_args()
    if args.row_limit <= 0:
        raise SystemExit("FHEW category benchmark requires a positive --row-limit")
    cfg = WORKLOADS[args.workload]
    bit_width = int(cfg["bit_width"] if args.bit_width is None else args.bit_width)

    repo = Path.cwd()
    input_path = Path(args.input)
    run_name = args.run_name or f"fhew_{args.workload}_{args.row_limit}_{int(time.time())}"
    run_dir = Path(args.output_root) / run_name
    if run_dir.exists() and not args.keep_existing:
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    encrypted_root = run_dir / "encrypted"
    encrypted_fhew_dir = encrypted_root / "category" / "fhew"
    key_dir = run_dir / "keys"
    server_dir = run_dir / "server_output"
    decrypted_csv = run_dir / "decrypted_counts.csv"
    reference_csv = run_dir / "plaintext_reference.csv"
    markdown_report = run_dir / f"fhew_{args.workload}_report.md"

    timings: dict[str, float] = {}
    reference, row_count, timings["python_reference_seconds"] = plaintext_reference(
        input_path,
        str(cfg["column"]),
        args.row_limit,
    )
    write_reference(reference_csv, reference)

    encrypt_command = [
        str(Path(args.build_dir) / "encrypt_home_credit_fhew_category"),
        "--input",
        str(input_path),
        "--column",
        str(cfg["column"]),
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
        str(Path(args.build_dir) / "server_home_credit_fhew_category_count"),
        "--context",
        str(encrypted_fhew_dir / "cryptoContext.bin"),
        "--refresh-key",
        str(encrypted_fhew_dir / "refreshKey.bin"),
        "--switch-key",
        str(encrypted_fhew_dir / "ksKey.bin"),
        "--code-manifest",
        str(encrypted_fhew_dir / "fhew_category_code_manifest.csv"),
        "--label-metadata",
        str(encrypted_fhew_dir / "fhew_category_label_metadata.csv"),
        "--input-dir",
        str(encrypted_fhew_dir),
        "--output-dir",
        str(server_dir),
    ]
    timings["he_server_wall_seconds"], server_output = run_command(server_command, repo)
    timings.update(parse_timing_lines(server_output, "he_server"))

    decrypt_command = [
        str(Path(args.build_dir) / "decrypt_home_credit_fhew_category_count"),
        "--context",
        str(key_dir / "fhew_crypto_context.bin"),
        "--secret-key",
        str(key_dir / "fhew_secret_key.bin"),
        "--manifest",
        str(server_dir / "fhew_category_count_manifest.csv"),
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
    metadata_path = server_dir / "fhew_category_count_run_metadata.json"
    if metadata_path.exists():
        server_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    summary = {
        "workload": args.workload,
        "section": cfg["section"],
        "label": cfg["label"],
        "input": str(input_path),
        "column": cfg["column"],
        "row_limit": args.row_limit,
        "row_count": row_count,
        "label_count": len(reference),
        "run_dir": str(run_dir),
        "correctness": "passed" if passed else "failed",
        "failures": failures[:20],
        "metadata": {
            "bit_width": bit_width,
            "security": args.security,
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
