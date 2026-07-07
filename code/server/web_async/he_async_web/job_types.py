"""Runnable encrypted Home Credit notebook-EDA job definitions."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def aggregate_job(
    *,
    label: str,
    stage: str,
    description: str,
    analysis: str,
    output_dir: str,
    client_requirements: list[str],
    server_returns: list[str],
    notebook_cells: str,
    he_operation: str,
) -> dict[str, Any]:
    return {
        "label": label,
        "family": "Home Credit Complete EDA",
        "stage": stage,
        "scheme": "CKKS",
        "binary": "server_home_credit_aggregate",
        "description": description,
        "notebook_cells": notebook_cells,
        "he_operation": he_operation,
        "required": ["crypto_context.bin", "eval_sum_keys.bin", "eval_mult_keys.bin", "aggregate_manifest.csv", "vectors/"],
        "client_requirements": client_requirements,
        "server_returns": server_returns,
        "command": [
            "--context",
            "crypto_context.bin",
            "--eval-sum-keys",
            "eval_sum_keys.bin",
            "--eval-mult-keys",
            "eval_mult_keys.bin",
            "--manifest",
            "aggregate_manifest.csv",
            "--input-dir",
            "vectors",
            "--output-dir",
            f"output/{output_dir}",
            "--analysis-filter",
            f"literal:{analysis}",
        ],
    }


JOB_TYPES: dict[str, dict[str, Any]] = {
    "home_credit_missing_data": aggregate_job(
        label="Missing Data Counts",
        stage="Notebook 4.x missing-value checks",
        description="Encrypted missing-count table for selected Home Credit application columns.",
        analysis="missing_data",
        output_dir="missing_data",
        notebook_cells="29, 31, 33, 35, 37, 39, 41",
        he_operation="sum(is_null_column_mask)",
        client_requirements=[
            "Client maps raw null/blank/nan values to one encrypted 0/1 missing mask per selected column.",
            "Column choice and null policy are plaintext metadata; raw cell values stay client-side.",
            "Server only sums encrypted missing masks; percentages are computed after client decrypts counts.",
        ],
        server_returns=["missing_data/aggregate_summary_manifest.csv", "missing_data/aggregates/*.bin"],
    ),
    "home_credit_target_balance": aggregate_job(
        label="Target Balance",
        stage="Notebook 5.5 target imbalance",
        description="Encrypted default/repaid count support for the Home Credit TARGET column.",
        analysis="target_balance",
        output_dir="target_balance",
        notebook_cells="52, 53",
        he_operation="sum(target_default_mask), sum(target_repaid_mask), sum(row_mask)",
        client_requirements=[
            "Client encodes TARGET into default, repaid, and row-count masks before encryption.",
            "Rows with missing TARGET should be excluded or represented by a documented target_missing mask.",
            "Server returns encrypted counts only; class percentages are client-side after decryption.",
        ],
        server_returns=["target_balance/aggregate_summary_manifest.csv", "target_balance/aggregates/*.bin"],
    ),
    "home_credit_application_numeric_summary": {
        "label": "Application Numeric Summary",
        "family": "Home Credit Complete EDA",
        "stage": "Notebook 5.1-5.3 distributions",
        "scheme": "CKKS",
        "binary": "server_numeric_summary",
        "description": "Packed encrypted sums for selected application_train numeric columns.",
        "notebook_cells": "44, 46, 48",
        "he_operation": "EvalSum(numeric_vector)",
        "required": ["crypto_context.bin", "eval_sum_keys.bin", "column_manifest.csv", "columns/"],
        "client_requirements": [
            "Client cleans or imputes numeric values before encryption and records missing policy separately.",
            "Selected columns include AMT_CREDIT, AMT_INCOME_TOTAL, AMT_ANNUITY, AMT_GOODS_PRICE, EXT_SOURCE_*, DAYS_BIRTH, and DAYS_EMPLOYED by default.",
            "Server returns encrypted sums; means need decrypted sum plus row/valid-count metadata on the client.",
        ],
        "server_returns": ["application_numeric_summary/summary_manifest.csv", "application_numeric_summary/sums/*.bin"],
        "command": [
            "--context",
            "crypto_context.bin",
            "--eval-sum-keys",
            "eval_sum_keys.bin",
            "--manifest",
            "column_manifest.csv",
            "--input-dir",
            "columns",
            "--output-dir",
            "output/application_numeric_summary",
        ],
    },
    "home_credit_application_category_counts": aggregate_job(
        label="Application Category Counts",
        stage="Notebook 5.4-5.13 categorical distributions",
        description="Encrypted value-count tables for application_train categorical columns.",
        analysis="application_category_counts",
        output_dir="application_category_counts",
        notebook_cells="50, 56, 59, 61, 64, 67, 70, 73, 76",
        he_operation="sum(one_hot_category_mask)",
        client_requirements=[
            "Client normalizes strings, applies __MISSING__, and uses top-K plus __OTHER__ where needed.",
            "Client one-hot encodes category labels into encrypted masks.",
            "Server never sees raw category strings beyond chosen label metadata in the manifest.",
        ],
        server_returns=[
            "application_category_counts/aggregate_summary_manifest.csv",
            "application_category_counts/aggregates/*.bin",
        ],
    ),
    "home_credit_application_default_rates": aggregate_job(
        label="Application Category Default Rates",
        stage="Notebook 5.14 category by target",
        description="Encrypted category counts, default counts, and amount sums for application_train categories.",
        analysis="application_default_rates",
        output_dir="application_default_rates",
        notebook_cells="80, 82, 84, 86, 88, 90, 92",
        he_operation="sum(mask), sum(mask * TARGET), sum(mask * amount)",
        client_requirements=[
            "Client prepares category masks and the TARGET default mask before encryption.",
            "Amount vectors such as AMT_CREDIT, AMT_INCOME_TOTAL, and AMT_ANNUITY can be encrypted for grouped sums.",
            "Default rates and amount means are computed client-side after decrypting server aggregate outputs.",
        ],
        server_returns=[
            "application_default_rates/aggregate_summary_manifest.csv",
            "application_default_rates/aggregates/*.bin",
        ],
    ),
    "home_credit_application_numeric_histograms": aggregate_job(
        label="Application Numeric Histograms",
        stage="Notebook 5.1-5.3 and EXT_SOURCE/age bucket EDA",
        description="Encrypted bin-count and default-count tables for selected numeric, age, EXT_SOURCE, and domain-ratio buckets.",
        analysis="application_numeric_histograms",
        output_dir="application_numeric_histograms",
        notebook_cells="44, 46, 48 plus age/EXT_SOURCE/domain-ratio bucket checks",
        he_operation="sum(bin_mask), sum(bin_mask * TARGET)",
        client_requirements=[
            "Client chooses fixed bins, creates one encrypted 0/1 mask per bin, and records invalid/null buckets.",
            "Server sums encrypted masks and target-conditioned masks; it does not discover bins or percentiles.",
            "Final percentages and plots/tables are produced only after client decryption.",
        ],
        server_returns=[
            "application_numeric_histograms/aggregate_summary_manifest.csv",
            "application_numeric_histograms/aggregates/*.bin",
        ],
    ),
    "home_credit_previous_application_category_counts": aggregate_job(
        label="Previous Application Category Counts",
        stage="Notebook 5.15 previous_application distributions",
        description="Encrypted value-count tables for selected previous_application categorical columns.",
        analysis="previous_application_category_counts",
        output_dir="previous_application_category_counts",
        notebook_cells="95, 98, 101, 104, 107, 110, 112, 115, 118, 120, 122, 124, 127, 129, 131, 133",
        he_operation="sum(previous_table_category_mask)",
        client_requirements=[
            "Client reads previous_application.csv locally and one-hot encodes selected categorical columns.",
            "High-cardinality columns should use top-K plus __OTHER__ before encryption.",
            "Server receives encrypted masks only; raw previous_application rows remain client-side.",
        ],
        server_returns=[
            "previous_application_category_counts/aggregate_summary_manifest.csv",
            "previous_application_category_counts/aggregates/*.bin",
        ],
    ),
    "home_credit_previous_application_target_rates": aggregate_job(
        label="Previous Application Target-Conditioned EDA",
        stage="Notebook 5.15 previous_application joined to current TARGET",
        description="Encrypted previous_application category counts conditioned on current application TARGET after a client-side SK_ID_CURR join.",
        analysis="previous_application_target_rates",
        output_dir="previous_application_target_rates",
        notebook_cells="95-133 with application_train TARGET join",
        he_operation="sum(joined_mask), sum(joined_mask * current_TARGET)",
        client_requirements=[
            "Client joins previous_application to application_train TARGET by SK_ID_CURR before encryption.",
            "Client creates masks only for previous rows with a known training TARGET.",
            "Server performs encrypted sums; it does not do encrypted joins in this prototype.",
        ],
        server_returns=[
            "previous_application_target_rates/aggregate_summary_manifest.csv",
            "previous_application_target_rates/aggregates/*.bin",
        ],
    ),
    "home_credit_selected_correlation_stats": aggregate_job(
        label="Selected Numeric Correlation Stats",
        stage="Notebook 6 correlation heatmap replacement",
        description="Encrypted selected-pair sums needed for client-side Pearson correlation tables.",
        analysis="selected_correlation_stats",
        output_dir="selected_correlation_stats",
        notebook_cells="135",
        he_operation="sum(valid), sum(valid*x), sum(valid*y), sum(x*y), sum(x*x), sum(y*y)",
        client_requirements=[
            "Client chooses a small set of numeric pairs and creates valid-pair masks before encryption.",
            "Client fills missing numeric pair values with zero and separately masks valid pairs.",
            "Server computes encrypted pairwise sums; division, square root, and final correlation happen after decryption.",
        ],
        server_returns=[
            "selected_correlation_stats/aggregate_summary_manifest.csv",
            "selected_correlation_stats/aggregates/*.bin",
        ],
    ),
    "home_credit_linear_score_demo": {
        "label": "Linear Score Demo",
        "family": "Home Credit Optional",
        "stage": "Optional encrypted inference plumbing",
        "scheme": "CKKS",
        "binary": "server_linear_score",
        "description": "Optional encrypted CKKS weighted-sum inference demo. This replaces RandomForest only for HE feasibility testing.",
        "notebook_cells": "139, 140 alternative, not RandomForest",
        "he_operation": "sum(feature_i * plaintext_weight_i) + bias",
        "required": ["crypto_context.bin", "score_manifest.csv", "score_features/"],
        "client_requirements": [
            "RandomForest training and feature importance stay client/trusted only.",
            "Client scales numeric features and encrypts vectors for a small linear model demo.",
            "Server returns encrypted score chunks; client decrypts and optionally applies sigmoid.",
        ],
        "server_returns": ["linear_score_demo/score_summary_manifest.csv", "linear_score_demo/scores/*.bin"],
        "command": [
            "--context",
            "crypto_context.bin",
            "--manifest",
            "score_manifest.csv",
            "--input-dir",
            "score_features",
            "--output-dir",
            "output/linear_score_demo",
        ],
    },
}


LEGACY_JOB_ALIASES = {
    "home_credit_numeric_summary": "home_credit_application_numeric_summary",
    "home_credit_category_eda": "home_credit_application_default_rates",
    "home_credit_bucket_eda": "home_credit_application_numeric_histograms",
    "home_credit_domain_ratio_eda": "home_credit_application_numeric_histograms",
    "home_credit_linear_score": "home_credit_linear_score_demo",
}

for legacy_job_type, canonical in LEGACY_JOB_ALIASES.items():
    legacy_cfg = deepcopy(JOB_TYPES[canonical])
    legacy_cfg["label"] = f"Legacy alias for {JOB_TYPES[canonical]['label']}"
    legacy_cfg["hidden"] = True
    JOB_TYPES[legacy_job_type] = legacy_cfg

JOB_TYPES["home_credit_numeric_summary"]["server_returns"] = [
    "numeric_summary/summary_manifest.csv",
    "numeric_summary/sums/*.bin",
]
JOB_TYPES["home_credit_numeric_summary"]["command"] = [
    "--context",
    "crypto_context.bin",
    "--eval-sum-keys",
    "eval_sum_keys.bin",
    "--manifest",
    "column_manifest.csv",
    "--input-dir",
    "columns",
    "--output-dir",
    "output/numeric_summary",
]
JOB_TYPES["home_credit_category_eda"]["server_returns"] = [
    "category_eda/aggregate_summary_manifest.csv",
    "category_eda/aggregates/*.bin",
]
JOB_TYPES["home_credit_category_eda"]["command"][-1] = "literal:category"
JOB_TYPES["home_credit_category_eda"]["command"][-3] = "output/category_eda"
JOB_TYPES["home_credit_bucket_eda"]["server_returns"] = [
    "bucket_eda/aggregate_summary_manifest.csv",
    "bucket_eda/aggregates/*.bin",
]
JOB_TYPES["home_credit_bucket_eda"]["command"][-1] = "literal:bucket"
JOB_TYPES["home_credit_bucket_eda"]["command"][-3] = "output/bucket_eda"
JOB_TYPES["home_credit_domain_ratio_eda"]["server_returns"] = [
    "ratio_eda/aggregate_summary_manifest.csv",
    "ratio_eda/aggregates/*.bin",
]
JOB_TYPES["home_credit_domain_ratio_eda"]["command"][-1] = "literal:ratio"
JOB_TYPES["home_credit_domain_ratio_eda"]["command"][-3] = "output/ratio_eda"
JOB_TYPES["home_credit_linear_score"]["server_returns"] = [
    "linear_score/score_summary_manifest.csv",
    "linear_score/scores/*.bin",
]
JOB_TYPES["home_credit_linear_score"]["command"][-1] = "output/linear_score"


ANALYSIS_TO_JOB_TYPE = {
    "missing_data": "home_credit_missing_data",
    "target_balance": "home_credit_target_balance",
    "application_category_counts": "home_credit_application_category_counts",
    "application_default_rates": "home_credit_application_default_rates",
    "application_numeric_histograms": "home_credit_application_numeric_histograms",
    "previous_application_category_counts": "home_credit_previous_application_category_counts",
    "previous_application_target_rates": "home_credit_previous_application_target_rates",
    "selected_correlation_stats": "home_credit_selected_correlation_stats",
    "category": "home_credit_category_eda",
    "bucket": "home_credit_bucket_eda",
    "ratio": "home_credit_domain_ratio_eda",
}


def canonical_job_type(job_type: str) -> str:
    normalized = job_type.strip()
    return LEGACY_JOB_ALIASES.get(normalized, normalized)


def visible_job_types() -> dict[str, dict[str, Any]]:
    return {key: value for key, value in JOB_TYPES.items() if not value.get("hidden")}


def public_job_types() -> dict[str, dict[str, Any]]:
    return {
        key: {
            "label": value["label"],
            "family": value.get("family", ""),
            "stage": value.get("stage", ""),
            "scheme": value["scheme"],
            "description": value["description"],
            "notebook_cells": value.get("notebook_cells", ""),
            "he_operation": value.get("he_operation", ""),
            "required": value["required"],
            "client_requirements": value.get("client_requirements", []),
            "server_returns": value.get("server_returns", []),
            "disabled": bool(value.get("disabled")),
        }
        for key, value in visible_job_types().items()
    }
