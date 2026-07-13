#!/usr/bin/env python3
"""Benchmark Home Credit previous_application category counts under CKKS HE.

This runner is for notebook section 5.15. It computes a plaintext Python
reference first, prepares encrypted previous_application category masks, runs
the OpenFHE aggregate server, decrypts the count results, compares correctness,
and writes a Markdown report.
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
    "prev_contract_type": {
        "section": "5.15.1",
        "title": "Previous Contract Type",
        "column": "NAME_CONTRACT_TYPE",
        "category_mode": "all",
    },
    "prev_contract_status": {
        "section": "5.15.4",
        "title": "Previous Contract Status",
        "column": "NAME_CONTRACT_STATUS",
        "category_mode": "all",
    },
    "prev_reject_reason": {
        "section": "5.15.6",
        "title": "Previous Reject Reason",
        "column": "CODE_REJECT_REASON",
        "category_mode": "all",
    },
    "prev_channel_type": {
        "section": "5.15.12",
        "title": "Previous Channel Type",
        "column": "CHANNEL_TYPE",
        "category_mode": "all",
    },
    "prev_yield_group": {
        "section": "5.15.14",
        "title": "Previous Yield Group",
        "column": "NAME_YIELD_GROUP",
        "category_mode": "all",
    },
    "prev_product_combination": {
        "section": "5.15.15",
        "title": "Previous Product Combination",
        "column": "PRODUCT_COMBINATION",
        "category_mode": "top_k",
        "k": 25,
        "other_bucket": True,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark Home Credit 5.15 previous_application category counts.")
    parser.add_argument("--input", default="data/home_credit/application_train.csv")
    parser.add_argument("--previous-application", default="data/home_credit/previous_application.csv")
    parser.add_argument("--workload", default="prev_contract_status", choices=sorted(WORKLOADS))
    parser.add_argument("--row-limit", type=int, default=0, help="application_train row limit. 0 means all rows.")
    parser.add_argument("--previous-row-limit", type=int, default=0, help="previous_application row limit. 0 means all rows.")
    parser.add_argument("--slots", type=int, default=8192)
    parser.add_argument("--build-dir", default="build")
    parser.add_argument("--output-root", default="benchmark_runs/home_credit_previous_category")
    parser.add_argument("--run-name", default="")
    parser.add_argument("--tolerance", type=float, default=1e-3)
    parser.add_argument("--keep-existing", action="store_true")
    parser.add_argument(
        "--allow-server-percent",
        action="store_true",
        help="Allow server plaintext-total percent rows. Default disables them for stricter HE boundary.",
    )
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


def selected_labels(counts: Counter[str], cfg: dict[str, object]) -> list[str]:
    mode = str(cfg.get("category_mode", "all"))
    if mode == "all":
        return sorted(counts)
    if mode == "top_k":
        labels = [label for label, _ in counts.most_common(int(cfg.get("k", 25)))]
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
    rows = list(iter_rows(input_path, row_limit))
    raw_counts = Counter(normalize_category(row.get(column)) for row in rows)
    labels = selected_labels(raw_counts, cfg)
    counts: Counter[str] = Counter(label_for(row.get(column), labels) for row in rows)
    total = sum(counts.values())
    report: list[dict[str, object]] = []
    for label, count in sorted(counts.items(), key=lambda item: item[1], reverse=True):
        report.append(
            {
                "table": "previous_application",
                "column": column,
                "label": label,
                "count": count,
                "percent": count / total if total else 0.0,
            }
        )
    return report, time.perf_counter() - started


def run_command(command: list[str], cwd: Path) -> tuple[float, str]:
    started = time.perf_counter()
    try:
        completed = subprocess.run(command, cwd=cwd, check=True, text=True, capture_output=True)  # noqa: S603
    except subprocess.CalledProcessError as exc:
        output = "\n".join(part for part in ((exc.stdout or "").strip(), (exc.stderr or "").strip()) if part)
        raise RuntimeError(f"command failed with exit code {exc.returncode}: {' '.join(command)}\n{output}") from exc
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


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def prune_prepared_payload(prepared_dir: Path, analysis: str, group: str) -> dict[str, int]:
    vector_manifest = prepared_dir / "vector_manifest.csv"
    aggregate_operations = prepared_dir / "aggregate_operations.csv"

    with vector_manifest.open("r", encoding="utf-8-sig", newline="") as input_file:
        reader = csv.DictReader(input_file)
        vector_fields = reader.fieldnames or []
        vector_rows = [row for row in reader if row.get("analysis") == analysis and row.get("group") == group]
    if not vector_rows:
        raise ValueError(f"no prepared vectors for analysis={analysis} group={group}")

    keep_vectors = {row["name"] for row in vector_rows}
    for vector_file in (prepared_dir / "vectors").glob("*.csv"):
        if vector_file.stem not in keep_vectors:
            vector_file.unlink()

    with aggregate_operations.open("r", encoding="utf-8-sig", newline="") as input_file:
        reader = csv.DictReader(input_file)
        aggregate_fields = reader.fieldnames or []
        aggregate_rows = [row for row in reader if row.get("analysis") == analysis and row.get("group") == group]
    if not aggregate_rows:
        raise ValueError(f"no aggregate operations for analysis={analysis} group={group}")

    write_csv(vector_manifest, vector_fields, vector_rows)
    write_csv(aggregate_operations, aggregate_fields, aggregate_rows)
    write_csv(prepared_dir / "numeric_vectors.csv", ["column", "vector"], [])
    write_csv(prepared_dir / "linear_score_vectors.csv", ["feature", "vector", "weight", "bias"], [])
    return {"vectors": len(vector_rows), "aggregate_operations": len(aggregate_rows)}


def read_decrypted_counts(path: Path) -> dict[str, float]:
    counts: dict[str, float] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as input_file:
        reader = csv.DictReader(input_file)
        for row in reader:
            if row.get("operation") == "count":
                counts[row["label"]] = float(row["value"])
    return counts


def write_reference(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=["table", "column", "label", "count", "percent"])
        writer.writeheader()
        writer.writerows(rows)


def write_decrypted_report(path: Path, reference: list[dict[str, object]], decrypted: dict[str, float]) -> None:
    total = sum(decrypted.values())
    with path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=["table", "column", "label", "count", "percent"])
        writer.writeheader()
        for row in reference:
            count = decrypted.get(str(row["label"]), float("nan"))
            writer.writerow(
                {
                    "table": row["table"],
                    "column": row["column"],
                    "label": row["label"],
                    "count": count,
                    "percent": count / total if total and math.isfinite(count) else "",
                }
            )


def compare_results(reference: list[dict[str, object]], decrypted: dict[str, float], tolerance: float) -> list[str]:
    failures: list[str] = []
    for expected in reference:
        label = str(expected["label"])
        expected_count = float(expected["count"])
        actual = decrypted.get(label, float("nan"))
        if not math.isfinite(actual) or abs(expected_count - actual) > tolerance:
            failures.append(f"{label} count: expected {expected_count}, got {actual}")
    extra = sorted(set(decrypted) - {str(row["label"]) for row in reference})
    for label in extra:
        failures.append(f"unexpected decrypted label: {label}")
    return failures


def path_size_bytes(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        return sum(child.stat().st_size for child in path.rglob("*") if child.is_file())
    return 0


def human_bytes(value: object) -> str:
    size = float(value)
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    unit = 0
    while size >= 1024 and unit < len(units) - 1:
        size /= 1024
        unit += 1
    return f"{int(size)} {units[unit]}" if unit == 0 else f"{size:.2f} {units[unit]}"


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
        "server_output_dir": path_size_bytes(server_dir),
    }


def format_seconds(value: object) -> str:
    return f"{float(value):.6f}"


def markdown_table(headers: list[str], rows: list[list[object]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(item) for item in row) + " |")
    return "\n".join(lines)


def write_markdown_report(path: Path, summary: dict[str, object], reference: list[dict[str, object]], decrypted: dict[str, float]) -> None:
    timings = summary["timings_seconds"]
    assert isinstance(timings, dict)
    artifact_sizes = summary["artifact_sizes_bytes"]
    assert isinstance(artifact_sizes, dict)
    artifacts = summary["artifacts"]
    assert isinstance(artifacts, dict)
    cfg = summary["workload_config"]
    assert isinstance(cfg, dict)

    total = sum(decrypted.values())
    result_rows = []
    for row in reference[:30]:
        label = str(row["label"])
        count = decrypted.get(label, float("nan"))
        result_rows.append(
            [
                label,
                int(round(count)) if math.isfinite(count) else "",
                f"{(count / total) * 100:.2f}%" if total and math.isfinite(count) else "",
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
        ("prepared_dir", "Prepared plaintext vectors"),
        ("run_dir_total", "Whole benchmark run directory"),
    ):
        if key in artifact_sizes:
            size_rows.append([label, key, human_bytes(artifact_sizes[key]), artifact_sizes[key]])

    report = f"""# Home Credit HE Previous Application Category Benchmark

