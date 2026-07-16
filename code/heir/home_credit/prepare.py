"""Prepare notebook-aligned numeric tensors for HEIR Home Credit experiments."""

from __future__ import annotations

import csv
import hashlib
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


def validate_tensor_artifacts(output_dir: Path, tensor_rows: list[dict[str, Any]]) -> int:
    """Fail preparation early when a manifest entry has no materialized vector."""
    missing = []
    for row in tensor_rows:
        relative_path = Path(str(row["file"]))
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(f"unsafe tensor path in manifest: {relative_path}")
        path = output_dir / relative_path
        if not path.is_file() or path.stat().st_size == 0:
            missing.append(str(relative_path))
    if missing:
        raise FileNotFoundError(f"prepared tensor artifacts missing: {', '.join(missing)}")
    return len(tensor_rows)


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
        label_token = tensor_label_token(label)
        mask = [float(value == label) for value in frame[column].tolist()]
        file_name = f"tensors/group_{label_token}.csv"
        write_vector(output_dir / file_name, mask)
        tensor_rows.append(
            {
                "name": f"group_mask.{label_token}",
                "kind": "group_mask",
                "label": label,
                "file": file_name,
                "rows": len(mask),
            }
        )

    manifest_path = output_dir / "tensor_manifest.csv"
    prepared_tensor_count = validate_tensor_artifacts(output_dir, tensor_rows)
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
        "prepared_tensor_count": prepared_tensor_count,
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


def tensor_label_token(label: str) -> str:
    """Create a readable filename token without conflating distinct labels."""
    digest = hashlib.sha256(label.encode("utf-8")).hexdigest()[:10]
    return f"{safe_label(label)}_{digest}"


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
    count_weight_path = tensor_dir / "count_weights.csv"
    percent_weight_path = tensor_dir / "percent_weights.csv"
    write_vector(count_weight_path, count_weights)
    write_vector(percent_weight_path, percent_weights)
    tensor_rows = [
        {
            "name": "count_weights",
            "kind": "count_weight",
            "label": "1",
            "file": count_weight_path.relative_to(output_dir).as_posix(),
            "rows": len(frame),
        },
        {
            "name": "percent_weights",
            "kind": "percent_weight",
            "label": "100/N",
            "file": percent_weight_path.relative_to(output_dir).as_posix(),
            "rows": len(frame),
        },
    ]
    for item in reference:
        label = str(item["label"])
        mask = [float(value == label) for value in grouped.tolist()]
        label_token = tensor_label_token(label)
        vector_path = tensor_dir / f"group_{label_token}.csv"
        write_vector(vector_path, mask)
        tensor_rows.append(
            {
                "name": f"group_mask.{label_token}",
                "kind": "group_mask",
                "label": label,
                "file": vector_path.relative_to(output_dir).as_posix(),
                "rows": len(mask),
            }
        )

    manifest_path = output_dir / "tensor_manifest.csv"
    reference_path = output_dir / "pandas_reference.csv"
    prepared_tensor_count = validate_tensor_artifacts(output_dir, tensor_rows)
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
        "prepared_tensor_count": prepared_tensor_count,
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


def previous_loan_count_reference_code() -> str:
    """Return the exact normal-dataflow baseline used by the history benchmark."""
    return "\n".join(
        [
            'previous_counts = previous_application.groupby("SK_ID_CURR").size().rename("previous_loan_count")',
            'joined = application_train[["SK_ID_CURR", "TARGET"]].merge(',
            '    previous_counts, on="SK_ID_CURR", how="left"',
            ').fillna({"previous_loan_count": 0})',
        ]
    )


