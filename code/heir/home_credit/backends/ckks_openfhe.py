"""CKKS/OpenFHE executor for HEIR-prepared Home Credit tensors.

This backend keeps the HEIR benchmark contract: fixed-shape numeric tensors and
manifest-driven kernels. The current executor uses the existing handwritten
OpenFHE CKKS binaries so we can measure real encrypted work while HEIR CKKS
code generation is still being wired in.
"""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


def run_command(command: list[str], cwd: Path) -> tuple[float, str]:
    started = time.perf_counter()
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True)  # noqa: S603
    output = completed.stdout + completed.stderr
    if completed.returncode != 0:
        raise RuntimeError(
            "command failed with exit code "
            f"{completed.returncode}: {' '.join(command)}\n{output}"
        )
    return time.perf_counter() - started, output


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as input_file:
        return list(csv.DictReader(input_file))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def copy_vector_without_header(source: Path, destination: Path) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    row_count = 0
    with source.open("r", encoding="utf-8-sig", newline="") as input_file:
        reader = csv.DictReader(input_file)
        with destination.open("w", encoding="utf-8", newline="") as output_file:
            for row in reader:
                output_file.write(f"{float(row['value']):.17g}\n")
                row_count += 1
    return row_count


def materialize_ckks_prepared(run_dir: Path, analysis_name: str) -> Path:
    prepared_dir = run_dir / "ckks_prepared"
    vector_dir = prepared_dir / "vectors"
    if prepared_dir.exists():
        shutil.rmtree(prepared_dir)
    vector_dir.mkdir(parents=True, exist_ok=True)

    tensor_rows = read_csv(run_dir / "tensor_manifest.csv")
    vector_manifest_rows: list[dict[str, Any]] = []
    aggregate_rows: list[dict[str, Any]] = []
    target_vector = ""

    for row in tensor_rows:
        name = row["name"]
        kind = row["kind"]
        label = row["label"]
        source_file = run_dir / row["file"]
        vector_name = name.replace(".", "_")
        destination = vector_dir / f"{vector_name}.csv"
        row_count = copy_vector_without_header(source_file, destination)
        if row_count != int(row["rows"]):
            raise ValueError(f"row count mismatch for {name}: manifest={row['rows']} actual={row_count}")

        vector_manifest_rows.append(
            {
                "name": vector_name,
                "kind": "mask",
                "source_column": "",
                "analysis": analysis_name,
                "group": "target" if kind == "target_mask" else "category",
                "label": label,
                "rows": row_count,
                "file": destination.relative_to(prepared_dir).as_posix(),
            }
        )
        if kind == "target_mask":
            target_vector = vector_name

    if not target_vector:
        raise ValueError("tensor manifest has no target_mask row")

    for row in tensor_rows:
        if row["kind"] != "group_mask":
            continue
        vector_name = row["name"].replace(".", "_")
        aggregate_rows.append(
            {
                "analysis": analysis_name,
                "group": "target_by_category",
                "label": row["label"],
                "operation": "count",
                "value_name": "",
                "mask_vector": vector_name,
                "value_vector": "",
            }
        )
        aggregate_rows.append(
            {
                "analysis": analysis_name,
                "group": "target_by_category",
                "label": row["label"],
                "operation": "default_count",
                "value_name": "TARGET=1",
                "mask_vector": vector_name,
                "value_vector": target_vector,
            }
        )

    write_csv(
        prepared_dir / "vector_manifest.csv",
        ["name", "kind", "source_column", "analysis", "group", "label", "rows", "file"],
        vector_manifest_rows,
    )
    write_csv(
        prepared_dir / "aggregate_operations.csv",
        ["analysis", "group", "label", "operation", "value_name", "mask_vector", "value_vector"],
        aggregate_rows,
    )
    write_csv(prepared_dir / "numeric_vectors.csv", ["column", "vector"], [])
    write_csv(prepared_dir / "linear_score_vectors.csv", ["feature", "vector", "weight", "bias"], [])
    return prepared_dir


