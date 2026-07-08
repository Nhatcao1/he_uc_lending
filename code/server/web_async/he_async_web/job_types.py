"""Runnable encrypted Home Credit notebook-EDA job definitions."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def numeric_job(
    *,
    label: str,
    stage: str,
    description: str,
    output_dir: str,
    notebook_cells: str,
    client_requirements: list[str],
) -> dict[str, Any]:
    return {
        "label": label,
        "family": "Home Credit Complete EDA",
        "stage": stage,
        "scheme": "CKKS",
        "binary": "server_numeric_summary",
        "description": description,
        "notebook_cells": notebook_cells,
        "he_operation": "EvalSum(encrypted_numeric_vector)",
        "required": ["crypto_context.bin", "eval_sum_keys.bin", "column_manifest.csv", "columns/"],
        "client_requirements": client_requirements,
        "server_returns": [f"{output_dir}/summary_manifest.csv", f"{output_dir}/sums/*.bin"],
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
            f"output/{output_dir}",
        ],
    }


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


def aggregate_returns(output_dir: str) -> list[str]:
    return [f"{output_dir}/aggregate_summary_manifest.csv", f"{output_dir}/aggregates/*.bin"]


def token_join_job(
    *,
    label: str,
    stage: str,
    description: str,
    analysis: str,
    output_dir: str,
    token_dir: str,
    client_requirements: list[str],
    match_mask: str = "",
) -> dict[str, Any]:
    required = [
        "crypto_context.bin",
        "eval_sum_keys.bin",
        "eval_mult_keys.bin",
        "aggregate_manifest.csv",
        "vectors/",
    ]
    command = [
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
    ]
    if match_mask:
        required.append(match_mask)
        command.extend(["--match-mask", match_mask])
    else:
        required.extend([f"{token_dir}/left_tokens.csv", f"{token_dir}/right_tokens.csv"])
        command.extend(["--left-tokens", f"{token_dir}/left_tokens.csv", "--right-tokens", f"{token_dir}/right_tokens.csv"])
    command.extend(["--output-dir", f"output/{output_dir}", "--analysis-filter", f"literal:{analysis}"])
    return {
        "label": label,
        "family": "Home Credit Manual Feature Engineering",
        "stage": stage,
        "scheme": "CKKS + protected join tokens",
        "binary": "server_home_credit_token_join_aggregate",
        "description": description,
        "notebook_cells": "manual feature engineering notebooks: groupby/merge pattern",
        "he_operation": "plaintext token match mask * encrypted category mask, then EvalSum",
        "required": required,
        "client_requirements": client_requirements,
        "server_returns": aggregate_returns(output_dir),
        "command": command,
    }


def fhew_match_job() -> dict[str, Any]:
    return {
        "label": "Manual FE: FHEW Encrypted Join Match",
        "family": "Home Credit Manual Feature Engineering",
        "stage": "Manual FE encrypted equality benchmark",
        "scheme": "BinFHE/FHEW",
        "binary": "server_home_credit_fhew_match",
        "description": (
            "Tiny encrypted equality comparison for application_train vs previous_application SK_ID_CURR tokens. "
            "This is for timing/feasibility comparison with HMAC and PSI-ready join paths."
        ),
        "notebook_cells": "manual feature engineering notebooks: merge/join pattern",
        "he_operation": "XNOR encrypted ID bits, AND-reduce equality, OR-reduce matches",
        "required": [
            "join/fhew/cryptoContext.bin",
            "join/fhew/refreshKey.bin",
            "join/fhew/ksKey.bin",
            "join/fhew/fhew_match_manifest.csv",
            "join/fhew/left_bits/",
            "join/fhew/right_bits/",
        ],
        "client_requirements": [
            "Client prepares HMAC-derived token-prefix integers locally, then encrypts each bit with BinFHE/FHEW.",
            "Upload contains encrypted bit ciphertexts and FHEW bootstrapping keys, not raw IDs or HMAC tokens.",
            "Keep this capped. Pairwise gates scale as left_rows * right_rows * id_bits.",
        ],
        "server_returns": [
            "join_fhew_prev_contract_status/fhew_match_summary_manifest.csv",
            "join_fhew_prev_contract_status/matches/*.bin",
        ],
        "command": [
            "--context",
            "join/fhew/cryptoContext.bin",
            "--refresh-key",
            "join/fhew/refreshKey.bin",
            "--switch-key",
            "join/fhew/ksKey.bin",
            "--manifest",
            "join/fhew/fhew_match_manifest.csv",
            "--input-dir",
            "join/fhew",
            "--output-dir",
            "output/join_fhew_prev_contract_status",
        ],
    }


COMMON_CATEGORY_CLIENT_REQS = [
    "Client normalizes strings, applies __MISSING__, and uses top-K plus __OTHER__ where needed.",
    "Client one-hot encodes category labels into encrypted 0/1 masks.",
    "Server sees chosen label metadata and encrypted masks, not raw category values.",
]

COMMON_TARGET_CLIENT_REQS = [
    "Client prepares category masks and the TARGET default mask before encryption.",
    "Server returns encrypted category counts and encrypted default counts.",
    "Default rates are computed only after the trusted client decrypts the count table.",
]

COMMON_PREVIOUS_CLIENT_REQS = [
    "Client reads previous_application.csv locally and one-hot encodes the selected column.",
    "High-cardinality columns use top-K plus __OTHER__ before encryption.",
    "Server receives encrypted masks only; raw previous_application rows remain client-side.",
]


JOB_TYPES: dict[str, dict[str, Any]] = {
    "home_credit_missing_data": aggregate_job(
        label="4.x Missing Data Checks",
        stage="Notebook 4.x missing-value checks",
        description="Encrypted missing-count table for selected application_train columns. More source tables require client prep extensions.",
        analysis="missing_data",
        output_dir="missing_data",
        notebook_cells="29, 31, 33, 35, 37, 39, 41",
        he_operation="sum(is_null_column_mask)",
        client_requirements=[
            "Client maps raw null/blank/nan values to one encrypted 0/1 missing mask per selected column.",
            "Current code covers selected application_train columns; the notebook's other CSV checks are documented as prep extensions.",
            "Server only sums encrypted missing masks; percentages are computed after client decrypts counts.",
        ],
        server_returns=aggregate_returns("missing_data"),
    ),
    "home_credit_app_dist_amt_credit": numeric_job(
        label="5.1 Distribution of AMT_CREDIT",
        stage="Notebook 5.1",
        description="Encrypted sum support for the AMT_CREDIT distribution table.",
        output_dir="app_dist_amt_credit",
        notebook_cells="44",
        client_requirements=[
            "Client cleans AMT_CREDIT, encrypts the numeric vector, and records row/valid-count metadata.",
            "Server computes encrypted sum; mean and chart-ready table are client-side after decryption.",
        ],
    ),
    "home_credit_app_dist_amt_income_total": numeric_job(
        label="5.2 Distribution of AMT_INCOME_TOTAL",
        stage="Notebook 5.2",
        description="Encrypted sum support for the AMT_INCOME_TOTAL distribution table.",
        output_dir="app_dist_amt_income_total",
        notebook_cells="46",
        client_requirements=[
            "Client cleans AMT_INCOME_TOTAL, encrypts the numeric vector, and records row/valid-count metadata.",
            "Server computes encrypted sum; mean and chart-ready table are client-side after decryption.",
        ],
    ),
    "home_credit_app_dist_amt_goods_price": numeric_job(
        label="5.3 Distribution of AMT_GOODS_PRICE",
        stage="Notebook 5.3",
        description="Encrypted sum support for the AMT_GOODS_PRICE distribution table.",
        output_dir="app_dist_amt_goods_price",
        notebook_cells="48",
        client_requirements=[
            "Client cleans AMT_GOODS_PRICE, encrypts the numeric vector, and records row/valid-count metadata.",
            "Server computes encrypted sum; mean and chart-ready table are client-side after decryption.",
        ],
    ),
    "home_credit_app_target_balance": aggregate_job(
        label="5.5 Target Balance",
        stage="Notebook 5.5",
        description="Encrypted count support for repaid/defaulted loan class balance.",
        analysis="target_balance",
        output_dir="app_target_balance",
        notebook_cells="52, 53",
        he_operation="sum(target_default_mask), sum(target_repaid_mask), sum(row_mask)",
        client_requirements=[
            "Client encodes TARGET into default, repaid, and row-count masks before encryption.",
            "Rows with missing TARGET should be excluded or represented by a documented target_missing mask.",
            "Server returns encrypted counts only; class percentages are client-side after decryption.",
        ],
        server_returns=aggregate_returns("app_target_balance"),
    ),
    "home_credit_app_selected_correlation_stats": aggregate_job(
        label="6 Pearson Correlation Support",
        stage="Notebook 6",
        description="Encrypted selected-pair sums needed for client-side Pearson correlation tables.",
        analysis="selected_correlation_stats",
        output_dir="app_selected_correlation_stats",
        notebook_cells="135",
        he_operation="sum(valid), sum(valid*x), sum(valid*y), sum(x*y), sum(x*x), sum(y*y)",
        client_requirements=[
            "Client chooses a small set of numeric pairs and creates valid-pair masks before encryption.",
            "Client fills missing numeric pair values with zero and separately masks valid pairs.",
            "Server computes encrypted pairwise sums; division, square root, and final correlation happen after decryption.",
        ],
        server_returns=aggregate_returns("app_selected_correlation_stats"),
    ),
    "home_credit_linear_score_demo": {
        "label": "7 Linear Score Demo",
        "family": "Home Credit Complete EDA",
        "stage": "Notebook 7 replacement",
        "scheme": "CKKS",
        "binary": "server_linear_score",
        "description": "Optional encrypted CKKS weighted-sum inference demo. This is a practical HE substitute for the notebook RandomForest section.",
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
    "home_credit_join_hmac_prev_contract_status": token_join_job(
        label="Manual FE: HMAC Token Join Previous Status",
        stage="Manual FE join proof",
        description="Server joins previous_application rows to the sampled application_train clients using HMAC SK_ID_CURR tokens, then sums encrypted NAME_CONTRACT_STATUS masks.",
        analysis="previous_application_token_join_hmac",
        output_dir="join_hmac_prev_contract_status",
        token_dir="join/hmac",
        client_requirements=[
            "Client creates HMAC-SHA256 join tokens for SK_ID_CURR and keeps the join secret local.",
            "Client encrypts previous_application NAME_CONTRACT_STATUS one-hot masks.",
            "Server sees only deterministic tokens and encrypted masks, then applies a token-match selection mask.",
        ],
    ),
    "home_credit_join_psi_prev_contract_status": token_join_job(
        label="Manual FE: PSI-Ready Join Previous Status",
        stage="Manual FE PSI join proof",
        description="PSI/trusted matching produces a row-aligned match mask; the server applies that plaintext mask to encrypted previous_application status vectors.",
        analysis="previous_application_token_join_psi",
        output_dir="join_psi_prev_contract_status",
        token_dir="join/psi",
        match_mask="join/psi/match_mask.csv",
        client_requirements=[
            "Client or trusted matching service runs PSI and writes matched HMAC tokens to the prepare step.",
            "Prepare converts the PSI matched-token set into row-aligned join/psi/match_mask.csv.",
            "Server receives the 0/1 mask and encrypted status masks; it does not need raw IDs or PSI token lists.",
        ],
    ),
    "home_credit_join_fhew_prev_contract_status": fhew_match_job(),
}


APPLICATION_CATEGORY_JOBS = [
    ("home_credit_app_suite_type", "5.4 Who Accompanied Client", "NAME_TYPE_SUITE", "50"),
    ("home_credit_app_loan_type", "5.6 Types of Loan", "NAME_CONTRACT_TYPE", "56"),
    ("home_credit_app_own_car_realty", "5.7 Own Car / Own Realty Flags", "FLAG_OWN_CAR, FLAG_OWN_REALTY", "59"),
    ("home_credit_app_income_type", "5.8 Income Sources", "NAME_INCOME_TYPE", "61"),
    ("home_credit_app_family_status", "5.9 Family Status", "NAME_FAMILY_STATUS", "64"),
    ("home_credit_app_occupation_type", "5.10 Occupation", "OCCUPATION_TYPE", "67"),
    ("home_credit_app_education_type", "5.11 Education", "NAME_EDUCATION_TYPE", "70"),
    ("home_credit_app_housing_type", "5.12 Housing Type", "NAME_HOUSING_TYPE", "73"),
    ("home_credit_app_organization_type", "5.13 Organization Type", "ORGANIZATION_TYPE", "76"),
]

for job_type, label, column_label, cells in APPLICATION_CATEGORY_JOBS:
    output_dir = job_type.removeprefix("home_credit_")
    JOB_TYPES[job_type] = aggregate_job(
        label=label,
        stage=label.split(" ", 1)[0],
        description=f"Encrypted value-count table for {column_label}.",
        analysis="application_category_counts",
        output_dir=output_dir,
        notebook_cells=cells,
        he_operation="sum(one_hot_category_mask)",
        client_requirements=COMMON_CATEGORY_CLIENT_REQS,
        server_returns=aggregate_returns(output_dir),
    )


APPLICATION_TARGET_JOBS = [
    ("home_credit_app_target_by_income_type", "5.14.1 Income Type by Target", "NAME_INCOME_TYPE", "80"),
    ("home_credit_app_target_by_family_status", "5.14.2 Family Status by Target", "NAME_FAMILY_STATUS", "82"),
    ("home_credit_app_target_by_occupation_type", "5.14.3 Occupation by Target", "OCCUPATION_TYPE", "84"),
    ("home_credit_app_target_by_education_type", "5.14.4 Education by Target", "NAME_EDUCATION_TYPE", "86"),
    ("home_credit_app_target_by_housing_type", "5.14.5 Housing Type by Target", "NAME_HOUSING_TYPE", "88"),
    ("home_credit_app_target_by_organization_type", "5.14.6 Organization Type by Target", "ORGANIZATION_TYPE", "90"),
    ("home_credit_app_target_by_suite_type", "5.14.7 Suite Type by Target", "NAME_TYPE_SUITE", "92"),
]

for job_type, label, column_label, cells in APPLICATION_TARGET_JOBS:
    output_dir = job_type.removeprefix("home_credit_")
    JOB_TYPES[job_type] = aggregate_job(
        label=label,
        stage=label.rsplit(" ", 2)[0],
        description=f"Encrypted count and default-count table for {column_label}.",
        analysis="application_default_rates",
        output_dir=output_dir,
        notebook_cells=cells,
        he_operation="sum(mask), sum(mask * TARGET), optional sum(mask * amount)",
        client_requirements=COMMON_TARGET_CLIENT_REQS,
        server_returns=aggregate_returns(output_dir),
    )


PREVIOUS_APPLICATION_JOBS = [
    ("home_credit_prev_contract_type", "5.15.1 Previous Contract Type", "NAME_CONTRACT_TYPE", "95"),
    ("home_credit_prev_weekday_process_start", "5.15.2 Previous Application Weekday", "WEEKDAY_APPR_PROCESS_START", "98"),
    ("home_credit_prev_cash_loan_purpose", "5.15.3 Previous Cash Loan Purpose", "NAME_CASH_LOAN_PURPOSE", "101"),
    ("home_credit_prev_contract_status", "5.15.4 Previous Contract Status", "NAME_CONTRACT_STATUS", "104"),
    ("home_credit_prev_payment_type", "5.15.5 Previous Payment Type", "NAME_PAYMENT_TYPE", "107"),
    ("home_credit_prev_reject_reason", "5.15.6 Previous Reject Reason", "CODE_REJECT_REASON", "110"),
    ("home_credit_prev_suite_type", "5.15.7 Previous Suite Type", "NAME_TYPE_SUITE", "112"),
    ("home_credit_prev_client_type", "5.15.8 Previous Client Type", "NAME_CLIENT_TYPE", "115"),
    ("home_credit_prev_goods_category", "5.15.9 Previous Goods Category", "NAME_GOODS_CATEGORY", "118"),
    ("home_credit_prev_portfolio", "5.15.10 Previous Portfolio", "NAME_PORTFOLIO", "120"),
    ("home_credit_prev_product_type", "5.15.11 Previous Product Type", "NAME_PRODUCT_TYPE", "122"),
    ("home_credit_prev_channel_type", "5.15.12 Previous Channel Type", "CHANNEL_TYPE", "124"),
    ("home_credit_prev_seller_industry", "5.15.13 Previous Seller Industry", "NAME_SELLER_INDUSTRY", "127"),
    ("home_credit_prev_yield_group", "5.15.14 Previous Yield Group", "NAME_YIELD_GROUP", "129"),
    ("home_credit_prev_product_combination", "5.15.15 Previous Product Combination", "PRODUCT_COMBINATION", "131"),
    ("home_credit_prev_insured_on_approval", "5.15.16 Previous Insured on Approval", "NFLAG_INSURED_ON_APPROVAL", "133"),
]

for job_type, label, column_label, cells in PREVIOUS_APPLICATION_JOBS:
    output_dir = job_type.removeprefix("home_credit_")
    JOB_TYPES[job_type] = aggregate_job(
        label=label,
        stage="Notebook 5.15",
        description=f"Encrypted previous_application value-count table for {column_label}.",
        analysis="previous_application_category_counts",
        output_dir=output_dir,
        notebook_cells=cells,
        he_operation="sum(previous_table_category_mask)",
        client_requirements=COMMON_PREVIOUS_CLIENT_REQS,
        server_returns=aggregate_returns(output_dir),
    )


HIDDEN_LEGACY_JOBS = {
    "home_credit_target_balance": aggregate_job(
        label="Legacy Target Balance",
        stage="Legacy broad workload",
        description="Legacy broad target-balance job.",
        analysis="target_balance",
        output_dir="target_balance",
        notebook_cells="52, 53",
        he_operation="sum(target_default_mask), sum(target_repaid_mask), sum(row_mask)",
        client_requirements=[],
        server_returns=aggregate_returns("target_balance"),
    ),
    "home_credit_application_numeric_summary": numeric_job(
        label="Legacy Application Numeric Summary",
        stage="Legacy broad workload",
        description="Legacy broad numeric summary job.",
        output_dir="application_numeric_summary",
        notebook_cells="44, 46, 48",
        client_requirements=[],
    ),
    "home_credit_application_category_counts": aggregate_job(
        label="Legacy Application Category Counts",
        stage="Legacy broad workload",
        description="Legacy broad application category-count job.",
        analysis="application_category_counts",
        output_dir="application_category_counts",
        notebook_cells="50, 56, 59, 61, 64, 67, 70, 73, 76",
        he_operation="sum(one_hot_category_mask)",
        client_requirements=[],
        server_returns=aggregate_returns("application_category_counts"),
    ),
    "home_credit_application_default_rates": aggregate_job(
        label="Legacy Application Category Default Rates",
        stage="Legacy broad workload",
        description="Legacy broad category-by-target job.",
        analysis="application_default_rates",
        output_dir="application_default_rates",
        notebook_cells="80, 82, 84, 86, 88, 90, 92",
        he_operation="sum(mask), sum(mask * TARGET), optional sum(mask * amount)",
        client_requirements=[],
        server_returns=aggregate_returns("application_default_rates"),
    ),
    "home_credit_application_numeric_histograms": aggregate_job(
        label="Legacy Application Numeric Histograms",
        stage="Legacy broad workload",
        description="Legacy broad histogram/bin job.",
        analysis="application_numeric_histograms",
        output_dir="application_numeric_histograms",
        notebook_cells="44, 46, 48",
        he_operation="sum(bin_mask), sum(bin_mask * TARGET)",
        client_requirements=[],
        server_returns=aggregate_returns("application_numeric_histograms"),
    ),
    "home_credit_previous_application_category_counts": aggregate_job(
        label="Legacy Previous Application Category Counts",
        stage="Legacy broad workload",
        description="Legacy broad previous_application category-count job.",
        analysis="previous_application_category_counts",
        output_dir="previous_application_category_counts",
        notebook_cells="95-133",
        he_operation="sum(previous_table_category_mask)",
        client_requirements=[],
        server_returns=aggregate_returns("previous_application_category_counts"),
    ),
    "home_credit_previous_application_target_rates": aggregate_job(
        label="Legacy Previous Application Target Rates",
        stage="Legacy broad workload",
        description="Legacy broad previous_application target-conditioned job.",
        analysis="previous_application_target_rates",
        output_dir="previous_application_target_rates",
        notebook_cells="95-133 with application_train TARGET join",
        he_operation="sum(joined_mask), sum(joined_mask * TARGET)",
        client_requirements=[],
        server_returns=aggregate_returns("previous_application_target_rates"),
    ),
    "home_credit_selected_correlation_stats": aggregate_job(
        label="Legacy Selected Correlation Stats",
        stage="Legacy broad workload",
        description="Legacy selected-pair correlation support job.",
        analysis="selected_correlation_stats",
        output_dir="selected_correlation_stats",
        notebook_cells="135",
        he_operation="sum(valid), sum(valid*x), sum(valid*y), sum(x*y), sum(x*x), sum(y*y)",
        client_requirements=[],
        server_returns=aggregate_returns("selected_correlation_stats"),
    ),
}

for legacy_cfg in HIDDEN_LEGACY_JOBS.values():
    legacy_cfg["hidden"] = True
JOB_TYPES.update(HIDDEN_LEGACY_JOBS)


LEGACY_JOB_ALIASES = {
    "home_credit_numeric_summary": "home_credit_application_numeric_summary",
    "home_credit_category_eda": "home_credit_application_default_rates",
    "home_credit_bucket_eda": "home_credit_application_numeric_histograms",
    "home_credit_domain_ratio_eda": "home_credit_application_numeric_histograms",
    "home_credit_linear_score": "home_credit_linear_score_demo",
}

for legacy_job_type, canonical in LEGACY_JOB_ALIASES.items():
    if legacy_job_type in JOB_TYPES:
        continue
    legacy_cfg = deepcopy(JOB_TYPES[canonical])
    legacy_cfg["label"] = f"Legacy alias for {JOB_TYPES[canonical]['label']}"
    legacy_cfg["hidden"] = True
    JOB_TYPES[legacy_job_type] = legacy_cfg

JOB_TYPES["home_credit_numeric_summary"]["server_returns"] = [
    "numeric_summary/summary_manifest.csv",
    "numeric_summary/sums/*.bin",
]
JOB_TYPES["home_credit_numeric_summary"]["command"][-1] = "output/numeric_summary"
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

NOTEBOOK_JOB_ORDER = [
    "home_credit_missing_data",
    "home_credit_app_dist_amt_credit",
    "home_credit_app_dist_amt_income_total",
    "home_credit_app_dist_amt_goods_price",
    "home_credit_app_suite_type",
    "home_credit_app_target_balance",
    "home_credit_app_loan_type",
    "home_credit_app_own_car_realty",
    "home_credit_app_income_type",
    "home_credit_app_family_status",
    "home_credit_app_occupation_type",
    "home_credit_app_education_type",
    "home_credit_app_housing_type",
    "home_credit_app_organization_type",
    "home_credit_app_target_by_income_type",
    "home_credit_app_target_by_family_status",
    "home_credit_app_target_by_occupation_type",
    "home_credit_app_target_by_education_type",
    "home_credit_app_target_by_housing_type",
    "home_credit_app_target_by_organization_type",
    "home_credit_app_target_by_suite_type",
    "home_credit_prev_contract_type",
    "home_credit_prev_weekday_process_start",
    "home_credit_prev_cash_loan_purpose",
    "home_credit_prev_contract_status",
    "home_credit_prev_payment_type",
    "home_credit_prev_reject_reason",
    "home_credit_prev_suite_type",
    "home_credit_prev_client_type",
    "home_credit_prev_goods_category",
    "home_credit_prev_portfolio",
    "home_credit_prev_product_type",
    "home_credit_prev_channel_type",
    "home_credit_prev_seller_industry",
    "home_credit_prev_yield_group",
    "home_credit_prev_product_combination",
    "home_credit_prev_insured_on_approval",
    "home_credit_app_selected_correlation_stats",
    "home_credit_linear_score_demo",
    "home_credit_join_hmac_prev_contract_status",
    "home_credit_join_psi_prev_contract_status",
    "home_credit_join_fhew_prev_contract_status",
]
JOB_TYPES = {
    **{job_type: JOB_TYPES[job_type] for job_type in NOTEBOOK_JOB_ORDER if job_type in JOB_TYPES},
    **{job_type: cfg for job_type, cfg in JOB_TYPES.items() if job_type not in NOTEBOOK_JOB_ORDER},
}


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
