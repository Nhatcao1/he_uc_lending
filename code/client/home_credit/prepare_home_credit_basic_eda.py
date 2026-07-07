#!/usr/bin/env python3
"""Prepare Home Credit vectors for encrypted EDA and linear scoring.

This script runs on the client, next to the raw Home Credit CSV. It does not
encrypt. It creates local prepared vector CSVs and manifests that the OpenFHE
client encryption tool can turn into server-uploadable ciphertext bundles.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
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
    "NAME_TYPE_SUITE": {"mode": "all"},
    "NAME_CONTRACT_TYPE": {"mode": "all"},
    "FLAG_OWN_CAR": {"mode": "all"},
    "FLAG_OWN_REALTY": {"mode": "all"},
    "NAME_INCOME_TYPE": {"mode": "all"},
    "NAME_FAMILY_STATUS": {"mode": "all"},
    "NAME_EDUCATION_TYPE": {"mode": "all"},
    "NAME_HOUSING_TYPE": {"mode": "all"},
    "OCCUPATION_TYPE": {"mode": "top_k", "k": 20, "other_bucket": True},
    "ORGANIZATION_TYPE": {"mode": "top_k", "k": 30, "other_bucket": True},
}

DEFAULT_PREVIOUS_CATEGORY_CONFIG: dict[str, dict[str, object]] = {
    "NAME_CONTRACT_TYPE": {"mode": "all"},
    "WEEKDAY_APPR_PROCESS_START": {"mode": "all"},
    "NAME_CASH_LOAN_PURPOSE": {"mode": "top_k", "k": 20, "other_bucket": True},
    "NAME_CONTRACT_STATUS": {"mode": "all"},
    "NAME_PAYMENT_TYPE": {"mode": "all"},
    "CODE_REJECT_REASON": {"mode": "all"},
    "NAME_TYPE_SUITE": {"mode": "all"},
    "NAME_CLIENT_TYPE": {"mode": "all"},
    "NAME_GOODS_CATEGORY": {"mode": "top_k", "k": 25, "other_bucket": True},
    "NAME_PORTFOLIO": {"mode": "all"},
    "NAME_PRODUCT_TYPE": {"mode": "all"},
    "CHANNEL_TYPE": {"mode": "all"},
    "NAME_SELLER_INDUSTRY": {"mode": "all"},
    "NAME_YIELD_GROUP": {"mode": "all"},
    "PRODUCT_COMBINATION": {"mode": "top_k", "k": 25, "other_bucket": True},
    "NFLAG_INSURED_ON_APPROVAL": {"mode": "all"},
}

DEFAULT_AMOUNT_COLUMNS = ["AMT_CREDIT", "AMT_INCOME_TOTAL", "AMT_ANNUITY"]
DEFAULT_NUMERIC_SUMMARY_COLUMNS = [
    "AMT_CREDIT",
    "AMT_INCOME_TOTAL",
    "AMT_ANNUITY",
    "AMT_GOODS_PRICE",
    "EXT_SOURCE_1",
    "EXT_SOURCE_2",
    "EXT_SOURCE_3",
    "DAYS_BIRTH",
    "DAYS_EMPLOYED",
]
DEFAULT_MISSING_COLUMNS = [
    "AMT_ANNUITY",
    "AMT_GOODS_PRICE",
    "EXT_SOURCE_1",
    "EXT_SOURCE_2",
    "EXT_SOURCE_3",
    "OCCUPATION_TYPE",
    "NAME_TYPE_SUITE",
    "DAYS_EMPLOYED",
]
DEFAULT_HISTOGRAM_COLUMNS = [
    "AMT_CREDIT",
    "AMT_INCOME_TOTAL",
    "AMT_ANNUITY",
    "AMT_GOODS_PRICE",
    "AGE_YEARS",
    "EXT_SOURCE_1",
    "EXT_SOURCE_2",
    "EXT_SOURCE_3",
    "CREDIT_INCOME_PERCENT",
    "ANNUITY_INCOME_PERCENT",
    "CREDIT_TERM",
    "DAYS_EMPLOYED_PERCENT",
]
DEFAULT_CORRELATION_PAIRS = [
    ("AMT_CREDIT", "AMT_INCOME_TOTAL"),
    ("AMT_CREDIT", "AMT_ANNUITY"),
    ("AMT_CREDIT", "AMT_GOODS_PRICE"),
    ("EXT_SOURCE_2", "EXT_SOURCE_3"),
    ("CREDIT_INCOME_PERCENT", "ANNUITY_INCOME_PERCENT"),
]

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

JOIN_STATUS_COLUMN = "NAME_CONTRACT_STATUS"
JOIN_HMAC_ANALYSIS = "previous_application_token_join_hmac"
JOIN_PSI_ANALYSIS = "previous_application_token_join_psi"


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
    table: str
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
    parser.add_argument(
        "--previous-application",
        default="",
        help="Optional previous_application.csv path for notebook 5.15 criteria.",
    )
    parser.add_argument("--output-dir", default="prepared_payloads/home_credit_basic_eda")
    parser.add_argument("--row-limit", type=int, default=0, help="Optional local test limit. 0 means all rows.")
    parser.add_argument(
        "--previous-row-limit",
        type=int,
        default=0,
        help="Optional previous_application local test limit. 0 means all rows.",
    )
    parser.add_argument("--category-config", help="Optional JSON category policy file.")
    parser.add_argument("--previous-category-config", help="Optional JSON previous_application category policy file.")
    parser.add_argument("--model-json", help="Optional trained/exported linear model JSON.")
    parser.add_argument(
        "--join-secret",
        default="home-credit-local-token-join-demo",
        help="Secret used to HMAC SK_ID_CURR for tokenized join demo artifacts. Override outside demos.",
    )
    parser.add_argument(
        "--psi-matched-token-file",
        default="",
        help=(
            "Optional newline/CSV file of HMAC tokens produced after a PSI run. "
            "When omitted, the PSI-ready workload uses the local application token set as a same-size fixture."
        ),
    )
    parser.add_argument(
        "--amount-columns",
        default=",".join(DEFAULT_AMOUNT_COLUMNS),
        help="Comma-separated amount columns to include in masked sums.",
    )
    parser.add_argument(
        "--numeric-columns",
        default=",".join(DEFAULT_NUMERIC_SUMMARY_COLUMNS),
        help="Comma-separated application numeric columns for encrypted summary sums.",
    )
    parser.add_argument(
        "--missing-columns",
        default=",".join(DEFAULT_MISSING_COLUMNS),
        help="Comma-separated application columns for encrypted missing-value counts.",
    )
    parser.add_argument(
        "--histogram-columns",
        default=",".join(DEFAULT_HISTOGRAM_COLUMNS),
        help="Comma-separated application derived/raw numeric columns to bucket into encrypted histogram masks.",
    )
    parser.add_argument(
        "--correlation-pairs",
        default=";".join(f"{left}:{right}" for left, right in DEFAULT_CORRELATION_PAIRS),
        help="Semicolon-separated selected pairs such as AMT_CREDIT:AMT_INCOME_TOTAL.",
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


def read_previous_category_config(path: str | None) -> dict[str, dict[str, object]]:
    if not path:
        return DEFAULT_PREVIOUS_CATEGORY_CONFIG
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    columns = data.get("categorical_columns", data)
    if not isinstance(columns, dict):
        raise ValueError("previous category config must be a dict or contain categorical_columns")
    return {str(key): dict(value) for key, value in columns.items()}


def split_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_correlation_pairs(value: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for item in value.split(";"):
        cleaned = item.strip()
        if not cleaned:
            continue
        if ":" not in cleaned:
            raise ValueError(f"correlation pair must be left:right, got: {cleaned}")
        left, right = [part.strip() for part in cleaned.split(":", 1)]
        if not left or not right:
            raise ValueError(f"correlation pair must be left:right, got: {cleaned}")
        pairs.append((left, right))
    return pairs


def join_token(secret: str, raw_id: str | None) -> str:
    cleaned = (raw_id or "").strip()
    if not cleaned:
        return ""
    return hmac.new(secret.encode("utf-8"), cleaned.encode("utf-8"), hashlib.sha256).hexdigest()


def read_token_file(path: str) -> set[str]:
    tokens: set[str] = set()
    if not path:
        return tokens
    input_path = Path(path)
    with input_path.open("r", encoding="utf-8-sig", newline="") as input_file:
        reader = csv.reader(input_file)
        for row in reader:
            if not row:
                continue
            token = row[0].strip()
            if not token or token.lower() in {"token", "join_token", "hmac_token"}:
                continue
            tokens.add(token)
    return tokens


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


def is_missing_value(value: str | None) -> bool:
    if value is None:
        return True
    cleaned = str(value).strip()
    return not cleaned or cleaned.lower() in {"nan", "none", "null"}


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
) -> tuple[int, dict[str, Counter[str]], dict[str, RunningStats], dict[str, int]]:
    category_counts = {column: Counter() for column in category_config}
    stats = {str(feature["source"]): RunningStats() for feature in model_features}
    target_by_curr: dict[str, int] = {}
    rows = 0
    for row in iter_rows(input_path, row_limit):
        rows += 1
        sk_id = (row.get("SK_ID_CURR") or "").strip()
        target = parse_float(row.get("TARGET"))
        if sk_id and target is not None:
            target_by_curr[sk_id] = int(target)
        for column, counter in category_counts.items():
            counter[normalize_category(row.get(column))] += 1
        for source, stat in stats.items():
            stat.add(value_from_source(row, source))
    return rows, category_counts, stats, target_by_curr


def collect_application_tokens(input_path: Path, row_limit: int, join_secret: str) -> tuple[list[str], set[str]]:
    ordered_tokens: list[str] = []
    unique_tokens: set[str] = set()
    for row in iter_rows(input_path, row_limit):
        token = join_token(join_secret, row.get("SK_ID_CURR"))
        if not token:
            continue
        ordered_tokens.append(token)
        unique_tokens.add(token)
    return ordered_tokens, unique_tokens


def collect_previous_tokens(input_path: Path, row_limit: int, join_secret: str) -> list[str]:
    tokens: list[str] = []
    for row in iter_rows(input_path, row_limit):
        tokens.append(join_token(join_secret, row.get("SK_ID_CURR")))
    return tokens


def collect_category_counts(
    input_path: Path,
    row_limit: int,
    category_config: dict[str, dict[str, object]],
) -> tuple[int, dict[str, Counter[str]]]:
    category_counts = {column: Counter() for column in category_config}
    rows = 0
    for row in iter_rows(input_path, row_limit):
        rows += 1
        for column, counter in category_counts.items():
            counter[normalize_category(row.get(column))] += 1
    return rows, category_counts


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
    previous_categories: dict[str, list[str]],
    amount_columns: list[str],
    numeric_columns: list[str],
    missing_columns: list[str],
    histogram_columns: list[str],
    correlation_pairs: list[tuple[str, str]],
    model: dict[str, object],
    target_by_curr: dict[str, int],
) -> tuple[list[VectorDef], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    vectors: list[VectorDef] = []
    aggregate_ops: list[dict[str, str]] = []
    numeric_rows: list[dict[str, str]] = []
    score_rows: list[dict[str, str]] = []
    vector_names: set[str] = set()
    numeric_vector_names: dict[str, str] = {}

    def add_vector(vector: VectorDef) -> None:
        if vector.name in vector_names:
            return
        vector_names.add(vector.name)
        vectors.append(vector)

    def add_numeric_vector(source: str, *, summary: bool) -> str:
        existing = numeric_vector_names.get(source)
        if existing:
            if summary and not any(row["column"] == source for row in numeric_rows):
                numeric_rows.append({"column": source, "vector": existing})
            return existing
        vector_name = f"numeric.{safe_name(source)}"
        numeric_vector_names[source] = vector_name
        add_vector(
            VectorDef(
                table="application_train",
                name=vector_name,
                kind="numeric" if summary else "numeric_aux",
                source_column=source,
                analysis="application_numeric_summary" if summary else "numeric_aux",
                group=source,
                label=source,
                value_fn=lambda row, selected_source=source: float(value_from_source(row, selected_source) or 0.0),
            )
        )
        if summary:
            numeric_rows.append({"column": source, "vector": vector_name})
        return vector_name

    row_mask = "row.application_train.all"
    target_default = "target.default"
    target_repaid = "target.repaid"
    add_vector(
        VectorDef(
            table="application_train",
            name=row_mask,
            kind="mask",
            source_column="__ROW__",
            analysis="target_balance",
            group="TARGET",
            label="all_rows",
            value_fn=lambda row: 1.0,
        )
    )
    add_vector(
        VectorDef(
            table="application_train",
            name=target_default,
            kind="target",
            source_column="TARGET",
            analysis="target_balance",
            group="TARGET",
            label="default",
            value_fn=lambda row: float(int(parse_float(row.get("TARGET")) or 0) == 1),
        )
    )
    add_vector(
        VectorDef(
            table="application_train",
            name=target_repaid,
            kind="target",
            source_column="TARGET",
            analysis="target_balance",
            group="TARGET",
            label="repaid",
            value_fn=lambda row: float(parse_float(row.get("TARGET")) == 0),
        )
    )
    add_count_op(aggregate_ops, "target_balance", "TARGET", "all_rows", row_mask)
    add_count_op(aggregate_ops, "target_balance", "TARGET", "default", target_default)
    add_count_op(aggregate_ops, "target_balance", "TARGET", "repaid", target_repaid)

    for column in numeric_columns:
        add_numeric_vector(column, summary=True)
    for column in amount_columns:
        add_numeric_vector(column, summary=column in numeric_columns)

    for column in missing_columns:
        vector_name = f"missing.application_train.{safe_name(column)}"
        add_vector(
            VectorDef(
                table="application_train",
                name=vector_name,
                kind="mask",
                source_column=column,
                analysis="missing_data",
                group=column,
                label=MISSING_BUCKET,
                value_fn=lambda row, selected_column=column: float(
                    is_missing_value(row.get(selected_column))
                    if selected_column not in {"AGE_YEARS", "CREDIT_INCOME_PERCENT", "ANNUITY_INCOME_PERCENT", "CREDIT_TERM", "DAYS_EMPLOYED_PERCENT"}
                    else value_from_source(row, selected_column) is None
                ),
            )
        )
        add_count_op(aggregate_ops, "missing_data", column, MISSING_BUCKET, vector_name)

    for column in category_config:
        labels = categories[column]
        for label in labels:
            vector_name = f"category.application_train.{safe_name(column)}.{safe_name(label)}"
            add_vector(
                VectorDef(
                    table="application_train",
                    name=vector_name,
                    kind="mask",
                    source_column=column,
                    analysis="application_category_counts",
                    group=column,
                    label=label,
                    value_fn=lambda row, selected_column=column, selected_label=label, selected_labels=labels: float(
                        category_label_for_value(row.get(selected_column), selected_labels) == selected_label
                    ),
                )
            )
            add_count_op(aggregate_ops, "application_category_counts", column, label, vector_name)
            add_mask_ops(
                aggregate_ops,
                "application_default_rates",
                column,
                label,
                vector_name,
                target_default,
                amount_columns,
            )

    for source in histogram_columns:
        for label in histogram_labels(source):
            vector_name = f"histogram.application_train.{safe_name(source)}.{safe_name(label)}"
            add_vector(
                VectorDef(
                    table="application_train",
                    name=vector_name,
                    kind="mask",
                    source_column=source,
                    analysis="application_numeric_histograms",
                    group=source,
                    label=label,
                    value_fn=lambda row, selected_source=source, selected_label=label: float(
                        bucket_histogram(row, selected_source) == selected_label
                    ),
                )
            )
            add_mask_ops(
                aggregate_ops,
                "application_numeric_histograms",
                source,
                label,
                vector_name,
                target_default,
                [],
            )

    previous_target = "previous_application.target.default"
    if previous_categories:
        add_vector(
            VectorDef(
                table="previous_application",
                name=previous_target,
                kind="target",
                source_column="SK_ID_CURR",
                analysis="previous_application_target_rates",
                group="TARGET",
                label="default",
                value_fn=lambda row: float(target_by_curr.get((row.get("SK_ID_CURR") or "").strip(), 0) == 1),
            )
        )
    for column, labels in previous_categories.items():
        for label in labels:
            base_vector = f"category.previous_application.{safe_name(column)}.{safe_name(label)}"
            joined_vector = f"joined.previous_application.{safe_name(column)}.{safe_name(label)}"
            add_vector(
                VectorDef(
                    table="previous_application",
                    name=base_vector,
                    kind="mask",
                    source_column=column,
                    analysis="previous_application_category_counts",
                    group=column,
                    label=label,
                    value_fn=lambda row, selected_column=column, selected_label=label, selected_labels=labels: float(
                        category_label_for_value(row.get(selected_column), selected_labels) == selected_label
                    ),
                )
            )
            add_vector(
                VectorDef(
                    table="previous_application",
                    name=joined_vector,
                    kind="mask",
                    source_column=f"{column}+SK_ID_CURR",
                    analysis="previous_application_target_rates",
                    group=column,
                    label=label,
                    value_fn=lambda row, selected_column=column, selected_label=label, selected_labels=labels: float(
                        (row.get("SK_ID_CURR") or "").strip() in target_by_curr
                        and category_label_for_value(row.get(selected_column), selected_labels) == selected_label
                    ),
                )
            )
            add_count_op(aggregate_ops, "previous_application_category_counts", column, label, base_vector)
            if column == JOIN_STATUS_COLUMN:
                add_count_op(aggregate_ops, JOIN_HMAC_ANALYSIS, column, label, base_vector)
                add_count_op(aggregate_ops, JOIN_PSI_ANALYSIS, column, label, base_vector)
            add_mask_ops(
                aggregate_ops,
                "previous_application_target_rates",
                column,
                label,
                joined_vector,
                previous_target,
                [],
            )

    for left, right in correlation_pairs:
        left_vector = add_numeric_vector(left, summary=left in numeric_columns)
        right_vector = add_numeric_vector(right, summary=right in numeric_columns)
        pair_label = f"{left}__{right}"
        valid_vector = f"corr.valid.{safe_name(left)}.{safe_name(right)}"
        add_vector(
            VectorDef(
                table="application_train",
                name=valid_vector,
                kind="mask",
                source_column=pair_label,
                analysis="selected_correlation_stats",
                group=pair_label,
                label="valid_pair",
                value_fn=lambda row, selected_left=left, selected_right=right: float(
                    value_from_source(row, selected_left) is not None and value_from_source(row, selected_right) is not None
                ),
            )
        )
        add_count_op(aggregate_ops, "selected_correlation_stats", pair_label, "n", valid_vector)
        add_masked_sum_op(aggregate_ops, "selected_correlation_stats", pair_label, "sum_x", valid_vector, left_vector)
        add_masked_sum_op(aggregate_ops, "selected_correlation_stats", pair_label, "sum_y", valid_vector, right_vector)
        add_masked_sum_op(aggregate_ops, "selected_correlation_stats", pair_label, "sum_xy", left_vector, right_vector)
        add_masked_sum_op(aggregate_ops, "selected_correlation_stats", pair_label, "sum_x2", left_vector, left_vector)
        add_masked_sum_op(aggregate_ops, "selected_correlation_stats", pair_label, "sum_y2", right_vector, right_vector)

    for feature in model.get("features", []):
        if not isinstance(feature, dict):
            continue
        feature_name = str(feature["name"])
        vector_name = f"ml.{safe_name(feature_name)}"
        add_vector(
            VectorDef(
                table="application_train",
                name=vector_name,
                kind="ml_feature",
                source_column=str(feature.get("source", feature_name)),
                analysis="linear_score_demo",
                group="linear_score_demo",
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


def add_count_op(
    aggregate_ops: list[dict[str, str]],
    analysis: str,
    group: str,
    label: str,
    mask_vector: str,
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


def add_masked_sum_op(
    aggregate_ops: list[dict[str, str]],
    analysis: str,
    group: str,
    value_name: str,
    mask_vector: str,
    value_vector: str,
) -> None:
    aggregate_ops.append(
        {
            "analysis": analysis,
            "group": group,
            "label": value_name,
            "operation": "masked_sum",
            "value_name": value_name,
            "mask_vector": mask_vector,
            "value_vector": value_vector,
        }
    )


def add_mask_ops(
    aggregate_ops: list[dict[str, str]],
    analysis: str,
    group: str,
    label: str,
    mask_vector: str,
    target_vector: str,
    amount_columns: list[str],
) -> None:
    add_count_op(aggregate_ops, analysis, group, label, mask_vector)
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


def histogram_labels(source: str) -> list[str]:
    if source == "AGE_YEARS":
        return ["lt_25", "25_34", "35_44", "45_54", "55_64", "65_plus", MISSING_BUCKET]
    if source in {"EXT_SOURCE_1", "EXT_SOURCE_2", "EXT_SOURCE_3"}:
        return [MISSING_BUCKET, "0_0.2", "0.2_0.4", "0.4_0.6", "0.6_0.8", "0.8_1.0"]
    if source == "DAYS_EMPLOYED":
        return [MISSING_BUCKET, "anomaly_365243", "normal"]
    if source in {"CREDIT_INCOME_PERCENT", "ANNUITY_INCOME_PERCENT", "CREDIT_TERM", "DAYS_EMPLOYED_PERCENT"}:
        return ["invalid", "negative", "0_0.1", "0.1_0.2", "0.2_0.4", "0.4_0.6", "0.6_1.0", "gte_1.0"]
    if source == "AMT_INCOME_TOTAL":
        return [MISSING_BUCKET, "0_100k", "100k_200k", "200k_500k", "500k_plus"]
    return [MISSING_BUCKET, "0_100k", "100k_300k", "300k_600k", "600k_1m", "1m_plus"]


def bucket_histogram(row: dict[str, str], source: str) -> str:
    if source == "AGE_YEARS":
        return bucket_age(row)
    if source in {"EXT_SOURCE_1", "EXT_SOURCE_2", "EXT_SOURCE_3"}:
        return bucket_ext_source(row, source)
    if source == "DAYS_EMPLOYED":
        return bucket_days_employed(row)
    if source in {"CREDIT_INCOME_PERCENT", "ANNUITY_INCOME_PERCENT", "CREDIT_TERM", "DAYS_EMPLOYED_PERCENT"}:
        return bucket_ratio(row, source)

    value = value_from_source(row, source)
    if value is None:
        return MISSING_BUCKET
    if source == "AMT_INCOME_TOTAL":
        if value < 100_000:
            return "0_100k"
        if value < 200_000:
            return "100k_200k"
        if value < 500_000:
            return "200k_500k"
        return "500k_plus"
    if value < 100_000:
        return "0_100k"
    if value < 300_000:
        return "100k_300k"
    if value < 600_000:
        return "300k_600k"
    if value < 1_000_000:
        return "600k_1m"
    return "1m_plus"


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_token_file(path: Path, tokens: Iterable[str]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(["token"])
        for token in tokens:
            if not token:
                continue
            writer.writerow([token])
            count += 1
    return count


def write_join_token_artifacts(
    output_dir: Path,
    application_tokens: list[str],
    application_token_set: set[str],
    previous_tokens: list[str],
    psi_matched_tokens: set[str],
) -> dict[str, object]:
    hmac_dir = output_dir / "join" / "hmac"
    psi_dir = output_dir / "join" / "psi"

    hmac_left_count = write_token_file(hmac_dir / "left_tokens.csv", sorted(application_token_set))
    hmac_right_count = write_token_file(hmac_dir / "right_tokens.csv", previous_tokens)

    psi_tokens = psi_matched_tokens if psi_matched_tokens else application_token_set
    psi_left_count = write_token_file(psi_dir / "left_tokens.csv", sorted(psi_tokens))
    psi_right_count = write_token_file(psi_dir / "right_tokens.csv", previous_tokens)

    metadata = {
        "hmac": {
            "left_tokens": "join/hmac/left_tokens.csv",
            "right_tokens": "join/hmac/right_tokens.csv",
            "left_token_count": hmac_left_count,
            "right_token_count": hmac_right_count,
            "match_source": "local_hmac_token_set",
        },
        "psi": {
            "left_tokens": "join/psi/left_tokens.csv",
            "right_tokens": "join/psi/right_tokens.csv",
            "left_token_count": psi_left_count,
            "right_token_count": psi_right_count,
            "match_source": "psi_matched_token_file" if psi_matched_tokens else "local_fixture_until_psi_output_is_supplied",
        },
        "token_type": "HMAC-SHA256(SK_ID_CURR)",
        "raw_ids_included": False,
        "application_token_rows_before_dedup": len(application_tokens),
        "previous_token_rows": len(previous_tokens),
    }
    (output_dir / "join" / "join_manifest.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def write_vectors(
    table_inputs: dict[str, tuple[Path, int]],
    output_dir: Path,
    vectors: list[VectorDef],
) -> dict[str, int]:
    vector_dir = output_dir / "vectors"
    vector_dir.mkdir(parents=True, exist_ok=True)
    handles: dict[str, object] = {}
    rows_by_vector: dict[str, int] = {vector.name: 0 for vector in vectors}
    vectors_by_table: dict[str, list[VectorDef]] = defaultdict(list)
    for vector in vectors:
        vectors_by_table[vector.table].append(vector)
    try:
        for vector in vectors:
            handles[vector.name] = (vector_dir / f"{safe_name(vector.name)}.csv").open("w", encoding="utf-8", newline="")
        for table, table_vectors in vectors_by_table.items():
            if table not in table_inputs:
                raise ValueError(f"no input path configured for vector table: {table}")
            input_path, row_limit = table_inputs[table]
            for row in iter_rows(input_path, row_limit):
                for vector in table_vectors:
                    value = vector.value_fn(row)
                    handles[vector.name].write(f"{float(value):.17g}\n")
                    rows_by_vector[vector.name] += 1
        return rows_by_vector
    finally:
        for handle in handles.values():
            handle.close()


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    previous_path = Path(args.previous_application) if args.previous_application else None
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if previous_path and not previous_path.is_file():
        raise FileNotFoundError(f"previous_application file not found: {previous_path}")

    amount_columns = split_list(args.amount_columns)
    numeric_columns = list(dict.fromkeys(split_list(args.numeric_columns) + amount_columns))
    missing_columns = split_list(args.missing_columns)
    histogram_columns = split_list(args.histogram_columns)
    correlation_pairs = parse_correlation_pairs(args.correlation_pairs)
    category_config = read_category_config(args.category_config)
    previous_category_config = read_previous_category_config(args.previous_category_config) if previous_path else {}

    rows, category_counts, initial_stats, target_by_curr = collect_first_pass(
        input_path,
        args.row_limit,
        category_config,
        DEFAULT_MODEL_FEATURES,
    )
    previous_rows = 0
    previous_selected: dict[str, list[str]] = {}
    if previous_path:
        previous_rows, previous_counts = collect_category_counts(
            previous_path,
            args.previous_row_limit,
            previous_category_config,
        )
        previous_selected = selected_categories(previous_category_config, previous_counts)

    model = read_model(args.model_json, initial_stats)
    selected = selected_categories(category_config, category_counts)
    vectors, aggregate_ops, numeric_rows, score_rows = build_vector_defs(
        category_config,
        selected,
        previous_selected,
        amount_columns,
        numeric_columns,
        missing_columns,
        histogram_columns,
        correlation_pairs,
        model,
        target_by_curr,
    )
    table_inputs: dict[str, tuple[Path, int]] = {
        "application_train": (input_path, args.row_limit),
    }
    if previous_path:
        table_inputs["previous_application"] = (previous_path, args.previous_row_limit)
    rows_by_vector = write_vectors(table_inputs, output_dir, vectors)

    application_tokens, application_token_set = collect_application_tokens(input_path, args.row_limit, args.join_secret)
    previous_tokens: list[str] = []
    psi_tokens: set[str] = set()
    join_metadata: dict[str, object] = {}
    if previous_path:
        previous_tokens = collect_previous_tokens(previous_path, args.previous_row_limit, args.join_secret)
        psi_tokens = read_token_file(args.psi_matched_token_file)
        join_metadata = write_join_token_artifacts(
            output_dir,
            application_tokens,
            application_token_set,
            previous_tokens,
            psi_tokens,
        )

    vector_manifest_rows = [
        {
            "table": vector.table,
            "name": vector.name,
            "kind": vector.kind,
            "source_column": vector.source_column,
            "analysis": vector.analysis,
            "group": vector.group,
            "label": vector.label,
            "rows": rows_by_vector[vector.name],
            "file": f"vectors/{safe_name(vector.name)}.csv",
        }
        for vector in vectors
    ]
    write_csv(
        output_dir / "vector_manifest.csv",
        ["table", "name", "kind", "source_column", "analysis", "group", "label", "rows", "file"],
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
        "application_train_source": str(input_path),
        "previous_application_source": str(previous_path) if previous_path else "",
        "application_train_rows": rows,
        "previous_application_rows": previous_rows,
        "row_limit": args.row_limit,
        "previous_row_limit": args.previous_row_limit,
        "category_config": category_config,
        "selected_categories": selected,
        "previous_category_config": previous_category_config,
        "selected_previous_categories": previous_selected,
        "missing_bucket": MISSING_BUCKET,
        "other_bucket": OTHER_BUCKET,
        "amount_columns": amount_columns,
        "numeric_columns": numeric_columns,
        "missing_columns": missing_columns,
        "histogram_columns": histogram_columns,
        "correlation_pairs": correlation_pairs,
        "target_lookup_count": len(target_by_curr),
        "join_token_count": len(application_token_set),
        "join_token_artifacts": join_metadata,
        "vector_count": len(vectors),
        "aggregate_operation_count": len(aggregate_ops),
        "implemented_criteria": [
            "missing_data",
            "target_balance",
            "application_numeric_summary",
            "application_category_counts",
            "application_default_rates",
            "application_numeric_histograms",
            "previous_application_category_counts" if previous_path else "previous_application_category_counts skipped",
            "previous_application_target_rates" if previous_path else "previous_application_target_rates skipped",
            "selected_correlation_stats",
            "linear_score_demo",
        ],
        "model_type": model.get("model_type"),
        "model_trained": model.get("trained", False),
        "note": "Prepared plaintext vectors are local client artifacts. Encrypt before server upload.",
    }
    (output_dir / "preparation_manifest.json").write_text(json.dumps(prep_manifest, indent=2), encoding="utf-8")

    print(f"prepared Home Credit vectors: {output_dir}")
    print(f"application_train rows: {rows}")
    print(f"previous_application rows: {previous_rows}")
    print(f"vectors: {len(vectors)}")
    print(f"aggregate operations: {len(aggregate_ops)}")


if __name__ == "__main__":
    main()
