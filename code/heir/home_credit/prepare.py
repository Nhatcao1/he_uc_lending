"""Prepare notebook-aligned numeric tensors for HEIR Home Credit experiments."""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Any

import pandas as pd

from code.heir.home_credit.workloads import PREVIOUS_CATEGORY_WORKLOADS, TARGET_GROUP_WORKLOADS


def read_application(path: Path, row_limit: int) -> pd.DataFrame:
    return pd.read_csv(path, nrows=row_limit or None)


def read_previous_application(path: Path, row_limit: int) -> pd.DataFrame:
    return pd.read_csv(path, nrows=row_limit or None)


def pandas_reference_code(column: str) -> str:
    return "\n".join(
        [
            f'temp = application_train["{column}"].value_counts()',
            "temp_y0 = []",
            "temp_y1 = []",
            "for val in temp.index:",
            f'    temp_y1.append(np.sum(application_train["TARGET"][application_train["{column}"] == val] == 1))',
            f'    temp_y0.append(np.sum(application_train["TARGET"][application_train["{column}"] == val] == 0))',
        ]
    )


def target_group_reference(frame: pd.DataFrame, workload: str) -> list[dict[str, Any]]:
    cfg = TARGET_GROUP_WORKLOADS[workload]
    column = str(cfg["column"])
    labels = [label for label in cfg["labels"] if label in set(frame[column].value_counts().index)]  # type: ignore[index]
    rows = []
    for label in labels:
        target_for_label = frame["TARGET"][frame[column] == label]
        default_count = int((target_for_label == 1).sum())
        repaid_count = int((target_for_label == 0).sum())
        count = default_count + repaid_count
        rows.append(
            {
                "label": label,
                "count": count,
                "default_count": default_count,
                "default_rate": default_count / count if count else 0.0,
            }
        )
    return rows