## Case

| Field | Value |
| --- | --- |
| Notebook section | `{cfg['section']}` |
| Workload | `{summary['workload']}` |
| Title | `{cfg['title']}` |
| Source table | `previous_application.csv` |
| Column | `{cfg['column']}` |
| Application rows used for prep | `{summary['row_limit']}` |
| Previous rows | `{summary['previous_row_limit']}` |
| CKKS slots | `{summary['slots']}` |
| Correctness | **{summary['correctness']}** |

## Python Reference

The notebook-style reference is:

```python
previous_application["{cfg['column']}"].value_counts()
previous_application["{cfg['column']}"].value_counts(normalize=True) * 100
```

## Data Before Encryption

The trusted side normalizes `{cfg['column']}` and creates one 0/1 mask vector
per selected label.

Example:

```text
Approved mask = [1, 0, 1, 0, ...]
Refused mask  = [0, 1, 0, 0, ...]
```

## HE Operation Path

Client/trusted side:

```text
MakeCKKSPackedPlaintext(label_mask)
Encrypt(public_key, packed_mask)
EvalSumKeyGen(secret_key)
```

HE compute side:

```text
count(label) = EvalSum(encrypted_label_mask)
```

Trusted result side:

```text
Decrypt(count(label))
total_rows = sum(decrypted label counts)
percent(label) = count(label) / total_rows
```

