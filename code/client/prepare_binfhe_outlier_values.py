#!/usr/bin/env python3
"""Prepare bounded integer LendingClub values for BinFHE outlier checks.

This script does not create masks. It creates integer values that the server can
compare homomorphically with BinFHE/FHEW threshold LUTs.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any


PLAINTEXT_MODULUS = 512
PACK_BITS_PER_FEATURE = 5
PACK_LEVELS = 1 << PACK_BITS_PER_FEATURE
PACK_GROUP_SIZE = 2
PACKED_PLAINTEXT_MODULUS = 1 << (PACK_BITS_PER_FEATURE * PACK_GROUP_SIZE)
MISSING_TOKENS = {"", "na", "nan", "null", "none", "n/a"}

RULES: list[dict[str, Any]] = [
    {
        "column": "annual_inc_k",
        "source": "annual_inc",
        "scale_divisor": 1000.0,
        "cap": 511,
        "threshold": 250,
        "comparison": "gt",
        "meaning": "annual_inc > 250000",
    },
    {
        "column": "dti",
        "source": "dti",
        "scale_divisor": 1.0,
        "cap": 511,
        "threshold": 50,
        "comparison": "gt",
        "meaning": "dti > 50",
    },
    {
        "column": "open_acc",
        "source": "open_acc",
        "scale_divisor": 1.0,
        "cap": 511,
        "threshold": 40,
        "comparison": "gt",
        "meaning": "open_acc > 40",
    },
    {
        "column": "total_acc",
        "source": "total_acc",
        "scale_divisor": 1.0,
        "cap": 511,
        "threshold": 80,
        "comparison": "gt",
        "meaning": "total_acc > 80",
    },
    {
        "column": "revol_util",
        "source": "revol_util",
        "scale_divisor": 1.0,
        "cap": 511,
        "threshold": 120,
        "comparison": "gt",
        "meaning": "revol_util > 120",
    },
    {
        "column": "revol_bal_k",
        "source": "revol_bal",
        "scale_divisor": 1000.0,
        "cap": 511,
        "threshold": 250,
        "comparison": "gt",
        "meaning": "revol_bal > 250000",
    },
]

OUTPUT_COLUMNS = ["row_id", *[rule["column"] for rule in RULES]]
RULE_COLUMNS = ["column", "plaintext_modulus", "threshold", "comparison", "source", "scale_divisor", "cap", "meaning"]
PACKED_VALUE_COLUMNS = ["row_id", "pack_id", "packed_value"]
PACKED_RULE_COLUMNS = [
    "pack_id",
    "plaintext_modulus",
    "bits_per_feature",
    "columns",
    "threshold_buckets",
    "comparison",
    "meanings",
]


def is_missing(value: str | None) -> bool:
    if value is None:
        return True
    return value.strip().lower() in MISSING_TOKENS


def parse_float(value: str | None) -> float | None:
    if is_missing(value):
        return None
    try:
        parsed = float(str(value).strip())
    except ValueError:
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def encode_value(value: float, scale_divisor: float, cap: int) -> int:
    encoded = int(math.floor(value / scale_divisor))
    if encoded < 0:
        return 0
    if encoded > cap:
        return cap
    return encoded


def bucket_value(encoded: int, cap: int) -> int:
    bucket = int(math.floor((encoded * PACK_LEVELS) / (cap + 1)))
    if bucket < 0:
        return 0
    if bucket >= PACK_LEVELS:
        return PACK_LEVELS - 1
    return bucket


def packed_rule_groups() -> list[list[dict[str, Any]]]:
    return [RULES[i : i + PACK_GROUP_SIZE] for i in range(0, len(RULES), PACK_GROUP_SIZE)]


def pack_group(row: dict[str, int], rules: list[dict[str, Any]]) -> int:
    packed = 0
    for offset, rule in enumerate(rules):
        bucket = bucket_value(row[rule["column"]], int(rule["cap"]))
        packed |= bucket << (PACK_BITS_PER_FEATURE * offset)
    return packed


def prepare_rows(input_csv: Path, row_limit: int | None) -> tuple[list[dict[str, int]], dict[str, Any]]:
    rows: list[dict[str, int]] = []
    stats: dict[str, Any] = {
        "raw_rows_seen": 0,
        "rows_kept": 0,
        "rows_dropped_missing_or_invalid": 0,
        "drop_reason_counts": {},
    }

    required = sorted({rule["source"] for rule in RULES})
    with input_csv.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames or []
        missing_columns = [col for col in required if col not in fieldnames]
        if missing_columns:
            raise ValueError(f"Input CSV is missing required columns: {missing_columns}")

        for raw in reader:
            if row_limit is not None and stats["raw_rows_seen"] >= row_limit:
                break
            stats["raw_rows_seen"] += 1

            parsed_sources: dict[str, float] = {}
            drop_reasons: list[str] = []
            for source in required:
                value = parse_float(raw.get(source))
                if value is None:
                    drop_reasons.append(f"{source}:missing_or_invalid")
                else:
                    parsed_sources[source] = value

            if drop_reasons:
                stats["rows_dropped_missing_or_invalid"] += 1
                for reason in drop_reasons:
                    stats["drop_reason_counts"][reason] = stats["drop_reason_counts"].get(reason, 0) + 1
                continue

            out = {"row_id": len(rows)}
            for rule in RULES:
                out[rule["column"]] = encode_value(
                    parsed_sources[rule["source"]],
                    float(rule["scale_divisor"]),
                    int(rule["cap"]),
                )
            rows.append(out)
            stats["rows_kept"] += 1

    return rows, stats


def write_values(path: Path, rows: list[dict[str, int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row[col] for col in OUTPUT_COLUMNS})


def write_rules(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=RULE_COLUMNS)
        writer.writeheader()
        for rule in RULES:
            writer.writerow(
                {
                    "column": rule["column"],
                    "plaintext_modulus": PLAINTEXT_MODULUS,
                    "threshold": rule["threshold"],
                    "comparison": rule["comparison"],
                    "source": rule["source"],
                    "scale_divisor": rule["scale_divisor"],
                    "cap": rule["cap"],
                    "meaning": rule["meaning"],
                }
            )


def write_packed_values(path: Path, rows: list[dict[str, int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    groups = packed_rule_groups()
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=PACKED_VALUE_COLUMNS)
        writer.writeheader()
        for row in rows:
            for idx, group in enumerate(groups):
                writer.writerow(
                    {
                        "row_id": row["row_id"],
                        "pack_id": f"pack_{idx}",
                        "packed_value": pack_group(row, group),
                    }
                )


def write_packed_rules(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=PACKED_RULE_COLUMNS)
        writer.writeheader()
        for idx, group in enumerate(packed_rule_groups()):
            writer.writerow(
                {
                    "pack_id": f"pack_{idx}",
                    "plaintext_modulus": PACKED_PLAINTEXT_MODULUS,
                    "bits_per_feature": PACK_BITS_PER_FEATURE,
                    "columns": ";".join(rule["column"] for rule in group),
                    "threshold_buckets": ";".join(
                        str(bucket_value(int(rule["threshold"]), int(rule["cap"]))) for rule in group
                    ),
                    "comparison": "any_gt_bucket",
                    "meanings": ";".join(rule["meaning"] for rule in group),
                }
            )


def write_manifest(
    path: Path,
    input_csv: Path,
    values_csv: Path,
    rules_csv: Path,
    packed_values_csv: Path,
    packed_rules_csv: Path,
    stats: dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "purpose": "bounded integer values for BinFHE/FHEW server-side outlier threshold checks",
        "input_csv": str(input_csv),
        "values_csv": str(values_csv),
        "rules_csv": str(rules_csv),
        "packed_values_csv": str(packed_values_csv),
        "packed_rules_csv": str(packed_rules_csv),
        "plaintext_modulus": PLAINTEXT_MODULUS,
        "packed_plaintext_modulus": PACKED_PLAINTEXT_MODULUS,
        "pack_bits_per_feature": PACK_BITS_PER_FEATURE,
        "pack_group_size": PACK_GROUP_SIZE,
        "stats": stats,
        "columns": OUTPUT_COLUMNS,
        "rules": RULES,
        "note": (
            "Client encodes bounded integers only. Scalar values are exact within the configured scale. "
            "Packed values bucket each feature and let the server compute encrypted any_outlier flags."
        ),
    }
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare bounded integer values for BinFHE outlier checks.")
    parser.add_argument("--input", default="data/lending_club_loan_two.csv", help="Raw LendingClub CSV path.")
    parser.add_argument(
        "--output",
        default="encrypted_payloads/binfhe_outliers/outlier_values.csv",
        help="Bounded integer values CSV path.",
    )
    parser.add_argument(
        "--rules",
        default="encrypted_payloads/binfhe_outliers/outlier_rules.csv",
        help="Outlier threshold rules CSV path.",
    )
    parser.add_argument(
        "--manifest",
        default="encrypted_payloads/binfhe_outliers/outlier_prep_manifest.json",
        help="Outlier prep manifest JSON path.",
    )
    parser.add_argument(
        "--packed-output",
        default="encrypted_payloads/binfhe_outliers/outlier_packed_values.csv",
        help="Packed bucketed values CSV path.",
    )
    parser.add_argument(
        "--packed-rules",
        default="encrypted_payloads/binfhe_outliers/outlier_packed_rules.csv",
        help="Packed outlier rule schema CSV path.",
    )
    parser.add_argument("--row-limit", type=int, default=None, help="Optional max raw rows to scan.")
    args = parser.parse_args()

    input_csv = Path(args.input)
    output_csv = Path(args.output)
    rules_csv = Path(args.rules)
    manifest_json = Path(args.manifest)
    packed_output_csv = Path(args.packed_output)
    packed_rules_csv = Path(args.packed_rules)

    rows, stats = prepare_rows(input_csv, args.row_limit)
    if not rows:
        raise SystemExit("No valid rows after BinFHE outlier preparation.")

    write_values(output_csv, rows)
    write_rules(rules_csv)
    write_packed_values(packed_output_csv, rows)
    write_packed_rules(packed_rules_csv)
    write_manifest(manifest_json, input_csv, output_csv, rules_csv, packed_output_csv, packed_rules_csv, stats)

    print(
        json.dumps(
            {
                "outlier_values_csv": str(output_csv),
                "outlier_rules_csv": str(rules_csv),
                "outlier_packed_values_csv": str(packed_output_csv),
                "outlier_packed_rules_csv": str(packed_rules_csv),
                "manifest": str(manifest_json),
                **stats,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