def parse_decrypted_aggregate(path: Path) -> list[dict[str, Any]]:
    rows = read_csv(path)
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        label = row["label"]
        item = grouped.setdefault(label, {"label": label, "count": 0.0, "default_count": 0.0})
        if row["operation"] == "count":
            item["count"] = float(row["value"])
        elif row["operation"] == "default_count":
            item["default_count"] = float(row["value"])
    results = []
    for item in grouped.values():
        count = item["count"]
        default_count = item["default_count"]
        results.append(
            {
                "label": item["label"],
                "count": count,
                "default_count": default_count,
                "default_rate": default_count / count if count else 0.0,
            }
        )
    return results


def run_ckks_openfhe_backend(
    run_dir: Path,
    build_dir: Path,
    analysis_name: str,
    slots: int,
    multiplicative_depth: int,
    scaling_mod_size: int,
    first_mod_size: int,
) -> tuple[dict[str, float], dict[str, Any], str]:
    prepared_dir = materialize_ckks_prepared(run_dir, analysis_name)
    encrypted_dir = run_dir / "ckks_encrypted"
    key_dir = run_dir / "ckks_keys"
    server_output_dir = run_dir / "ckks_server_output" / analysis_name
    decrypted_csv = run_dir / "ckks_decrypted.csv"
    for path in (encrypted_dir, key_dir, server_output_dir):
        if path.exists():
            shutil.rmtree(path)
    timings: dict[str, float] = {}
    logs: list[str] = []

    timings["ckks_encrypt_wall_seconds"], output = run_command(
        [
            str(build_dir / "encrypt_home_credit_payload"),
            "--prepared-dir",
            str(prepared_dir),
            "--server-output-dir",
            str(encrypted_dir),
            "--client-key-dir",
            str(key_dir),
            "--slots",
            str(slots),
            "--multiplicative-depth",
            str(multiplicative_depth),
            "--scaling-mod-size",
            str(scaling_mod_size),
            "--first-mod-size",
            str(first_mod_size),
        ],
        Path.cwd(),
    )
    logs.append(output)

    timings["ckks_server_wall_seconds"], output = run_command(
        [
            str(build_dir / "server_home_credit_aggregate"),
            "--context",
            str(encrypted_dir / "crypto_context.bin"),
            "--eval-sum-keys",
            str(encrypted_dir / "eval_sum_keys.bin"),
            "--eval-mult-keys",
            str(encrypted_dir / "eval_mult_keys.bin"),
            "--manifest",
            str(encrypted_dir / "aggregate_manifest.csv"),
            "--input-dir",
            str(encrypted_dir / "vectors"),
            "--output-dir",
            str(server_output_dir),
            "--analysis-filter",
            analysis_name,
            "--no-percent",
        ],
        Path.cwd(),
    )
    logs.append(output)

    timings["ckks_decrypt_wall_seconds"], output = run_command(
        [
            str(build_dir / "decrypt_ckks_results"),
            "--context",
            str(encrypted_dir / "crypto_context.bin"),
            "--secret-key",
            str(key_dir / "secret_key.bin"),
            "--manifest",
            str(server_output_dir / "aggregate_summary_manifest.csv"),
            "--input-dir",
            str(server_output_dir),
            "--output-csv",
            str(decrypted_csv),
            "--manifest-type",
            "aggregate",
        ],
        Path.cwd(),
    )
    logs.append(output)

    result = {
        "backend": "heir_ckks_openfhe_executor",
        "scheme": "CKKS",
        "slots": slots,
        "codegen": "handwritten_openfhe_executor_for_heir_tensor_contract",
        "results": parse_decrypted_aggregate(decrypted_csv),
        "prepared_dir": str(prepared_dir),
        "encrypted_dir": str(encrypted_dir),
        "server_output_dir": str(server_output_dir),
        "decrypted_csv": str(decrypted_csv),
    }
    (run_dir / "heir_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return timings, result, "\n".join(logs)
