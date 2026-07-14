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

INCOME_TYPE_LABELS = [
    "Working",
    "Commercial associate",
    "Pensioner",
    "State servant",
    "Unemployed",
    "Student",
    "Businessman",
]

FAMILY_STATUS_LABELS = [
    "Married",
    "Single / not married",
    "Civil marriage",
    "Separated",
    "Widow",
]

OCCUPATION_TYPE_LABELS = [
    "Laborers",
    "Sales staff",
    "Core staff",
    "Managers",
    "Drivers",
    "High skill tech staff",
    "Accountants",
    "Medicine staff",
    "Security staff",
    "Cooking staff",
    "Cleaning staff",
    "Private service staff",
    "Low-skill Laborers",
    "Waiters/barmen staff",
    "Secretaries",
    "Realty agents",
]

EDUCATION_TYPE_LABELS = [
    "Secondary / secondary special",
    "Higher education",
    "Incomplete higher",
    "Lower secondary",
    "Academic degree",
]

HOUSING_TYPE_LABELS = [
    "House / apartment",
    "With parents",
    "Municipal apartment",
    "Rented apartment",
    "Office apartment",
]

ORGANIZATION_TYPE_LABELS = [
    "Business Entity Type 3",
    "XNA",
    "Self-employed",
    "Other",
    "Medicine",
    "Business Entity Type 2",
    "Government",
    "School",
    "Trade: type 7",
    "Kindergarten",
    "Construction",
    "Business Entity Type 1",
    "Transport: type 4",
    "Trade: type 3",
    "Industry: type 9",
    "Industry: type 3",
    "Security",
    "Housing",
    "Industry: type 11",
    "Military",
    "Bank",
    "Agriculture",
    "Police",
    "Transport: type 2",
    "Postal",
    "Security Ministries",
    "Trade: type 2",
    "Restaurant",
    "Services",
    "University",
    "Industry: type 7",
    "Transport: type 3",
    "Industry: type 4",
    "Hotel",
    "Electricity",
    "Industry: type 1",
    "Trade: type 6",
    "Industry: type 5",
    "Insurance",
    "Telecom",
    "Emergency",
    "Industry: type 2",
    "Advertising",
    "Realtor",
    "Culture",
    "Industry: type 12",
    "Trade: type 1",
    "Mobile",
    "Legal Services",
    "Cleaning",
    "Transport: type 1",
    "Industry: type 6",
    "Industry: type 10",
]

SUITE_TYPE_LABELS = [
    "Unaccompanied",
    "Family",
    "Spouse, partner",
    "Children",
    "Other_B",
    "Other_A",
    "Group of people",
]