This benchmark disables server-side plaintext-total percent rows by passing
`--no-percent` to `server_home_credit_aggregate`, unless `--allow-server-percent`
is explicitly set.

## Timing Summary

{markdown_table(["Metric", "Seconds"], timing_rows)}

## Artifact Size Summary

{markdown_table(["Artifact", "Key", "Size", "Bytes"], size_rows)}

## Result Preview

{markdown_table(["Label", "Count", "Percent"], result_rows)}

## Artifacts

| Artifact | Path |
| --- | --- |
| JSON summary | `{path.parent / 'benchmark_summary.json'}` |
| Plaintext reference | `{artifacts['plaintext_reference']}` |
| Decrypted raw aggregate CSV | `{artifacts['decrypted_raw_csv']}` |
| Decrypted report CSV | `{artifacts['decrypted_report_csv']}` |
| Markdown report | `{path}` |
| Prepared vectors | `{artifacts['prepared_dir']}` |
| Encrypted bundle | `{artifacts['encrypted_dir']}` |
| HE server output | `{artifacts['server_output_dir']}` |
"""
    path.write_text(report, encoding="utf-8")


def main() -> None:
    args = parse_args()
    repo = Path.cwd()
    input_path = Path(args.input)
    previous_path = Path(args.previous_application)
    cfg = WORKLOADS[args.workload]
    run_name = args.run_name or f"{args.workload}_{args.previous_row_limit or 'all'}_{int(time.time())}"
    run_dir = Path(args.output_root) / run_name
    if run_dir.exists() and not args.keep_existing:
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    prepared_dir = run_dir / "prepared"
    encrypted_dir = run_dir / "encrypted"
    key_dir = run_dir / "keys"
    server_dir = run_dir / "server_output" / args.workload
    filtered_manifest = run_dir / "aggregate_manifest.filtered.csv"
    decrypted_raw_csv = run_dir / "decrypted_raw.csv"
    decrypted_report_csv = run_dir / "decrypted_report.csv"
    reference_csv = run_dir / "plaintext_reference.csv"
    markdown_report = run_dir / f"{args.workload}_report.md"
    empty_category_config = run_dir / "no_application_categories.json"
    previous_category_config = run_dir / "previous_category_config.json"
    empty_category_config.write_text('{"categorical_columns":{}}\n', encoding="utf-8")
    previous_category_config.write_text(
        json.dumps(
            {
                "categorical_columns": {
                    str(cfg["column"]): {
                        "mode": cfg.get("category_mode", "all"),
                        **{key: value for key, value in cfg.items() if key in {"k", "other_bucket"}},
                    }
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    timings: dict[str, float] = {}
    reference, timings["python_reference_seconds"] = plaintext_reference(previous_path, args.previous_row_limit, cfg)
    write_reference(reference_csv, reference)

    prepare_command = [
        "python3",
        "code/client/home_credit/prepare_home_credit_basic_eda.py",
        "--input",
        str(input_path),
        "--previous-application",
        str(previous_path),
        "--output-dir",
        str(prepared_dir),
        "--row-limit",
        str(args.row_limit),
        "--previous-row-limit",
        str(args.previous_row_limit),
        "--category-config",
        str(empty_category_config),
        "--previous-category-config",
        str(previous_category_config),
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
    ]
    timings["prepare_wall_seconds"], prepare_output = run_command(prepare_command, repo)
    prepared_pruned = prune_prepared_payload(
        prepared_dir,
        "previous_application_category_counts",
        str(cfg["column"]),
    )

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
        "previous_application_category_counts",
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
        "previous_application_category_counts",
    ]
    if not args.allow_server_percent:
        server_command.append("--no-percent")
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
        str(decrypted_raw_csv),
        "--manifest-type",
        "aggregate",
    ]
    timings["decrypt_wall_seconds"], decrypt_output = run_command(decrypt_command, repo)
    timings.update(parse_timing_lines(decrypt_output, "decrypt"))

    decrypted = read_decrypted_counts(decrypted_raw_csv)
    write_decrypted_report(decrypted_report_csv, reference, decrypted)
    failures = compare_results(reference, decrypted, args.tolerance)
    passed = not failures

    summary = {
        "workload": args.workload,
        "workload_config": cfg,
        "input": str(input_path),
        "previous_application": str(previous_path),
        "row_limit": args.row_limit,
        "previous_row_limit": args.previous_row_limit,
        "slots": args.slots,
        "run_dir": str(run_dir),
        "filtered_manifest_rows": manifest_rows,
        "prepared_pruned": prepared_pruned,
        "server_percent_enabled": bool(args.allow_server_percent),
        "correctness": "passed" if passed else "failed",
        "failures": failures[:20],
        "timings_seconds": timings,
        "artifact_sizes_bytes": collect_artifact_sizes(run_dir, prepared_dir, encrypted_dir, key_dir, server_dir),
        "artifacts": {
            "plaintext_reference": str(reference_csv),
            "decrypted_raw_csv": str(decrypted_raw_csv),
            "decrypted_report_csv": str(decrypted_report_csv),
            "markdown_report": str(markdown_report),
            "prepared_dir": str(prepared_dir),
            "encrypted_dir": str(encrypted_dir),
            "server_output_dir": str(server_dir),
        },
        "decrypted_counts": decrypted,
    }
    (run_dir / "benchmark_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_markdown_report(markdown_report, summary, reference, decrypted)

    print(json.dumps(summary, indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