def prepare_previous_loan_count_tensors(
    application_path: Path,
    previous_application_path: Path,
    application_row_limit: int,
    previous_row_limit: int,
    output_dir: Path,
) -> dict[str, Any]:
    """Create an anonymous padded history matrix without exporting applicant IDs.

    The row-to-ID mapping and TARGET stay in ``client_private``. The HE input is
    only an ``application_count x slots_per_application`` matrix of 0/1 history
    indicators plus a vector of ones. This intentionally separates record
    alignment from the encrypted per-applicant summation.
    """
    started = time.perf_counter()
    load_started = time.perf_counter()
    application = read_application(application_path, application_row_limit)
    application_load_seconds = time.perf_counter() - load_started
    previous_load_started = time.perf_counter()
    previous = read_previous_application(previous_application_path, previous_row_limit)
    previous_load_seconds = time.perf_counter() - previous_load_started

    required_application = {"SK_ID_CURR", "TARGET"}
    required_previous = {"SK_ID_CURR"}
    missing_application = sorted(required_application.difference(application.columns))
    missing_previous = sorted(required_previous.difference(previous.columns))
    if missing_application:
        raise ValueError(f"application_train missing required columns: {', '.join(missing_application)}")
    if missing_previous:
        raise ValueError(f"previous_application missing required columns: {', '.join(missing_previous)}")
    if application["SK_ID_CURR"].duplicated().any():
        raise ValueError("application_train SK_ID_CURR must be unique for the history-count benchmark")

    reference_started = time.perf_counter()
    previous_counts = previous.groupby("SK_ID_CURR").size().rename("previous_loan_count")
    joined = application[["SK_ID_CURR", "TARGET"]].merge(
        previous_counts, on="SK_ID_CURR", how="left"
    ).fillna({"previous_loan_count": 0})
    joined["previous_loan_count"] = joined["previous_loan_count"].astype(int)
    pandas_reference_seconds = time.perf_counter() - reference_started

    tensor_started = time.perf_counter()
    application_ids = application["SK_ID_CURR"].tolist()
    index_by_id = {int(value): index for index, value in enumerate(application_ids)}
    matched_previous = previous[previous["SK_ID_CURR"].isin(index_by_id)].copy()
    matched_previous["app_index"] = matched_previous["SK_ID_CURR"].map(index_by_id).astype(int)
    history_lengths = matched_previous.groupby("app_index").size()
    slots_per_application = int(history_lengths.max()) if not history_lengths.empty else 1
    application_count = int(len(application))
    history_mask = [0.0] * (application_count * slots_per_application)
    next_slot = [0] * application_count
    for app_index in matched_previous["app_index"].tolist():
        slot = next_slot[app_index]
        if slot >= slots_per_application:
            raise RuntimeError("history slot allocation exceeded its fixed tensor shape")
        history_mask[app_index * slots_per_application + slot] = 1.0
        next_slot[app_index] += 1

    tensor_dir = output_dir / "tensors"
    history_path = tensor_dir / "history_mask_matrix.csv"
    unit_weights_path = tensor_dir / "unit_weights.csv"
    write_vector(history_path, history_mask)
    write_vector(unit_weights_path, [1.0] * slots_per_application)

    client_private_dir = output_dir / "client_private"
    reference_rows = [
        {
            "app_index": index,
            "previous_loan_count": int(value),
        }
        for index, value in enumerate(joined["previous_loan_count"].tolist())
    ]
    mapping_rows = [
        {
            "app_index": index,
            "SK_ID_CURR": int(row.SK_ID_CURR),
            "TARGET": int(row.TARGET) if pd.notna(row.TARGET) else "",
        }
        for index, row in enumerate(application[["SK_ID_CURR", "TARGET"]].itertuples(index=False))
    ]
    write_csv(output_dir / "pandas_reference.csv", ["app_index", "previous_loan_count"], reference_rows)
    write_csv(client_private_dir / "applicant_mapping.csv", ["app_index", "SK_ID_CURR", "TARGET"], mapping_rows)

    tensor_rows = [
        {
            "name": "history_mask_matrix",
            "kind": "history_mask_matrix",
            "label": "1=one previous_application row in this anonymous applicant slot",
            "file": history_path.relative_to(output_dir).as_posix(),
            "rows": len(history_mask),
        },
        {
            "name": "unit_weights",
            "kind": "unit_weight",
            "label": "1",
            "file": unit_weights_path.relative_to(output_dir).as_posix(),
            "rows": slots_per_application,
        },
    ]
    prepared_tensor_count = validate_tensor_artifacts(output_dir, tensor_rows)
    manifest_path = output_dir / "tensor_manifest.csv"
    write_csv(manifest_path, ["name", "kind", "label", "file", "rows"], tensor_rows)
    tensor_materialization_seconds = time.perf_counter() - tensor_started
    prepare_wall_seconds = time.perf_counter() - started

    spec = {
        "workload": "previous_loan_count_by_applicant",
        "notebook_section": "derived applicant-history feature",
        "title": "Previous Loan Count per Applicant",
        "application_input": str(application_path),
        "previous_application_input": str(previous_application_path),
        "requested_application_row_limit": application_row_limit,
        "requested_previous_row_limit": previous_row_limit,
        "application_rows": application_count,
        "previous_application_rows": int(len(previous)),
        "matched_previous_rows": int(len(matched_previous)),
        "slots_per_application": slots_per_application,
        "padding_slots": application_count * slots_per_application - int(len(matched_previous)),
        "prepared_tensor_count": prepared_tensor_count,
        "kernel": "per_applicant_history_count",
        "pandas_reference_code": previous_loan_count_reference_code(),
        "tensor_manifest": str(manifest_path),
        "pandas_reference": str(output_dir / "pandas_reference.csv"),
        "client_private_mapping": str(client_private_dir / "applicant_mapping.csv"),
        "timings_seconds": {
            "pandas_application_load_seconds": application_load_seconds,
            "pandas_previous_application_load_seconds": previous_load_seconds,
            "pandas_reference_seconds": pandas_reference_seconds,
            "normal_python_baseline_seconds": (
                application_load_seconds + previous_load_seconds + pandas_reference_seconds
            ),
            "tensor_materialization_seconds": tensor_materialization_seconds,
            "prepare_wall_seconds": prepare_wall_seconds,
        },
    }
    (output_dir / "heir_workload_spec.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    return spec


def prepare_single_missing_count_tensors(
    input_path: Path, column: str, row_limit: int, output_dir: Path
) -> dict[str, Any]:
    """Prepare one encrypted 0/1 missing-value mask for a demonstration count."""
    started = time.perf_counter()
    load_started = time.perf_counter()
    frame = read_application(input_path, row_limit)
    pandas_load_seconds = time.perf_counter() - load_started
    if column not in frame:
        raise ValueError(f"application_train has no column {column}")

    reference_started = time.perf_counter()
    missing_count = int(frame[column].isnull().sum())
    row_count = int(len(frame))
    pandas_reference_seconds = time.perf_counter() - reference_started
    if row_count == 0:
        raise ValueError("single missing-count benchmark requires at least one application row")

    tensor_started = time.perf_counter()
    tensor_dir = output_dir / "tensors"
    missing_mask_path = tensor_dir / "missing_mask.csv"
    unit_weights_path = tensor_dir / "unit_weights.csv"
    missing_mask = [float(value) for value in frame[column].isnull().tolist()]
    write_vector(missing_mask_path, missing_mask)
    write_vector(unit_weights_path, [1.0] * row_count)
    tensor_rows = [
        {
            "name": "missing_mask",
            "kind": "missing_mask",
            "label": f"{column}.isnull()",
            "file": missing_mask_path.relative_to(output_dir).as_posix(),
            "rows": row_count,
        },
        {
            "name": "unit_weights",
            "kind": "unit_weight",
            "label": "1",
            "file": unit_weights_path.relative_to(output_dir).as_posix(),
            "rows": row_count,
        },
    ]
    prepared_tensor_count = validate_tensor_artifacts(output_dir, tensor_rows)
    manifest_path = output_dir / "tensor_manifest.csv"
    write_csv(manifest_path, ["name", "kind", "label", "file", "rows"], tensor_rows)
    reference_path = output_dir / "pandas_reference.csv"
    write_csv(
        reference_path,
        ["column", "row_count", "missing_count", "missing_percent"],
        [
            {
                "column": column,
                "row_count": row_count,
                "missing_count": missing_count,
                "missing_percent": 100.0 * missing_count / row_count if row_count else 0.0,
            }
        ],
    )
    tensor_materialization_seconds = time.perf_counter() - tensor_started
    prepare_wall_seconds = time.perf_counter() - started
    spec = {
        "workload": "single_missing_count",
        "notebook_section": "4.x missing-data check",
        "title": f"Missing Count: {column}",
        "input": str(input_path),
        "column": column,
        "requested_row_limit": row_limit,
        "actual_rows": row_count,
        "prepared_tensor_count": prepared_tensor_count,
        "kernel": "single_mask_count",
        "pandas_reference_code": f'application_train["{column}"].isnull().sum()',
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


def prepare_single_pearson_tensors(
    input_path: Path, feature_x: str, feature_y: str, row_limit: int, output_dir: Path
) -> dict[str, Any]:
    """Prepare one normalized numeric pair for an encrypted Pearson trial."""
    started = time.perf_counter()
    load_started = time.perf_counter()
    frame = read_application(input_path, row_limit)
    pandas_load_seconds = time.perf_counter() - load_started
    missing = [column for column in (feature_x, feature_y) if column not in frame]
    if missing:
        raise ValueError(f"application_train missing Pearson feature(s): {', '.join(missing)}")

    reference_started = time.perf_counter()
    pair = frame[[feature_x, feature_y]].apply(pd.to_numeric, errors="coerce").dropna()
    if len(pair) < 2:
        raise ValueError("Pearson benchmark requires at least two complete numeric rows")
    x_min, x_max = float(pair[feature_x].min()), float(pair[feature_x].max())
    y_min, y_max = float(pair[feature_y].min()), float(pair[feature_y].max())
    if x_max <= x_min or y_max <= y_min:
        raise ValueError("Pearson benchmark requires non-constant features")
    x = ((pair[feature_x] - x_min) / (x_max - x_min)).astype(float)
    y = ((pair[feature_y] - y_min) / (y_max - y_min)).astype(float)
    n = int(len(pair))
    mean_x, mean_y = float(x.mean()), float(y.mean())
    mean_xy = float((x * y).mean())
    mean_x2, mean_y2 = float((x * x).mean()), float((y * y).mean())
    covariance = mean_xy - mean_x * mean_y
    variance_x, variance_y = mean_x2 - mean_x * mean_x, mean_y2 - mean_y * mean_y
    variance_product = variance_x * variance_y
    if variance_product <= 0:
        raise ValueError("Pearson benchmark has non-positive normalized variance product")
    # Calibrate z near 1 for a small, stable inverse-square-root approximation.
    # This aggregate calibration is public benchmark metadata, not ciphertext data.
    inverse_sqrt_scale = 1.0 / variance_product
    reference_correlation = float(pair[feature_x].corr(pair[feature_y], method="pearson"))
    pandas_reference_seconds = time.perf_counter() - reference_started

    tensor_started = time.perf_counter()
    tensor_dir = output_dir / "tensors"
    x_values, y_values = x.tolist(), y.tolist()
    inverse_n = 1.0 / n
    vector_specs = {
        "x": x_values,
        "y": y_values,
        "x_times_inverse_n": [value * inverse_n for value in x_values],
        "y_times_inverse_n": [value * inverse_n for value in y_values],
        "inverse_n": [inverse_n] * n,
        "ones": [1.0] * n,
    }
    tensor_rows = []
    for name, values in vector_specs.items():
        path = tensor_dir / f"{name}.csv"
        write_vector(path, values)
        tensor_rows.append({"name": name, "kind": "pearson_vector", "label": name, "file": path.relative_to(output_dir).as_posix(), "rows": n})
    prepared_tensor_count = validate_tensor_artifacts(output_dir, tensor_rows)
    manifest_path = output_dir / "tensor_manifest.csv"
    write_csv(manifest_path, ["name", "kind", "label", "file", "rows"], tensor_rows)
    reference_path = output_dir / "pandas_reference.csv"
    reference_row = {
        "feature_x": feature_x,
        "feature_y": feature_y,
        "complete_rows": n,
        "correlation": reference_correlation,
        "normalized_mean_x": mean_x,
        "normalized_mean_y": mean_y,
        "normalized_mean_xy": mean_xy,
        "normalized_mean_x2": mean_x2,
        "normalized_mean_y2": mean_y2,
        "normalized_variance_product": variance_product,
        "inverse_sqrt_scale": inverse_sqrt_scale,
        "x_min": x_min,
        "x_max": x_max,
        "y_min": y_min,
        "y_max": y_max,
    }
    write_csv(reference_path, list(reference_row), [reference_row])
    tensor_materialization_seconds = time.perf_counter() - tensor_started
    prepare_wall_seconds = time.perf_counter() - started
    spec = {
        "workload": "single_pair_full_pearson",
        "notebook_section": "Pearson correlation selected-pair trial",
        "title": f"Full HE Pearson: {feature_x} vs {feature_y}",
        "input": str(input_path),
        "feature_x": feature_x,
        "feature_y": feature_y,
        "requested_row_limit": row_limit,
        "actual_rows": int(len(frame)),
        "complete_pair_rows": n,
        "normalization": {"x_min": x_min, "x_max": x_max, "y_min": y_min, "y_max": y_max},
        "inverse_sqrt_scale": inverse_sqrt_scale,
        "kernel": "heir_dot_moments_plus_ckks_chebyshev_inverse_sqrt",
        "pandas_reference_code": f'application_train[["{feature_x}", "{feature_y}"]].dropna().corr(method="pearson")',
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
