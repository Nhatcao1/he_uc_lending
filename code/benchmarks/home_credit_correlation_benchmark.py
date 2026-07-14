#!/usr/bin/env python3
"""Benchmark selected Home Credit Pearson-correlation sufficient stats under HE.

The runner intentionally avoids the web path. It first computes a plaintext
Python reference, then prepares only the selected correlation vectors, encrypts
them, runs the OpenFHE aggregate server, decrypts the aggregate result, compares
the sufficient statistics, and writes a Markdown report.
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


PAIR_PRESETS = {
    "notebook_core": [
        ("AMT_CREDIT", "AMT_INCOME_TOTAL"),
        ("AMT_CREDIT", "AMT_ANNUITY"),
        ("AMT_CREDIT", "AMT_GOODS_PRICE"),
        ("EXT_SOURCE_1", "EXT_SOURCE_2"),
        ("EXT_SOURCE_2", "EXT_SOURCE_3"),
        ("EXT_SOURCE_1", "AGE_YEARS"),
        ("EXT_SOURCE_2", "TARGET"),
        ("EXT_SOURCE_3", "TARGET"),
        ("CREDIT_INCOME_PERCENT", "ANNUITY_INCOME_PERCENT"),
        ("CREDIT_INCOME_PERCENT", "CREDIT_TERM"),
        ("DAYS_EMPLOYED_PERCENT", "TARGET"),
    ],
    "amounts": [
        ("AMT_CREDIT", "AMT_INCOME_TOTAL"),
        ("AMT_CREDIT", "AMT_ANNUITY"),
        ("AMT_CREDIT", "AMT_GOODS_PRICE"),
        ("AMT_ANNUITY", "AMT_INCOME_TOTAL"),
        ("AMT_GOODS_PRICE", "AMT_INCOME_TOTAL"),
    ],
    "ext_sources": [
        ("EXT_SOURCE_1", "EXT_SOURCE_2"),
        ("EXT_SOURCE_1", "EXT_SOURCE_3"),
        ("EXT_SOURCE_2", "EXT_SOURCE_3"),
        ("EXT_SOURCE_1", "AGE_YEARS"),
        ("EXT_SOURCE_2", "TARGET"),
        ("EXT_SOURCE_3", "TARGET"),
    ],
    "domain_ratios": [
        ("CREDIT_INCOME_PERCENT", "ANNUITY_INCOME_PERCENT"),
        ("CREDIT_INCOME_PERCENT", "CREDIT_TERM"),
        ("ANNUITY_INCOME_PERCENT", "CREDIT_TERM"),
        ("DAYS_EMPLOYED_PERCENT", "AGE_YEARS"),
        ("DAYS_EMPLOYED_PERCENT", "TARGET"),
    ],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark Home Credit selected correlation stats with CKKS HE.")
    parser.add_argument("--input", default="data/home_credit/application_train.csv")
    parser.add_argument(
        "--pair-preset",
        default="notebook_core",
        choices=sorted(PAIR_PRESETS),
        help="Notebook-inspired pair preset used when --pairs is omitted.",
    )
    parser.add_argument(
        "--pairs",
        default="",
        help="Semicolon-separated selected pairs, e.g. AMT_CREDIT:AMT_INCOME_TOTAL;AMT_CREDIT:AMT_GOODS_PRICE.",
    )
    parser.add_argument("--row-limit", type=int, default=0, help="0 means all rows.")
    parser.add_argument("--slots", type=int, default=8192)
    parser.add_argument("--build-dir", default="build")
    parser.add_argument("--output-root", default="benchmark_runs/home_credit_correlation")
    parser.add_argument("--run-name", default="")
    parser.add_argument("--tolerance", type=float, default=1e-2)
    parser.add_argument("--keep-existing", action="store_true", help="Do not delete an existing run directory.")
    return parser.parse_args()


def parse_pairs(value: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for raw in value.split(";"):
        cleaned = raw.strip()
        if not cleaned:
            continue
        if ":" not in cleaned:
            raise ValueError(f"correlation pair must be left:right, got: {cleaned}")
        left, right = [part.strip() for part in cleaned.split(":", 1)]
        if not left or not right:
            raise ValueError(f"correlation pair must be left:right, got: {cleaned}")
        pairs.append((left, right))
    if not pairs:
        raise ValueError("at least one correlation pair is required")
    return pairs


def selected_pairs(args: argparse.Namespace) -> list[tuple[str, str]]:
    if args.pairs.strip():
        return parse_pairs(args.pairs)
    return list(PAIR_PRESETS[args.pair_preset])


def parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or abs(denominator) <= 1e-12:
        return None
    value = numerator / denominator
    return value if math.isfinite(value) else None


def value_from_source(row: dict[str, str], source: str) -> float | None:
    if source == "AGE_YEARS":
        days_birth = parse_float(row.get("DAYS_BIRTH"))
        if days_birth is None:
            return None
        return abs(days_birth) / 365.25
    if source == "CREDIT_INCOME_PERCENT":
        return safe_ratio(parse_float(row.get("AMT_CREDIT")), parse_float(row.get("AMT_INCOME_TOTAL")))
    if source == "ANNUITY_INCOME_PERCENT":
        return safe_ratio(parse_float(row.get("AMT_ANNUITY")), parse_float(row.get("AMT_INCOME_TOTAL")))
    if source == "CREDIT_TERM":
        return safe_ratio(parse_float(row.get("AMT_ANNUITY")), parse_float(row.get("AMT_CREDIT")))
    if source == "DAYS_EMPLOYED_PERCENT":
        employed = parse_float(row.get("DAYS_EMPLOYED"))
        birth = parse_float(row.get("DAYS_BIRTH"))
        if employed == 365243:
            return None
        return safe_ratio(employed, birth)
    return parse_float(row.get(source))


def iter_rows(path: Path, row_limit: int):
    with path.open("r", encoding="utf-8-sig", newline="") as input_file:
        reader = csv.DictReader(input_file)
        for index, row in enumerate(reader):
            if row_limit and index >= row_limit:
                break
            yield row


def correlation_from_stats(stats: dict[str, float]) -> float:
    n = stats["n"]
    if n <= 1:
        return float("nan")
    numerator = n * stats["sum_xy"] - stats["sum_x"] * stats["sum_y"]
    left = n * stats["sum_x2"] - stats["sum_x"] * stats["sum_x"]
    right = n * stats["sum_y2"] - stats["sum_y"] * stats["sum_y"]
    denominator = math.sqrt(max(left, 0.0) * max(right, 0.0))
    if denominator <= 1e-12:
        return float("nan")
    return numerator / denominator


def plaintext_reference(input_path: Path, row_limit: int, pairs: list[tuple[str, str]]) -> tuple[list[dict[str, float | str]], float]:
    started = time.perf_counter()
    stats_by_pair: dict[str, dict[str, float]] = {
        f"{left}__{right}": {
            "n": 0.0,
            "sum_x": 0.0,
            "sum_y": 0.0,
            "sum_xy": 0.0,
            "sum_x2": 0.0,
            "sum_y2": 0.0,
        }
        for left, right in pairs
    }

    for row in iter_rows(input_path, row_limit):
        for left, right in pairs:
            left_value = value_from_source(row, left)
            right_value = value_from_source(row, right)
            if left_value is None or right_value is None:
                continue
            stats = stats_by_pair[f"{left}__{right}"]
            stats["n"] += 1.0
            stats["sum_x"] += left_value
            stats["sum_y"] += right_value
            stats["sum_xy"] += left_value * right_value
            stats["sum_x2"] += left_value * left_value
            stats["sum_y2"] += right_value * right_value

    rows: list[dict[str, float | str]] = []
    for left, right in pairs:
        pair_label = f"{left}__{right}"
        stats = stats_by_pair[pair_label]
        rows.append(
            {
                "pair": pair_label,
                "feature_x": left,
                "feature_y": right,
                "n": stats["n"],
                "sum_x": stats["sum_x"],
                "sum_y": stats["sum_y"],
                "sum_xy": stats["sum_xy"],
                "sum_x2": stats["sum_x2"],
                "sum_y2": stats["sum_y2"],
                "correlation": correlation_from_stats(stats),
            }
        )
    return rows, time.perf_counter() - started


def run_command(command: list[str], cwd: Path) -> tuple[float, str]:
    started = time.perf_counter()
    try:
        completed = subprocess.run(command, cwd=cwd, check=True, text=True, capture_output=True)  # noqa: S603
    except subprocess.CalledProcessError as exc:
        output = "\n".join(part for part in ((exc.stdout or "").strip(), (exc.stderr or "").strip()) if part)
        command_text = " ".join(command)
        raise RuntimeError(
            f"command failed with exit code {exc.returncode}: {command_text}\n{output}"
        ) from exc
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


def filter_manifest_by_analysis(source: Path, destination: Path, analysis: str) -> int:
    with source.open("r", encoding="utf-8-sig", newline="") as input_file:
        reader = csv.DictReader(input_file)
        fieldnames = reader.fieldnames or []
        rows = [row for row in reader if row.get("analysis") == analysis]
    if not rows:
        raise ValueError(f"no aggregate manifest rows for analysis={analysis}")
    with destination.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def read_decrypted_stats(path: Path) -> dict[str, dict[str, float]]:
    stats_by_pair: dict[str, dict[str, float]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as input_file:
        reader = csv.DictReader(input_file)
        for row in reader:
            pair = row["group"]
            operation = row["operation"]
            value_name = row["value_name"]
            value = float(row["value"])
            stats = stats_by_pair.setdefault(pair, {})
            if operation == "count" and row["label"] == "n":
                stats["n"] = value
            elif operation == "masked_sum":
                stats[value_name] = value
    for stats in stats_by_pair.values():
        if {"n", "sum_x", "sum_y", "sum_xy", "sum_x2", "sum_y2"} <= set(stats):
            stats["correlation"] = correlation_from_stats(stats)
    return stats_by_pair


def write_reference(path: Path, rows: list[dict[str, float | str]]) -> None:
    fieldnames = ["pair", "feature_x", "feature_y", "n", "sum_x", "sum_y", "sum_xy", "sum_x2", "sum_y2", "correlation"]
    with path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_decrypted_report_csv(path: Path, reference: list[dict[str, float | str]], decrypted: dict[str, dict[str, float]]) -> None:
    fieldnames = ["pair", "n", "sum_x", "sum_y", "sum_xy", "sum_x2", "sum_y2", "correlation"]
    with path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()
        for expected in reference:
            pair = str(expected["pair"])
            stats = decrypted.get(pair, {})
            writer.writerow({"pair": pair, **{key: stats.get(key, "") for key in fieldnames if key != "pair"}})


def compare_results(
    reference: list[dict[str, float | str]], decrypted: dict[str, dict[str, float]], tolerance: float
) -> list[str]:
    failures: list[str] = []
    checked = {"n", "sum_x", "sum_y", "sum_xy", "sum_x2", "sum_y2"}
    for expected in reference:
        pair = str(expected["pair"])
        actual = decrypted.get(pair)
        if actual is None:
            failures.append(f"missing decrypted pair: {pair}")
            continue
        for field in sorted(checked):
            expected_value = float(expected[field])
            actual_value = float(actual.get(field, float("nan")))
            allowed_error = tolerance if field == "n" else tolerance * max(1.0, abs(expected_value))
            if not math.isfinite(actual_value) or abs(expected_value - actual_value) > allowed_error:
                failures.append(f"{pair} {field}: expected {expected_value}, got {actual_value}")
    extra = sorted(set(decrypted) - {str(row["pair"]) for row in reference})
    for pair in extra:
        failures.append(f"unexpected decrypted pair: {pair}")
    return failures


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


def format_seconds(value: object) -> str:
    try:
        return f"{float(value):.6f}"
    except (TypeError, ValueError):
        return ""


def markdown_table(headers: list[str], rows: list[list[object]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(item) for item in row) + " |")
    return "\n".join(lines)


def write_markdown_report(path: Path, summary: dict[str, object], reference: list[dict[str, float | str]]) -> None:
    timings = summary["timings_seconds"]
    assert isinstance(timings, dict)
    artifact_sizes = summary["artifact_sizes_bytes"]
    assert isinstance(artifact_sizes, dict)
    artifacts = summary["artifacts"]
    assert isinstance(artifacts, dict)

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

    result_rows = []
    decrypted = summary["decrypted_stats"]
    assert isinstance(decrypted, dict)
    for row in reference:
        pair = str(row["pair"])
        actual = decrypted.get(pair, {})
        if not isinstance(actual, dict):
            actual = {}
        result_rows.append(
            [
                pair,
                int(round(float(actual.get("n", float("nan"))))) if "n" in actual else "",
                f"{float(actual.get('sum_x', float('nan'))):.6g}" if "sum_x" in actual else "",
                f"{float(actual.get('sum_y', float('nan'))):.6g}" if "sum_y" in actual else "",
                f"{float(actual.get('sum_xy', float('nan'))):.6g}" if "sum_xy" in actual else "",
                f"{float(actual.get('correlation', float('nan'))):.6f}" if "correlation" in actual else "",
            ]
        )

    report = f"""# Home Credit HE Correlation Benchmark Report

