#!/usr/bin/env python3
"""Prepare LendingClub data for later HE encryption.

This client-side script reads the raw CSV, normalizes missing tokens, maps small
categorical fields, drops rows that are not encryption-ready, creates optional
policy masks, normalizes numeric values, and writes local prep reports.

It does not perform HE encryption.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


NUMERIC_COLUMNS = [
    "loan_amnt",
    "annual_inc",
    "dti",
    "open_acc",
    "total_acc",
    "revol_util",
    "revol_bal",
    "pub_rec",
    "mort_acc",
    "pub_rec_bankruptcies",
]

OUTPUT_COLUMNS = [
    "row_id",
    *NUMERIC_COLUMNS,
    "term_60_month",
    "loan_status",
]

RAW_OUTPUT_COLUMNS = [
    "row_id",
    *NUMERIC_COLUMNS,
    "term_60_month",
    "loan_status",
]

POLICY_RULES = {
    "annual_inc_gt_250000": ("annual_inc", "gt", 250000.0),
    "dti_gt_50": ("dti", "gt", 50.0),
    "open_acc_gt_40": ("open_acc", "gt", 40.0),
    "total_acc_gt_80": ("total_acc", "gt", 80.0),
    "revol_util_gt_120": ("revol_util", "gt", 120.0),
    "revol_bal_gt_250000": ("revol_bal", "gt", 250000.0),
}

POLICY_MASK_COLUMNS = ["row_id", *POLICY_RULES.keys()]

MISSING_TOKENS = {"", "na", "nan", "null", "none", "n/a"}
REQUIRED_INPUT_COLUMNS = [*NUMERIC_COLUMNS, "term", "loan_status"]


def is_missing(value: str | None) -> bool:
    if value is None:
        return True
    return value.strip().lower() in MISSING_TOKENS


def parse_float(value: str | None) -> float | None:
    if is_missing(value):
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def parse_term(value: str | None) -> int | None:
    if is_missing(value):
        return None
    text = str(value).strip().lower()
    if text.startswith("36"):
        return 0
    if text.startswith("60"):
        return 1
    return None


def parse_loan_status(value: str | None) -> int | None:
    if is_missing(value):
        return None
    text = str(value).strip().lower()
    if text == "fully paid":
        return 1
    if text == "charged off":
        return 0
    return None


def empty_column_stats() -> dict[str, dict[str, int]]:
    return {
        col: {
            "missing": 0,
            "invalid": 0,
            "dropped": 0,
        }
        for col in REQUIRED_INPUT_COLUMNS
    }


def empty_numeric_summary() -> dict[str, dict[str, float]]:
    return {
        col: {
            "min": 0.0,
            "max": 0.0,
            "mean": 0.0,
            "sum": 0.0,
        }
        for col in [*NUMERIC_COLUMNS, "term_60_month", "loan_status"]
    }


def load_clean_rows(
    input_csv: Path,
    row_limit: int | None,
) -> tuple[list[dict[str, float]], dict[str, Any], dict[str, dict[str, int]]]:
    rows: list[dict[str, float]] = []
    stats: dict[str, Any] = {
        "raw_rows_seen": 0,
        "rows_kept": 0,
        "rows_dropped_missing_or_invalid": 0,
        "drop_reason_counts": {},
    }
    column_stats = empty_column_stats()

    with input_csv.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        missing_columns = [col for col in REQUIRED_INPUT_COLUMNS if col not in reader.fieldnames]
        if missing_columns:
            raise ValueError(f"Input CSV is missing required columns: {missing_columns}")

        for raw in reader:
            if row_limit is not None and stats["raw_rows_seen"] >= row_limit:
                break
            stats["raw_rows_seen"] += 1

            parsed: dict[str, float] = {"row_id": float(len(rows))}
            drop_reasons: list[str] = []

            for col in NUMERIC_COLUMNS:
                raw_value = raw.get(col)
                if is_missing(raw_value):
                    column_stats[col]["missing"] += 1
                    column_stats[col]["dropped"] += 1
                    drop_reasons.append(f"{col}:missing")
                    continue

                value = parse_float(raw_value)
                if value is None:
                    column_stats[col]["invalid"] += 1
                    column_stats[col]["dropped"] += 1
                    drop_reasons.append(f"{col}:invalid")
                    continue

                parsed[col] = value

            if is_missing(raw.get("term")):
                column_stats["term"]["missing"] += 1
                column_stats["term"]["dropped"] += 1
                drop_reasons.append("term:missing")
            else:
                term = parse_term(raw.get("term"))
                if term is None:
                    column_stats["term"]["invalid"] += 1
                    column_stats["term"]["dropped"] += 1
                    drop_reasons.append("term:invalid")
                else:
                    parsed["term_60_month"] = float(term)

            if is_missing(raw.get("loan_status")):
                column_stats["loan_status"]["missing"] += 1
                column_stats["loan_status"]["dropped"] += 1
                drop_reasons.append("loan_status:missing")
            else:
                status = parse_loan_status(raw.get("loan_status"))
                if status is None:
                    column_stats["loan_status"]["invalid"] += 1
                    column_stats["loan_status"]["dropped"] += 1
                    drop_reasons.append("loan_status:invalid")
                else:
                    parsed["loan_status"] = float(status)

            if drop_reasons:
                stats["rows_dropped_missing_or_invalid"] += 1
                for reason in drop_reasons:
                    stats["drop_reason_counts"][reason] = stats["drop_reason_counts"].get(reason, 0) + 1
                continue

            rows.append(parsed)
            stats["rows_kept"] += 1

    return rows, stats, column_stats


def minmax_params(rows: list[dict[str, float]]) -> dict[str, dict[str, float]]:
    params: dict[str, dict[str, float]] = {}
    for col in NUMERIC_COLUMNS:
        values = [row[col] for row in rows]
        params[col] = {"min": min(values), "max": max(values)}
    return params


def summarize_columns(rows: list[dict[str, float]], columns: list[str]) -> dict[str, dict[str, float]]:
    if not rows:
        return empty_numeric_summary()

    summary: dict[str, dict[str, float]] = {}
    for col in columns:
        values = [row[col] for row in rows]
        total = sum(values)
        summary[col] = {
            "min": min(values),
            "max": max(values),
            "mean": total / len(values),
            "sum": total,
        }
    return summary


def normalize_rows(rows: list[dict[str, float]], params: dict[str, dict[str, float]]) -> list[dict[str, float]]:
    normalized: list[dict[str, float]] = []
    for row in rows:
        out: dict[str, float] = {"row_id": row["row_id"]}
        for col in NUMERIC_COLUMNS:
            lo = params[col]["min"]
            hi = params[col]["max"]
            out[col] = 0.0 if hi == lo else (row[col] - lo) / (hi - lo)
        out["term_60_month"] = row["term_60_month"]
        out["loan_status"] = row["loan_status"]
        normalized.append(out)
    return normalized


def build_policy_masks(rows: list[dict[str, float]]) -> list[dict[str, float]]:
    masks: list[dict[str, float]] = []
    for row in rows:
        out: dict[str, float] = {"row_id": row["row_id"]}
        for mask_name, (col, op, threshold) in POLICY_RULES.items():
            value = row[col]
            if op == "gt":
                out[mask_name] = 1.0 if value > threshold else 0.0
            else:
                raise ValueError(f"Unsupported policy op: {op}")
        masks.append(out)
    return masks


def write_payload(rows: list[dict[str, float]], output_csv: Path) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row[col] for col in OUTPUT_COLUMNS})


def write_rows(rows: list[dict[str, float]], output_csv: Path, columns: list[str]) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row[col] for col in columns})


def write_manifest(
    manifest_path: Path,
    input_csv: Path,
    output_csv: Path,
    clean_output_csv: Path,
    policy_mask_output_csv: Path,
    report_path: Path,
    stats: dict[str, Any],
    params: dict[str, dict[str, float]],
) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "purpose": "client-side preparation before HE encryption",
        "input_csv": str(input_csv),
        "prepared_normalized_csv": str(output_csv),
        "prepared_clean_csv": str(clean_output_csv),
        "prepared_policy_masks_csv": str(policy_mask_output_csv),
        "prep_report_json": str(report_path),
        "missing_value_policy": "drop rows missing required fields or containing invalid numeric/category values",
        "normalization": "minmax fitted on kept rows",
        "stats": stats,
        "columns": OUTPUT_COLUMNS,
        "raw_output_columns": RAW_OUTPUT_COLUMNS,
        "numeric_columns": NUMERIC_COLUMNS,
        "policy_mask_columns": POLICY_MASK_COLUMNS,
        "policy_rules": POLICY_RULES,
        "normalization_params": params,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def write_report(
    report_path: Path,
    stats: dict[str, Any],
    column_quality: dict[str, dict[str, int]],
    clean_summary: dict[str, dict[str, float]],
    normalized_summary: dict[str, dict[str, float]],
    policy_masks: list[dict[str, float]],
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    policy_counts = {
        mask_name: int(sum(row[mask_name] for row in policy_masks))
        for mask_name in POLICY_RULES.keys()
    }
    report = {
        "purpose": "client-side data preparation report before HE encryption",
        "stats": stats,
        "column_quality": column_quality,
        "clean_value_summary": clean_summary,
        "normalized_value_summary": normalized_summary,
        "policy_mask_counts": policy_counts,
        "note": (
            "These reports are generated before encryption and should remain local. "
            "Server-side HE EDA should receive encrypted prepared values or encrypted masks only."
        ),
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare LendingClub CSV for HE encryption.")
    parser.add_argument("--input", default="data/lending_club_loan_two.csv", help="Raw LendingClub CSV path.")
    parser.add_argument(
        "--output",
        default="encrypted_payloads/prepared_lending_values.csv",
        help="Prepared normalized numeric CSV path for later CKKS encryption.",
    )
    parser.add_argument(
        "--clean-output",
        default="encrypted_payloads/prepared_lending_clean_values.csv",
        help="Cleaned but unnormalized local baseline CSV path.",
    )
    parser.add_argument(
        "--policy-mask-output",
        default="encrypted_payloads/prepared_lending_policy_masks.csv",
        help="Prepared local policy-mask CSV path for future encrypted count EDA.",
    )
    parser.add_argument(
        "--manifest",
        default="encrypted_payloads/prepared_lending_manifest.json",
        help="Preparation manifest path.",
    )
    parser.add_argument(
        "--report",
        default="encrypted_payloads/prepared_lending_report.json",
        help="Client-side preparation report path.",
    )
    parser.add_argument("--row-limit", type=int, default=None, help="Optional max raw rows to scan.")
    args = parser.parse_args()

    input_csv = Path(args.input)
    output_csv = Path(args.output)
    clean_output_csv = Path(args.clean_output)
    policy_mask_output_csv = Path(args.policy_mask_output)
    manifest_path = Path(args.manifest)
    report_path = Path(args.report)

    rows, stats, column_quality = load_clean_rows(input_csv, args.row_limit)
    if not rows:
        raise SystemExit("No valid rows after preparation.")

    params = minmax_params(rows)
    prepared = normalize_rows(rows, params)
    policy_masks = build_policy_masks(rows)
    clean_summary = summarize_columns(rows, [*NUMERIC_COLUMNS, "term_60_month", "loan_status"])
    normalized_summary = summarize_columns(prepared, [*NUMERIC_COLUMNS, "term_60_month", "loan_status"])

    write_payload(prepared, output_csv)
    write_rows(rows, clean_output_csv, RAW_OUTPUT_COLUMNS)
    write_rows(policy_masks, policy_mask_output_csv, POLICY_MASK_COLUMNS)
    write_manifest(
        manifest_path,
        input_csv,
        output_csv,
        clean_output_csv,
        policy_mask_output_csv,
        report_path,
        stats,
        params,
    )
    write_report(report_path, stats, column_quality, clean_summary, normalized_summary, policy_masks)

    print(
        json.dumps(
            {
                "prepared_normalized_csv": str(output_csv),
                "prepared_clean_csv": str(clean_output_csv),
                "prepared_policy_masks_csv": str(policy_mask_output_csv),
                "manifest": str(manifest_path),
                "report": str(report_path),
                **stats,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
