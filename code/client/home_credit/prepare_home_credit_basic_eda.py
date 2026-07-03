#!/usr/bin/env python3
"""Prepare Home Credit vectors for encrypted EDA and linear scoring.

This script runs on the client, next to the raw Home Credit CSV. It does not
encrypt. It creates local prepared vector CSVs and manifests that the OpenFHE
client encryption tool can turn into server-uploadable ciphertext bundles.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


MISSING_BUCKET = "__MISSING__"
OTHER_BUCKET = "__OTHER__"

DEFAULT_CATEGORY_CONFIG: dict[str, dict[str, object]] = {
    "NAME_INCOME_TYPE": {"mode": "all"},
    "NAME_EDUCATION_TYPE": {"mode": "all"},
    "OCCUPATION_TYPE": {"mode": "top_k", "k": 20, "other_bucket": True},
    "ORGANIZATION_TYPE": {"mode": "top_k", "k": 30, "other_bucket": True},
}

DEFAULT_AMOUNT_COLUMNS = ["AMT_CREDIT", "AMT_INCOME_TOTAL", "AMT_ANNUITY"]

DEFAULT_MODEL_FEATURES = [
    {"name": "AMT_CREDIT_scaled", "source": "AMT_CREDIT", "weight": 0.15},
    {"name": "AMT_INCOME_TOTAL_scaled", "source": "AMT_INCOME_TOTAL", "weight": -0.20},
    {"name": "AMT_ANNUITY_scaled", "source": "AMT_ANNUITY", "weight": 0.10},
    {"name": "EXT_SOURCE_2_scaled", "source": "EXT_SOURCE_2", "weight": -0.35},
    {"name": "EXT_SOURCE_3_scaled", "source": "EXT_SOURCE_3", "weight": -0.35},
    {"name": "AGE_YEARS_scaled", "source": "AGE_YEARS", "weight": -0.05},
    {"name": "CREDIT_INCOME_PERCENT_scaled", "source": "CREDIT_INCOME_PERCENT", "weight": 0.20},
    {"name": "ANNUITY_INCOME_PERCENT_scaled", "source": "ANNUITY_INCOME_PERCENT", "weight": 0.15},
    {"name": "DAYS_EMPLOYED_PERCENT_scaled", "source": "DAYS_EMPLOYED_PERCENT", "weight": -0.05},
]


@dataclass
class RunningStats:
    count: int = 0
    mean: float = 0.0
    m2: float = 0.0

    def add(self, value: float | None) -> None:
        if value is None or not math.isfinite(value):
            return
        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        self.m2 += delta * (value - self.mean)

    @property
    def std(self) -> float:
        if self.count < 2:
            return 1.0
        value = math.sqrt(self.m2 / (self.count - 1))
        return value if value > 1e-12 else 1.0


@dataclass
class VectorDef:
    name: str
    kind: str
    source_column: str
    analysis: str
    group: str
    label: str
    value_fn: Callable[[dict[str, str]], float]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare Home Credit client-side EDA vectors.")
    parser.add_argument("--input", default="data/home_credit/application_train.csv")
    parser.add_argument("--output-dir", default="prepared_payloads/home_credit_basic_eda")
    parser.add_argument("--row-limit", type=int, default=0, help="Optional local test limit. 0 means all rows.")
    parser.add_argument("--category-config", help="Optional JSON category policy file.")
    parser.add_argument("--model-json", help="Optional trained/exported linear model JSON.")
    parser.add_argument(
        "--amount-columns",
        default=",".join(DEFAULT_AMOUNT_COLUMNS),
        help="Comma-separated amount columns to include in masked sums.",
    )
    return parser.parse_args()


def safe_name(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    value = value.strip("._")
    return value or "value"


def read_category_config(path: str | None) -> dict[str, dict[str, object]]:
    if not path:
        return DEFAULT_CATEGORY_CONFIG
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    columns = data.get("categorical_columns", data)
    if not isinstance(columns, dict):
        raise ValueError("category config must be a dict or contain categorical_columns")
    return {str(key): dict(value) for key, value in columns.items()}


def iter_rows(path: Path, row_limit: int) -> Iterable[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as input_file:
        reader = csv.DictReader(input_file)
        for index, row in enumerate(reader):
            if row_limit and index >= row_limit:
                break
            yield row


def normalize_category(value: str | None) -> str:
    if value is None:
        return MISSING_BUCKET
    cleaned = str(value).strip()
    if not cleaned or cleaned.lower() in {"nan", "none", "null"}:
        return MISSING_BUCKET
    return cleaned


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


def value_from_source(row: dict[str, str], source: str) -> float | None:
    if source == "AGE_YEARS":
        days_birth = parse_float(row.get("DAYS_BIRTH"))
        if days_birth is None:
            return None
        return abs(days_birth) / 365.25
    if source == "CREDIT_INCOME_PERCENT":
        credit = parse_float(row.get("AMT_CREDIT"))
        income = parse_float(row.get("AMT_INCOME_TOTAL"))
        return safe_ratio(credit, income)
    if source == "ANNUITY_INCOME_PERCENT":
        annuity = parse_float(row.get("AMT_ANNUITY"))
        income = parse_float(row.get("AMT_INCOME_TOTAL"))
        return safe_ratio(annuity, income)
    if source == "CREDIT_TERM":
        annuity = parse_float(row.get("AMT_ANNUITY"))
        credit = parse_float(row.get("AMT_CREDIT"))
        return safe_ratio(annuity, credit)
    if source == "DAYS_EMPLOYED_PERCENT":
        employed = parse_float(row.get("DAYS_EMPLOYED"))
        birth = parse_float(row.get("DAYS_BIRTH"))
        if employed == 365243:
            return None
        return safe_ratio(employed, birth)
    return parse_float(row.get(source))


def safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or abs(denominator) <= 1e-12:
        return None
    value = numerator / denominator
    return value if math.isfinite(value) else None


def bucket_age(row: dict[str, str]) -> str:
    age = value_from_source(row, "AGE_YEARS")
    if age is None:
        return MISSING_BUCKET
    if age < 25:
        return "lt_25"
    if age < 35:
        return "25_34"
    if age < 45:
        return "35_44"
    if age < 55:
        return "45_54"
    if age < 65:
        return "55_64"
    return "65_plus"


def bucket_ext_source(row: dict[str, str], column: str) -> str:
    value = parse_float(row.get(column))
    if value is None:
        return MISSING_BUCKET
    if value < 0.2:
        return "0_0.2"
    if value < 0.4:
        return "0.2_0.4"
    if value < 0.6:
        return "0.4_0.6"
    if value < 0.8:
        return "0.6_0.8"
    return "0.8_1.0"


def bucket_days_employed(row: dict[str, str]) -> str:
    value = parse_float(row.get("DAYS_EMPLOYED"))
    if value is None:
        return MISSING_BUCKET
    if int(value) == 365243:
        return "anomaly_365243"
    return "normal"


def bucket_ratio(row: dict[str, str], source: str) -> str:
    value = value_from_source(row, source)
    if value is None:
        return "invalid"
    if value < 0:
        return "negative"
    if value < 0.1:
        return "0_0.1"
    if value < 0.2:
        return "0.1_0.2"
    if value < 0.4:
        return "0.2_0.4"
    if value < 0.6:
        return "0.4_0.6"
    if value < 1.0:
        return "0.6_1.0"
    return "gte_1.0"


def collect_first_pass(
    input_path: Path,
    row_limit: int,
    category_config: dict[str, dict[str, object]],
    model_features: list[dict[str, object]],
) -> tuple[int, dict[str, Counter[str]], dict[str, RunningStats]]:
    category_counts = {column: Counter() for column in category_config}
    stats = {str(feature["source"]): RunningStats() for feature in model_features}
    rows = 0
    for row in iter_rows(input_path, row_limit):
        rows += 1
        for column, counter in category_counts.items():
            counter[normalize_category(row.get(column))] += 1
        for source, stat in stats.items():
            stat.add(value_from_source(row, source))
    return rows, category_counts, stats


def selected_categories(category_config: dict[str, dict[str, object]], counts: dict[str, Counter[str]]) -> dict[str, list[str]]:
    selected: dict[str, list[str]] = {}
    for column, policy in category_config.items():
        counter = counts.get(column, Counter())
        mode = str(policy.get("mode", "all"))
        if mode == "top_k":
            k = int(policy.get("k", 20))
            labels = [label for label, _ in counter.most_common(k)]
            if MISSING_BUCKET in counter and MISSING_BUCKET not in labels:
                labels.append(MISSING_BUCKET)
            if bool(policy.get("other_bucket", True)):
                labels.append(OTHER_BUCKET)
        elif mode == "all":
            labels = sorted(counter)
        else:
            raise ValueError(f"unsupported category mode for {column}: {mode}")
        selected[column] = labels
    return selected


def category_label_for_value(raw_value: str | None, labels: list[str]) -> str:
    normalized = normalize_category(raw_value)
    if normalized in labels:
        return normalized
    if OTHER_BUCKET in labels:
        return OTHER_BUCKET
    return normalized


def read_model(path: str | None, stats: dict[str, RunningStats]) -> dict[str, object]:
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))

    features = []
    for spec in DEFAULT_MODEL_FEATURES:
        source = str(spec["source"])
        stat = stats[source]
        features.append(
            {
                "name": spec["name"],
                "source": source,
                "weight": spec["weight"],
                "mean": stat.mean,
                "scale": stat.std,
                "fill": stat.mean,
            }
        )
    return {
        "model_type": "demo_linear_home_credit_score",
        "trained": False,
        "score_meaning": "demo logit-like risk score; use trained JSON for real scoring",
        "bias": 0.0,
        "features": features,
    }


def scaled_feature(row: dict[str, str], feature: dict[str, object]) -> float:
    value = value_from_source(row, str(feature["source"]))
    if value is None:
        value = float(feature.get("fill", feature.get("mean", 0.0)))
    mean = float(feature.get("mean", 0.0))
    scale = float(feature.get("scale", 1.0))
    if abs(scale) <= 1e-12:
        scale = 1.0
    return (value - mean) / scale


def build_vector_defs(
    category_config: dict[str, dict[str, object]],
    categories: dict[str, list[str]],
    amount_columns: list[str],
    model: dict[str, object],
) -> tuple[list[VectorDef], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    vectors: list[VectorDef] = []
    aggregate_ops: list[dict[str, str]] = []
    numeric_rows: list[dict[str, str]] = []
    score_rows: list[dict[str, str]] = []

    target_name = "target.default"
    vectors.append(
        VectorDef(
            name=target_name,
            kind="target",
            source_column="TARGET",
            analysis="target",
            group="TARGET",
            label="default",
            value_fn=lambda row: float(int(parse_float(row.get("TARGET")) or 0)),
        )
    )

    for column in amount_columns:
        vector_name = f"numeric.{column}"
        vectors.append(
            VectorDef(
                name=vector_name,
                kind="numeric",
                source_column=column,
                analysis="numeric_summary",
                group=column,
                label=column,
                value_fn=lambda row, selected_column=column: float(value_from_source(row, selected_column) or 0.0),
            )
        )
        numeric_rows.append({"column": column, "vector": vector_name})

    for column in category_config:
        labels = categories[column]
        for label in labels:
            vector_name = f"category.{safe_name(column)}.{safe_name(label)}"
            vectors.append(
                VectorDef(
                    name=vector_name,
                    kind="mask",
                    source_column=column,
                    analysis="category",
                    group=column,
                    label=label,
                    value_fn=lambda row, selected_column=column, selected_label=label, selected_labels=labels: float(
                        category_label_for_value(row.get(selected_column), selected_labels) == selected_label
                    ),
                )
            )
            add_mask_ops(aggregate_ops, "category", column, label, vector_name, target_name, amount_columns)

    add_bucket_vectors(vectors, aggregate_ops, target_name)
    add_ratio_vectors(vectors, aggregate_ops, target_name)

    for feature in model.get("features", []):
        if not isinstance(feature, dict):
            continue
        feature_name = str(feature["name"])
        vector_name = f"ml.{safe_name(feature_name)}"
        vectors.append(
            VectorDef(
                name=vector_name,
                kind="ml_feature",
                source_column=str(feature.get("source", feature_name)),
                analysis="linear_score",
                group="linear_score",
                label=feature_name,
                value_fn=lambda row, selected_feature=feature: scaled_feature(row, selected_feature),
            )
        )
        score_rows.append(
            {
                "feature": feature_name,
                "vector": vector_name,
                "weight": str(float(feature.get("weight", 0.0))),
                "bias": str(float(model.get("bias", 0.0))),
            }
        )

    return vectors, aggregate_ops, numeric_rows, score_rows


def add_mask_ops(
    aggregate_ops: list[dict[str, str]],
    analysis: str,
    group: str,
    label: str,
    mask_vector: str,
    target_vector: str,
    amount_columns: list[str],
) -> None:
    aggregate_ops.append(
        {
            "analysis": analysis,
            "group": group,
            "label": label,
            "operation": "count",
            "value_name": "rows",
            "mask_vector": mask_vector,
            "value_vector": "",
        }
    )
    aggregate_ops.append(
        {
            "analysis": analysis,
            "group": group,
            "label": label,
            "operation": "default_count",
            "value_name": "TARGET",
            "mask_vector": mask_vector,
            "value_vector": target_vector,
        }
    )
    for column in amount_columns:
        aggregate_ops.append(
            {
                "analysis": analysis,
                "group": group,
                "label": label,
                "operation": "masked_sum",
                "value_name": column,
                "mask_vector": mask_vector,
                "value_vector": f"numeric.{column}",
            }
        )


def add_bucket_vectors(vectors: list[VectorDef], aggregate_ops: list[dict[str, str]], target_name: str) -> None:
    amount_columns: list[str] = []
    age_labels = ["lt_25", "25_34", "35_44", "45_54", "55_64", "65_plus", MISSING_BUCKET]
    for label in age_labels:
        name = f"bucket.age.{safe_name(label)}"
        vectors.append(
            VectorDef(
                name=name,
                kind="mask",
                source_column="DAYS_BIRTH",
                analysis="bucket",
                group="AGE_YEARS",
                label=label,
                value_fn=lambda row, selected_label=label: float(bucket_age(row) == selected_label),
            )
        )
        add_mask_ops(aggregate_ops, "bucket", "AGE_YEARS", label, name, target_name, amount_columns)

    ext_labels = [MISSING_BUCKET, "0_0.2", "0.2_0.4", "0.4_0.6", "0.6_0.8", "0.8_1.0"]
    for column in ["EXT_SOURCE_1", "EXT_SOURCE_2", "EXT_SOURCE_3"]:
        for label in ext_labels:
            name = f"bucket.{safe_name(column)}.{safe_name(label)}"
            vectors.append(
                VectorDef(
                    name=name,
                    kind="mask",
                    source_column=column,
                    analysis="bucket",
                    group=column,
                    label=label,
                    value_fn=lambda row, selected_column=column, selected_label=label: float(
                        bucket_ext_source(row, selected_column) == selected_label
                    ),
                )
            )
            add_mask_ops(aggregate_ops, "bucket", column, label, name, target_name, amount_columns)

    for label in [MISSING_BUCKET, "anomaly_365243", "normal"]:
        name = f"bucket.DAYS_EMPLOYED.{safe_name(label)}"
        vectors.append(
            VectorDef(
                name=name,
                kind="mask",
                source_column="DAYS_EMPLOYED",
                analysis="bucket",
                group="DAYS_EMPLOYED",
                label=label,
                value_fn=lambda row, selected_label=label: float(bucket_days_employed(row) == selected_label),
            )
        )
        add_mask_ops(aggregate_ops, "bucket", "DAYS_EMPLOYED", label, name, target_name, amount_columns)


def add_ratio_vectors(vectors: list[VectorDef], aggregate_ops: list[dict[str, str]], target_name: str) -> None:
    ratio_sources = [
        "CREDIT_INCOME_PERCENT",
        "ANNUITY_INCOME_PERCENT",
        "CREDIT_TERM",
        "DAYS_EMPLOYED_PERCENT",
    ]
    labels = ["invalid", "negative", "0_0.1", "0.1_0.2", "0.2_0.4", "0.4_0.6", "0.6_1.0", "gte_1.0"]
    for source in ratio_sources:
        for label in labels:
            name = f"ratio.{safe_name(source)}.{safe_name(label)}"
            vectors.append(
                VectorDef(
                    name=name,
                    kind="mask",
                    source_column=source,
                    analysis="ratio",
                    group=source,
                    label=label,
                    value_fn=lambda row, selected_source=source, selected_label=label: float(
                        bucket_ratio(row, selected_source) == selected_label
                    ),
                )
            )
            add_mask_ops(aggregate_ops, "ratio", source, label, name, target_name, [])


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_vectors(input_path: Path, output_dir: Path, row_limit: int, vectors: list[VectorDef]) -> int:
    vector_dir = output_dir / "vectors"
    vector_dir.mkdir(parents=True, exist_ok=True)
    handles: dict[str, object] = {}
    try:
        for vector in vectors:
            handles[vector.name] = (vector_dir / f"{safe_name(vector.name)}.csv").open("w", encoding="utf-8", newline="")
        rows = 0
        for row in iter_rows(input_path, row_limit):
            rows += 1
            for vector in vectors:
                value = vector.value_fn(row)
                handles[vector.name].write(f"{float(value):.17g}\n")
        return rows
    finally:
        for handle in handles.values():
            handle.close()


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    amount_columns = [item.strip() for item in args.amount_columns.split(",") if item.strip()]
    category_config = read_category_config(args.category_config)

    rows, category_counts, initial_stats = collect_first_pass(
        input_path,
        args.row_limit,
        category_config,
        DEFAULT_MODEL_FEATURES,
    )
    model = read_model(args.model_json, initial_stats)
    selected = selected_categories(category_config, category_counts)
    vectors, aggregate_ops, numeric_rows, score_rows = build_vector_defs(category_config, selected, amount_columns, model)
    written_rows = write_vectors(input_path, output_dir, args.row_limit, vectors)

    vector_manifest_rows = [
        {
            "name": vector.name,
            "kind": vector.kind,
            "source_column": vector.source_column,
            "analysis": vector.analysis,
            "group": vector.group,
            "label": vector.label,
            "rows": written_rows,
            "file": f"vectors/{safe_name(vector.name)}.csv",
        }
        for vector in vectors
    ]
    write_csv(
        output_dir / "vector_manifest.csv",
        ["name", "kind", "source_column", "analysis", "group", "label", "rows", "file"],
        vector_manifest_rows,
    )
    write_csv(
        output_dir / "aggregate_operations.csv",
        ["analysis", "group", "label", "operation", "value_name", "mask_vector", "value_vector"],
        aggregate_ops,
    )
    write_csv(output_dir / "numeric_vectors.csv", ["column", "vector"], numeric_rows)
    write_csv(output_dir / "linear_score_vectors.csv", ["feature", "vector", "weight", "bias"], score_rows)

    (output_dir / "linear_score_model.json").write_text(json.dumps(model, indent=2), encoding="utf-8")
    prep_manifest = {
        "source": str(input_path),
        "rows": rows,
        "written_rows": written_rows,
        "row_limit": args.row_limit,
        "category_config": category_config,
        "selected_categories": selected,
        "missing_bucket": MISSING_BUCKET,
        "other_bucket": OTHER_BUCKET,
        "amount_columns": amount_columns,
        "vector_count": len(vectors),
        "aggregate_operation_count": len(aggregate_ops),
        "model_type": model.get("model_type"),
        "model_trained": model.get("trained", False),
        "note": "Prepared plaintext vectors are local client artifacts. Encrypt before server upload.",
    }
    (output_dir / "preparation_manifest.json").write_text(json.dumps(prep_manifest, indent=2), encoding="utf-8")

    print(f"prepared Home Credit vectors: {output_dir}")
    print(f"rows: {written_rows}")
    print(f"vectors: {len(vectors)}")
    print(f"aggregate operations: {len(aggregate_ops)}")


if __name__ == "__main__":
    main()