## Case

| Field | Value |
| --- | --- |
| Workload | `selected_correlation_stats` |
| Input | `{summary['input']}` |
| Rows | `{summary['row_limit']}` |
| Pair preset | `{summary['pair_preset']}` |
| Pairs | `{summary['pairs']}` |
| CKKS slots | `{summary['slots']}` |
| Correctness | **{summary['correctness']}** |

## What This EDA Computes

This benchmark reproduces the sufficient statistics needed for selected
Pearson-correlation pairs. The final division and square root are done after
decryption.

The selected default preset follows the notebook flow: amount relationships,
`EXT_SOURCE` relationships, target relationships, and domain-ratio features.
Derived values such as `AGE_YEARS`, `CREDIT_INCOME_PERCENT`,
`ANNUITY_INCOME_PERCENT`, `CREDIT_TERM`, and `DAYS_EMPLOYED_PERCENT` are
prepared inside the benchmark/prep code before encryption.

## Python Reference First

The runner computes the plaintext Python reference before starting HE. This
provides the baseline latency and correctness target.

## HE Operation Path

Client/trusted side:

```text
create x, y, and valid-pair mask vectors
MakeCKKSPackedPlaintext(...)
Encrypt(public_key, packed_vector)
EvalSumKeyGen(secret_key)
EvalMultKeyGen(secret_key)
```