WORKLOADS = {
    "app_target_by_income_type": {
        "section": "5.14.1",
        "title": "Income Type by Target",
        "column": "NAME_INCOME_TYPE",
        "analysis": "application_default_rates",
        "category_mode": "labels",
        "labels": INCOME_TYPE_LABELS,
    },
    "app_target_by_family_status": {
        "section": "5.14.2",
        "title": "Family Status by Target",
        "column": "NAME_FAMILY_STATUS",
        "analysis": "application_default_rates",
        "category_mode": "labels",
        "labels": FAMILY_STATUS_LABELS,
    },
    "app_target_by_occupation_type": {
        "section": "5.14.3",
        "title": "Occupation by Target",
        "column": "OCCUPATION_TYPE",
        "analysis": "application_default_rates",
        "category_mode": "labels",
        "labels": OCCUPATION_TYPE_LABELS,
    },
    "app_target_by_education_type": {
        "section": "5.14.4",
        "title": "Education by Target",
        "column": "NAME_EDUCATION_TYPE",
        "analysis": "application_default_rates",
        "category_mode": "labels",
        "labels": EDUCATION_TYPE_LABELS,
    },
    "app_target_by_housing_type": {
        "section": "5.14.5",
        "title": "Housing Type by Target",
        "column": "NAME_HOUSING_TYPE",
        "analysis": "application_default_rates",
        "category_mode": "labels",
        "labels": HOUSING_TYPE_LABELS,
    },
    "app_target_by_organization_type": {
        "section": "5.14.6",
        "title": "Organization Type by Target",
        "column": "ORGANIZATION_TYPE",
        "analysis": "application_default_rates",
        "category_mode": "labels",
        "labels": ORGANIZATION_TYPE_LABELS,
    },
    "app_target_by_suite_type": {
        "section": "5.14.7",
        "title": "Suite Type by Target",
        "column": "NAME_TYPE_SUITE",
        "analysis": "application_default_rates",
        "category_mode": "labels",
        "labels": SUITE_TYPE_LABELS,
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
    parser.add_argument("--tolerance", type=float, default=1e-4)
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
    if mode == "labels":
        labels = [str(label) for label in cfg.get("labels", [])]
        if not labels:
            raise ValueError("labels mode requires a non-empty labels list")
        return labels
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
        if cfg.get("category_mode") == "labels" and label not in labels:
            continue
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


def format_seconds(value: object) -> str:
    try:
        return f"{float(value):.6f}"
    except (TypeError, ValueError):
        return ""


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


def collect_artifact_sizes(run_dir: Path, prepared_dir: Path, encrypted_dir: Path, key_dir: Path, server_dir: Path) -> dict[str, int]:
    return {
        "run_dir_total": path_size_bytes(run_dir),
        "prepared_dir": path_size_bytes(prepared_dir),
        "encrypted_dir_server_upload_total": path_size_bytes(encrypted_dir),
        "encrypted_vectors_dir": path_size_bytes(encrypted_dir / "vectors"),
        "crypto_context": path_size_bytes(encrypted_dir / "crypto_context.bin"),
        "public_key": path_size_bytes(encrypted_dir / "public_key.bin"),
        "eval_sum_keys": path_size_bytes(encrypted_dir / "eval_sum_keys.bin"),
        "eval_mult_keys": path_size_bytes(encrypted_dir / "eval_mult_keys.bin"),
        "aggregate_manifest": path_size_bytes(encrypted_dir / "aggregate_manifest.csv"),
        "client_secret_key": path_size_bytes(key_dir / "secret_key.bin"),
        "client_key_dir_total": path_size_bytes(key_dir),
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
    artifacts = summary["artifacts"]
    assert isinstance(artifacts, dict)
    artifact_sizes = summary.get("artifact_sizes_bytes", {})
    assert isinstance(artifact_sizes, dict)

    result_rows = []
    for row in reference[:20]:
        count = int(row["count"])
        default_count = int(row["default_count"])
        result_rows.append(
            [
                row["label"],
                count,
                f"{float(row['percent']) * 100:.2f}%",
                default_count,
                f"{float(row['default_rate']) * 100:.2f}%",
            ]
        )

    timing_rows = []
    for key in (
        "python_reference_seconds",
        "prepare_wall_seconds",
        "encrypt.make_context_seconds",
        "encrypt.keygen_seconds",
        "encrypt.eval_mult_keygen_seconds",
        "encrypt.eval_sum_keygen_seconds",
        "encrypt.encrypt_vectors_seconds",
        "encrypt.total_seconds",
        "he_server.aggregate_compute_seconds",
        "he_server.total_seconds",
        "decrypt.decrypt_rows_seconds",
        "decrypt.total_seconds",
    ):
        if key in timings:
            timing_rows.append([key, format_seconds(timings[key])])

    size_rows = []
    for key, label in (
        ("encrypted_dir_server_upload_total", "Server upload material total"),
        ("encrypted_vectors_dir", "Encrypted vectors"),
        ("crypto_context", "Crypto context"),
        ("public_key", "Public key"),
        ("eval_sum_keys", "Eval sum keys"),
        ("eval_mult_keys", "Eval mult keys"),
        ("aggregate_manifest", "Aggregate manifest"),
        ("server_output_dir", "Encrypted HE result"),
        ("client_secret_key", "Client secret key"),
        ("client_key_dir_total", "Client key directory total"),
        ("prepared_dir", "Prepared plaintext vectors"),
        ("run_dir_total", "Whole benchmark run directory"),
    ):
        if key in artifact_sizes:
            size_rows.append([label, key, human_bytes(artifact_sizes[key]), artifact_sizes[key]])

    report = f"""# Home Credit HE EDA Benchmark Report

## Case

| Field | Value |
| --- | --- |
| Workload | `{summary['workload']}` |
| Notebook section | `{summary.get('notebook_section', '')}` |
| Title | `{summary.get('title', '')}` |
| Input | `{summary['input']}` |
| Rows | `{summary['row_limit']}` |
| Group column | `{summary['selected_group']}` |
| CKKS slots | `{summary['slots']}` |
| Correctness | **{summary['correctness']}** |

## What This EDA Computes

This case computes the default count and default rate for each selected group.
The plaintext Python result is used only as a local benchmark reference.

## Data Preparation Before Encryption

The trusted side reads the raw Home Credit application table, normalizes the
group column, creates one 0/1 mask per notebook label, creates a `TARGET=1`
mask, and writes vector manifests for encryption. Rows outside the notebook
label list are ignored for this benchmark so the output matches the notebook
chart categories.

## HE Operation Path

Client/trusted side:

```text
MakeCKKSPackedPlaintext(group_mask)
MakeCKKSPackedPlaintext(target_mask)
Encrypt(public_key, packed_mask)
EvalSumKeyGen(secret_key)
EvalMultKeyGen(secret_key)
```

HE compute side:

```text
group_count = EvalSum(encrypted_group_mask)
default_count = EvalSum(EvalMultAndRelinearize(encrypted_group_mask, encrypted_target_mask))
```

Trusted result side:

```text
Decrypt(group_count)
Decrypt(default_count)
default_rate = default_count / group_count
```

## Timing Summary

{markdown_table(["Metric", "Seconds"], timing_rows)}

## Artifact Size Summary

{markdown_table(["Artifact", "Key", "Size", "Bytes"], size_rows)}

Important deployment boundary:

- Server-upload material includes `crypto_context.bin`, public/evaluation keys,
  encrypted vectors, and manifests.
- Client-only material includes the secret key and decrypted/reference reports.
- Prepared plaintext vectors are benchmark artifacts only; they must not be sent
  to the untrusted HE server in a real deployment.

## Result Preview

{markdown_table(["Segment", "Count", "Percent", "Default count", "Default rate"], result_rows)}

## Artifacts

| Artifact | Path |
| --- | --- |
| JSON summary | `{path.parent / 'benchmark_summary.json'}` |
| Plaintext reference | `{artifacts['plaintext_reference']}` |
| Decrypted HE result | `{artifacts['decrypted_csv']}` |
| Prepared vectors | `{artifacts['prepared_dir']}` |
| Encrypted bundle | `{artifacts['encrypted_dir']}` |
| HE server output | `{artifacts['server_output_dir']}` |

## Notes

- This report is generated under `benchmark_runs/`, which is ignored by git.
- Use it as an external slide/report input. It is not intended as permanent
  planning context unless explicitly referenced.
"""
    path.write_text(report, encoding="utf-8")


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
    markdown_report = run_dir / f"{args.workload}_report.md"
    category_config = run_dir / "category_config.json"
    empty_model = run_dir / "empty_linear_model.json"
    category_config.write_text(
        json.dumps(
            {
                "categorical_columns": {
                    str(cfg["column"]): {
                        "mode": cfg.get("category_mode", "all"),
                        "labels": cfg.get("labels", []),
                        **{key: value for key, value in cfg.items() if key in {"k", "other_bucket"}},
                    }
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    empty_model.write_text(
        json.dumps(
            {
                "model_type": "empty_benchmark_model",
                "trained": False,
                "bias": 0.0,
                "features": [],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

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
        "--category-config",
        str(category_config),
        "--amount-columns",
        "",
        "--numeric-columns",
        "",
        "--missing-columns",
        "",
        "--histogram-columns",
        "",
        "--correlation-pairs",
        "",
        "--model-json",
        str(empty_model),
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
        "notebook_section": cfg.get("section", ""),
        "title": cfg.get("title", ""),
        "label_policy": cfg.get("category_mode", "all"),
        "labels": cfg.get("labels", []),
        "reference_rows": len(reference),
        "filtered_manifest_rows": manifest_rows,
        "correctness": "passed" if passed else "failed",
        "failures": failures[:20],
        "timings_seconds": timings,
        "artifact_sizes_bytes": collect_artifact_sizes(run_dir, prepared_dir, encrypted_dir, key_dir, server_dir),
        "artifacts": {
            "plaintext_reference": str(reference_csv),
            "decrypted_csv": str(decrypted_csv),
            "markdown_report": str(markdown_report),
            "prepared_dir": str(prepared_dir),
            "encrypted_dir": str(encrypted_dir),
            "server_output_dir": str(server_dir),
        },
    }
    (run_dir / "benchmark_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_markdown_report(markdown_report, summary, reference)

    print(json.dumps(summary, indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