def write_vector(path: Path, values: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.writer(output_file)
        writer.writerow(["value"])
        writer.writerows([[f"{value:.17g}"] for value in values])


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def prepare_target_group_tensors(input_path: Path, workload: str, row_limit: int, output_dir: Path) -> dict[str, Any]:
    started = time.perf_counter()
    cfg = TARGET_GROUP_WORKLOADS[workload]
    column = str(cfg["column"])

    load_started = time.perf_counter()
    frame = read_application(input_path, row_limit)
    pandas_load_seconds = time.perf_counter() - load_started

    reference_started = time.perf_counter()
    reference = target_group_reference(frame, workload)
    pandas_reference_seconds = time.perf_counter() - reference_started

    tensor_started = time.perf_counter()
    tensor_dir = output_dir / "tensors"
    target_mask = [float(value == 1) for value in frame["TARGET"].fillna(0).astype(int).tolist()]
    write_vector(tensor_dir / "target_mask.csv", target_mask)

    tensor_rows = [
        {
            "name": "target_mask",
            "kind": "target_mask",
            "label": "TARGET=1",
            "file": "tensors/target_mask.csv",
            "rows": len(target_mask),
        }
    ]
    for item in reference:
        label = str(item["label"])
        safe_label = "".join(char if char.isalnum() else "_" for char in label).strip("_").lower()
        mask = [float(value == label) for value in frame[column].tolist()]
        file_name = f"tensors/group_{safe_label}.csv"
        write_vector(output_dir / file_name, mask)
        tensor_rows.append(
            {
                "name": f"group_mask.{safe_label}",
                "kind": "group_mask",
                "label": label,
                "file": file_name,
                "rows": len(mask),
            }
        )

    manifest_path = output_dir / "tensor_manifest.csv"
    write_csv(manifest_path, ["name", "kind", "label", "file", "rows"], tensor_rows)
    reference_path = output_dir / "pandas_reference.csv"
    write_csv(reference_path, ["label", "count", "default_count", "default_rate"], reference)
    tensor_materialization_seconds = time.perf_counter() - tensor_started
    prepare_wall_seconds = time.perf_counter() - started

    spec = {
        "workload": workload,
        "notebook_section": cfg["section"],
        "title": cfg["title"],
        "input": str(input_path),
        "requested_row_limit": row_limit,
        "actual_rows": int(len(frame)),
        "column": column,
        "kernel": "masked_default_count",
        "pandas_reference_code": pandas_reference_code(column),
        "tensor_manifest": str(manifest_path),
        "pandas_reference": str(reference_path),
        "timings_seconds": {
            "pandas_load_seconds": pandas_load_seconds,
            "pandas_reference_seconds": pandas_reference_seconds,
            "normal_python_baseline_seconds": pandas_load_seconds + pandas_reference_seconds,
            "tensor_materialization_seconds": tensor_materialization_seconds,
            "prepare_wall_seconds": prepare_wall_seconds,
        },
    }
    (output_dir / "heir_workload_spec.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    return spec


def previous_reference_code(column: str) -> str:
    return "\n".join(
        [
            f'previous_application["{column}"].value_counts()',
            f'previous_application["{column}"].value_counts(normalize=True) * 100',
        ]
    )


def safe_label(label: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in label).strip("_").lower() or "blank"


def prepare_previous_category_tensors(input_path: Path, workload: str, row_limit: int, output_dir: Path) -> dict[str, Any]:
    """Prepare encrypted numeric masks for one notebook 5.15 value-count table."""
    started = time.perf_counter()
    cfg = PREVIOUS_CATEGORY_WORKLOADS[workload]
    column = str(cfg["column"])

    load_started = time.perf_counter()
    frame = read_previous_application(input_path, row_limit)
    pandas_load_seconds = time.perf_counter() - load_started
    if column not in frame:
        raise ValueError(f"previous_application has no column {column}")

    reference_started = time.perf_counter()
    raw_series = frame[column]
    valid_values = raw_series.notna()
    # Categorical columns are mostly strings, but NFLAG_INSURED_ON_APPROVAL is
    # numeric. Use one stable comparison representation for both cases.
    category_series = raw_series.astype(str).where(valid_values)
    value_counts = category_series.value_counts()
    top_k = int(cfg.get("top_k", 0))
    selected_labels = [str(label) for label in (value_counts.head(top_k) if top_k else value_counts).index]
    selected_set = set(selected_labels)
    if top_k:
        grouped = category_series.where(category_series.isin(selected_set), "__OTHER__").where(valid_values)
        labels = selected_labels + (["__OTHER__"] if bool((valid_values & ~category_series.isin(selected_set)).any()) else [])
    else:
        grouped = category_series
        labels = selected_labels
    total_rows = int(grouped.notna().sum())
    reference = []
    for label in labels:
        count = int((grouped == label).sum())
        reference.append({"label": label, "count": count, "percent": (100.0 * count / total_rows) if total_rows else 0.0})
    pandas_reference_seconds = time.perf_counter() - reference_started

    tensor_started = time.perf_counter()
    tensor_dir = output_dir / "tensors"
    count_weights = [1.0] * len(frame)
    percent_weights = [100.0 / total_rows if total_rows else 0.0] * len(frame)
    write_vector(tensor_dir / "count_weights.csv", count_weights)
    write_vector(tensor_dir / "percent_weights.csv", percent_weights)
    tensor_rows = [
        {"name": "count_weights", "kind": "count_weight", "label": "1", "file": "tensors/count_weights.csv", "rows": len(frame)},
        {
            "name": "percent_weights",
            "kind": "percent_weight",
            "label": "100/N",
            "file": "tensors/percent_weights.csv",
            "rows": len(frame),
        },
    ]
    for item in reference:
        label = str(item["label"])
        mask = [float(value == label) for value in grouped.tolist()]
        file_name = f"tensors/group_{safe_label(label)}.csv"
        write_vector(output_dir / file_name, mask)
        tensor_rows.append(
            {
                "name": f"group_mask.{safe_label(label)}",
                "kind": "group_mask",
                "label": label,
                "file": file_name,
                "rows": len(mask),
            }
        )

    manifest_path = output_dir / "tensor_manifest.csv"
    reference_path = output_dir / "pandas_reference.csv"
    write_csv(manifest_path, ["name", "kind", "label", "file", "rows"], tensor_rows)
    write_csv(reference_path, ["label", "count", "percent"], reference)
    tensor_materialization_seconds = time.perf_counter() - tensor_started
    prepare_wall_seconds = time.perf_counter() - started
    spec = {
        "workload": workload,
        "notebook_section": cfg["section"],
        "title": cfg["title"],
        "input": str(input_path),
        "requested_row_limit": row_limit,
        "actual_rows": int(len(frame)),
        "valid_category_rows": total_rows,
        "column": column,
        "kernel": "category_count_and_percent",
        "pandas_reference_code": previous_reference_code(column),
        "tensor_manifest": str(manifest_path),
        "pandas_reference": str(reference_path),
        "timings_seconds": {
            "pandas_load_seconds": pandas_load_seconds,
            "pandas_reference_seconds": pandas_reference_seconds,
            "normal_python_baseline_seconds": pandas_load_seconds + pandas_reference_seconds,
            "tensor_materialization_seconds": tensor_materialization_seconds,
            "prepare_wall_seconds": prepare_wall_seconds,
        },
    }
    (output_dir / "heir_workload_spec.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    return spec