HE compute side:

```text
n      = EvalSum(valid_mask)
sum_x  = EvalSum(valid_mask * x)
sum_y  = EvalSum(valid_mask * y)
sum_xy = EvalSum(x * y)
sum_x2 = EvalSum(x * x)
sum_y2 = EvalSum(y * y)
```

Trusted result side:

```text
corr = (n * sum_xy - sum_x * sum_y)
       / sqrt((n * sum_x2 - sum_x^2) * (n * sum_y2 - sum_y^2))
```

## Timing Summary

{markdown_table(["Metric", "Seconds"], timing_rows)}

## Artifact Size Summary

{markdown_table(["Artifact", "Key", "Size", "Bytes"], size_rows)}

## Result Preview

{markdown_table(["Pair", "n", "sum_x", "sum_y", "sum_xy", "correlation"], result_rows)}

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


def write_failure_markdown_report(path: Path, summary: dict[str, object]) -> None:
    timings = summary.get("timings_seconds", {})
    assert isinstance(timings, dict)
    artifact_sizes = summary.get("artifact_sizes_bytes", {})
    assert isinstance(artifact_sizes, dict)
    artifacts = summary.get("artifacts", {})
    assert isinstance(artifacts, dict)

    timing_rows = [[key, format_seconds(value)] for key, value in sorted(timings.items())]
    size_rows = []
    for key, value in sorted(artifact_sizes.items()):
        size_rows.append([key, human_bytes(value), value])

    report = f"""# Home Credit HE Correlation Benchmark Report

## Case

| Field | Value |
| --- | --- |
| Workload | `selected_correlation_stats` |
| Input | `{summary.get('input', '')}` |
| Rows | `{summary.get('row_limit', '')}` |
| Pair preset | `{summary.get('pair_preset', '')}` |
| Pairs | `{summary.get('pairs', '')}` |
| CKKS slots | `{summary.get('slots', '')}` |
| Correctness | **failed** |
| Failure stage | `{summary.get('failure_stage', '')}` |

## Failure

```text
{summary.get('error', '')}
```

This report is still useful for performance review: artifacts and timings up to
the failure point are preserved. A common failure for large raw amount
correlations is CKKS decode failure from approximation error after multiplying
large values and summing many rows. The usual fix is scaling amount features
before encryption, because Pearson correlation is scale invariant.

## Timing Summary

{markdown_table(["Metric", "Seconds"], timing_rows)}

## Artifact Size Summary

{markdown_table(["Artifact", "Size", "Bytes"], size_rows)}

## Artifacts

| Artifact | Path |
| --- | --- |
| JSON summary | `{path.parent / 'benchmark_summary.json'}` |
| Plaintext reference | `{artifacts.get('plaintext_reference', '')}` |
| Decrypted raw aggregate CSV | `{artifacts.get('decrypted_raw_csv', '')}` |
| Decrypted report CSV | `{artifacts.get('decrypted_report_csv', '')}` |
| Markdown report | `{path}` |
| Prepared vectors | `{artifacts.get('prepared_dir', '')}` |
| Encrypted bundle | `{artifacts.get('encrypted_dir', '')}` |
| HE server output | `{artifacts.get('server_output_dir', '')}` |
"""
    path.write_text(report, encoding="utf-8")


def main() -> None:
    args = parse_args()
    repo = Path.cwd()
    input_path = Path(args.input)
    pairs = selected_pairs(args)
    pair_arg = ";".join(f"{left}:{right}" for left, right in pairs)
    run_name = args.run_name or f"correlation_{args.row_limit or 'all'}_{int(time.time())}"
    run_dir = Path(args.output_root) / run_name
    if run_dir.exists() and not args.keep_existing:
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    prepared_dir = run_dir / "prepared"
    encrypted_dir = run_dir / "encrypted"
    key_dir = run_dir / "keys"
    server_dir = run_dir / "server_output" / "selected_correlation_stats"
    filtered_manifest = run_dir / "aggregate_manifest.filtered.csv"
    decrypted_raw_csv = run_dir / "decrypted_raw.csv"
    decrypted_report_csv = run_dir / "decrypted_correlation.csv"
    reference_csv = run_dir / "plaintext_reference.csv"
    markdown_report = run_dir / "selected_correlation_stats_report.md"
    empty_category_config = run_dir / "no_categories.json"
    empty_category_config.write_text('{"categorical_columns":{}}\n', encoding="utf-8")

    timings: dict[str, float] = {}
    reference: list[dict[str, float | str]] = []
    manifest_rows = 0
    stage = "python_reference"
    try:
        reference, timings["python_reference_seconds"] = plaintext_reference(input_path, args.row_limit, pairs)
        write_reference(reference_csv, reference)

        stage = "prepare"
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
            str(empty_category_config),
            "--amount-columns",
            "",
            "--numeric-columns",
            "",
            "--missing-columns",
            "",
            "--histogram-columns",
            "",
            "--correlation-pairs",
            pair_arg,
        ]
        timings["prepare_wall_seconds"], prepare_output = run_command(prepare_command, repo)

        stage = "encrypt"
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

        stage = "filter_manifest"
        manifest_rows = filter_manifest_by_analysis(
            encrypted_dir / "aggregate_manifest.csv",
            filtered_manifest,
            "selected_correlation_stats",
        )

        stage = "he_server"
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
            "selected_correlation_stats",
        ]
        timings["he_server_wall_seconds"], server_output = run_command(server_command, repo)
        timings.update(parse_timing_lines(server_output, "he_server"))

        stage = "decrypt"
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

        stage = "compare"
        decrypted = read_decrypted_stats(decrypted_raw_csv)
        write_decrypted_report_csv(decrypted_report_csv, reference, decrypted)
        failures = compare_results(reference, decrypted, args.tolerance)
        passed = not failures

        summary = {
            "workload": "selected_correlation_stats",
            "input": str(input_path),
            "row_limit": args.row_limit,
            "slots": args.slots,
            "pair_preset": args.pair_preset if not args.pairs.strip() else "custom",
            "pairs": pair_arg,
            "run_dir": str(run_dir),
            "reference_rows": len(reference),
            "filtered_manifest_rows": manifest_rows,
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
            "decrypted_stats": decrypted,
        }
        (run_dir / "benchmark_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        write_markdown_report(markdown_report, summary, reference)

        print(json.dumps(summary, indent=2))
        if not passed:
            raise SystemExit(1)
    except Exception as exc:
        summary = {
            "workload": "selected_correlation_stats",
            "input": str(input_path),
            "row_limit": args.row_limit,
            "slots": args.slots,
            "pair_preset": args.pair_preset if not args.pairs.strip() else "custom",
            "pairs": pair_arg,
            "run_dir": str(run_dir),
            "reference_rows": len(reference),
            "filtered_manifest_rows": manifest_rows,
            "correctness": "failed",
            "failure_stage": stage,
            "error": str(exc),
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
        }
        (run_dir / "benchmark_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        write_failure_markdown_report(markdown_report, summary)
        print(json.dumps(summary, indent=2))
        raise


if __name__ == "__main__":
    main()
