#!/usr/bin/env python3
"""Build applicant-level credit-risk features from all Home Credit tables.

This trusted-client step follows the feature-engineering families used by the
Home Credit notebooks. Raw identifiers and source rows never leave the client.
"""

from __future__ import annotations

import argparse
from pathlib import Path


APPLICATION_NUMERIC = [
    "AMT_CREDIT",
    "AMT_INCOME_TOTAL",
    "AMT_ANNUITY",
    "AMT_GOODS_PRICE",
    "EXT_SOURCE_1",
    "EXT_SOURCE_2",
    "EXT_SOURCE_3",
    "DAYS_BIRTH",
    "DAYS_EMPLOYED",
    "DAYS_REGISTRATION",
    "DAYS_ID_PUBLISH",
    "DAYS_LAST_PHONE_CHANGE",
    "CNT_CHILDREN",
    "CNT_FAM_MEMBERS",
    "OWN_CAR_AGE",
    "REGION_RATING_CLIENT",
    "REGION_RATING_CLIENT_W_CITY",
    "HOUR_APPR_PROCESS_START",
    "OBS_30_CNT_SOCIAL_CIRCLE",
    "DEF_30_CNT_SOCIAL_CIRCLE",
    "AMT_REQ_CREDIT_BUREAU_YEAR",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Home Credit applicant-level scoring features.")
    parser.add_argument("--data-dir", type=Path, default=Path("data/home_credit"))
    parser.add_argument("--application", default="application_train.csv")
    parser.add_argument("--output", type=Path, default=Path("prepared_payloads/home_credit_scoring/features.csv"))
    parser.add_argument("--row-limit", type=int, default=0, help="Application row limit; 0 means all rows.")
    parser.add_argument("--related-row-limit", type=int, default=0, help="Per-related-table row limit; 0 means all rows.")
    parser.add_argument("--require-all-tables", action="store_true")
    return parser.parse_args()


def read_table(pd, path: Path, columns: list[str] | None, limit: int):  # type: ignore[no-untyped-def]
    if not path.is_file():
        return None
    header = pd.read_csv(path, nrows=0).columns
    selected = [column for column in (columns or list(header)) if column in header]
    return pd.read_csv(path, usecols=selected, nrows=limit or None, low_memory=False)


def safe_divide(np, numerator, denominator):  # type: ignore[no-untyped-def]
    result = numerator / denominator.replace(0, np.nan)
    return result.replace([np.inf, -np.inf], np.nan)


def add_application_features(pd, np, frame):  # type: ignore[no-untyped-def]
    output = frame[["SK_ID_CURR"] + (["TARGET"] if "TARGET" in frame else [])].copy()
    for column in frame.select_dtypes(include="number").columns:
        if column not in {"SK_ID_CURR", "TARGET"}:
            values = pd.to_numeric(frame[column], errors="coerce")
            if column == "DAYS_EMPLOYED":
                values = values.mask(values == 365243)
            output[f"app_raw_{column.lower()}"] = values
    for column in APPLICATION_NUMERIC:
        if column in frame:
            values = pd.to_numeric(frame[column], errors="coerce")
            if column == "DAYS_EMPLOYED":
                values = values.mask(values == 365243)
            output[f"app_{column.lower()}"] = values

    if "DAYS_BIRTH" in frame:
        output["app_age_years"] = pd.to_numeric(frame["DAYS_BIRTH"], errors="coerce").abs() / 365.25
    if "DAYS_EMPLOYED" in frame:
        employed = pd.to_numeric(frame["DAYS_EMPLOYED"], errors="coerce")
        output["app_days_employed_anom"] = (employed == 365243).astype(float)
        output["app_days_employed_clean"] = employed.mask(employed == 365243)

    pairs = {
        "app_credit_income_ratio": ("AMT_CREDIT", "AMT_INCOME_TOTAL"),
        "app_annuity_income_ratio": ("AMT_ANNUITY", "AMT_INCOME_TOTAL"),
        "app_credit_term_ratio": ("AMT_ANNUITY", "AMT_CREDIT"),
        "app_goods_credit_ratio": ("AMT_GOODS_PRICE", "AMT_CREDIT"),
        "app_employed_birth_ratio": ("DAYS_EMPLOYED", "DAYS_BIRTH"),
        "app_children_family_ratio": ("CNT_CHILDREN", "CNT_FAM_MEMBERS"),
    }
    for name, (numerator, denominator) in pairs.items():
        if numerator in frame and denominator in frame:
            output[name] = safe_divide(
                np,
                pd.to_numeric(frame[numerator], errors="coerce"),
                pd.to_numeric(frame[denominator], errors="coerce"),
            )

    categorical_flags = {
        "app_contract_revolving": ("NAME_CONTRACT_TYPE", "Revolving loans"),
        "app_owns_car": ("FLAG_OWN_CAR", "Y"),
        "app_owns_realty": ("FLAG_OWN_REALTY", "Y"),
        "app_higher_education": ("NAME_EDUCATION_TYPE", "Higher education"),
        "app_working_income": ("NAME_INCOME_TYPE", "Working"),
        "app_commercial_income": ("NAME_INCOME_TYPE", "Commercial associate"),
        "app_pensioner_income": ("NAME_INCOME_TYPE", "Pensioner"),
        "app_married": ("NAME_FAMILY_STATUS", "Married"),
        "app_house_owner": ("NAME_HOUSING_TYPE", "House / apartment"),
    }
    for name, (column, value) in categorical_flags.items():
        if column in frame:
            output[name] = (frame[column].fillna("") == value).astype(float)
    for column in frame.select_dtypes(include="object").columns:
        if column == "SK_ID_CURR":
            continue
        normalized = frame[column].fillna("__MISSING__").astype(str)
        categories = set(normalized.value_counts().head(32).index)
        bucketed = normalized.where(normalized.isin(categories), "__OTHER__")
        dummies = pd.get_dummies(bucketed, prefix=f"app_cat_{column.lower()}", dtype=float)
        output = pd.concat([output, dummies], axis=1)

    polynomial_sources = ["EXT_SOURCE_1", "EXT_SOURCE_2", "EXT_SOURCE_3", "DAYS_BIRTH"]
    available_poly = [column for column in polynomial_sources if column in frame]
    for left_index, left in enumerate(available_poly):
        left_values = pd.to_numeric(frame[left], errors="coerce")
        output[f"app_poly_{left.lower()}_pow2"] = left_values**2
        output[f"app_poly_{left.lower()}_pow3"] = left_values**3
        for right in available_poly[left_index + 1 :]:
            right_values = pd.to_numeric(frame[right], errors="coerce")
            output[f"app_poly_{left.lower()}_x_{right.lower()}"] = left_values * right_values
            output[f"app_poly_{left.lower()}2_x_{right.lower()}"] = (left_values**2) * right_values
            output[f"app_poly_{left.lower()}_x_{right.lower()}2"] = left_values * (right_values**2)
    return output


def named_group(frame, group: str, definitions: dict[str, tuple[str, str]]):  # type: ignore[no-untyped-def]
    available = {
        name: (source, operation)
        for name, (source, operation) in definitions.items()
        if source in frame.columns
    }
    if not available:
        return None
    return frame.groupby(group).agg(**available).reset_index()


def notebook_numeric_aggregates(frame, group: str, prefix: str, excluded: set[str]):  # type: ignore[no-untyped-def]
    numeric = [
        column
        for column in frame.select_dtypes(include="number").columns
        if column != group and column not in excluded
    ]
    if not numeric:
        return None
    grouped = frame.groupby(group)[numeric].agg(["count", "mean", "max", "min", "sum"])
    grouped.columns = [f"{prefix}_{column.lower()}_{stat}" for column, stat in grouped.columns]
    return grouped.reset_index()


def notebook_categorical_aggregates(pd, frame, group: str, prefix: str):  # type: ignore[no-untyped-def]
    pieces = []
    for column in frame.select_dtypes(include="object").columns:
        if column == group:
            continue
        normalized = frame[column].fillna("__MISSING__").astype(str)
        categories = set(normalized.value_counts().head(32).index)
        bucketed = normalized.where(normalized.isin(categories), "__OTHER__")
        dummies = pd.get_dummies(bucketed, prefix=f"{prefix}_{column.lower()}", dtype=float)
        dummies[group] = frame[group].values
        grouped = dummies.groupby(group).agg(["sum", "mean"])
        grouped.columns = [f"{name}_{stat}" for name, stat in grouped.columns]
        pieces.append(grouped)
    if not pieces:
        return None
    return pd.concat(pieces, axis=1).reset_index()


def merge_candidate_aggregates(features, grouped):  # type: ignore[no-untyped-def]
    if grouped is None:
        return features
    duplicate_columns = [column for column in grouped if column != "SK_ID_CURR" and column in features]
    return features.merge(grouped.drop(columns=duplicate_columns), on="SK_ID_CURR", how="left")


def add_bureau_features(pd, np, features, data_dir: Path, limit: int):  # type: ignore[no-untyped-def]
    columns = [
        "SK_ID_CURR",
        "SK_ID_BUREAU",
        "CREDIT_ACTIVE",
        "DAYS_CREDIT",
        "CREDIT_DAY_OVERDUE",
        "AMT_CREDIT_MAX_OVERDUE",
        "CNT_CREDIT_PROLONG",
        "AMT_CREDIT_SUM",
        "AMT_CREDIT_SUM_DEBT",
        "AMT_CREDIT_SUM_OVERDUE",
        "AMT_ANNUITY",
    ]
    bureau = read_table(pd, data_dir / "bureau.csv", None, limit)
    if bureau is None:
        return features, None
    bureau["bureau_active_flag"] = (bureau.get("CREDIT_ACTIVE", "") == "Active").astype(float)
    bureau["bureau_closed_flag"] = (bureau.get("CREDIT_ACTIVE", "") == "Closed").astype(float)
    bureau["bureau_debt_credit_ratio"] = safe_divide(
        np,
        pd.to_numeric(bureau.get("AMT_CREDIT_SUM_DEBT"), errors="coerce"),
        pd.to_numeric(bureau.get("AMT_CREDIT_SUM"), errors="coerce"),
    )
    definitions = {
        "bureau_loan_count": ("SK_ID_BUREAU", "count"),
        "bureau_active_count": ("bureau_active_flag", "sum"),
        "bureau_closed_count": ("bureau_closed_flag", "sum"),
        "bureau_days_credit_mean": ("DAYS_CREDIT", "mean"),
        "bureau_days_credit_min": ("DAYS_CREDIT", "min"),
        "bureau_credit_day_overdue_max": ("CREDIT_DAY_OVERDUE", "max"),
        "bureau_credit_max_overdue_mean": ("AMT_CREDIT_MAX_OVERDUE", "mean"),
        "bureau_credit_prolong_sum": ("CNT_CREDIT_PROLONG", "sum"),
        "bureau_credit_sum_total": ("AMT_CREDIT_SUM", "sum"),
        "bureau_credit_sum_mean": ("AMT_CREDIT_SUM", "mean"),
        "bureau_debt_sum": ("AMT_CREDIT_SUM_DEBT", "sum"),
        "bureau_overdue_sum": ("AMT_CREDIT_SUM_OVERDUE", "sum"),
        "bureau_annuity_sum": ("AMT_ANNUITY", "sum"),
        "bureau_debt_credit_ratio_mean": ("bureau_debt_credit_ratio", "mean"),
    }
    grouped = named_group(bureau, "SK_ID_CURR", definitions)
    features = features.merge(grouped, on="SK_ID_CURR", how="left")
    candidates = notebook_numeric_aggregates(
        bureau,
        "SK_ID_CURR",
        "nb_bureau",
        {"SK_ID_BUREAU"},
    )
    features = merge_candidate_aggregates(features, candidates)
    categories = notebook_categorical_aggregates(pd, bureau, "SK_ID_CURR", "nb_bureau_cat")
    return merge_candidate_aggregates(features, categories), bureau


def add_bureau_balance_features(pd, features, bureau, data_dir: Path, limit: int):  # type: ignore[no-untyped-def]
    balance = read_table(pd, data_dir / "bureau_balance.csv", ["SK_ID_BUREAU", "MONTHS_BALANCE", "STATUS"], limit)
    if balance is None or bureau is None:
        return features
    mapping = bureau[["SK_ID_BUREAU", "SK_ID_CURR"]].drop_duplicates()
    balance = balance.merge(mapping, on="SK_ID_BUREAU", how="inner")
    balance["bb_delinquent"] = balance["STATUS"].isin(["1", "2", "3", "4", "5"]).astype(float)
    balance["bb_severe_delinquent"] = balance["STATUS"].isin(["3", "4", "5"]).astype(float)
    balance["bb_closed"] = (balance["STATUS"] == "C").astype(float)
    grouped = named_group(
        balance,
        "SK_ID_CURR",
        {
            "bureau_balance_month_count": ("MONTHS_BALANCE", "count"),
            "bureau_balance_oldest_month": ("MONTHS_BALANCE", "min"),
            "bureau_balance_latest_month": ("MONTHS_BALANCE", "max"),
            "bureau_balance_delinquent_count": ("bb_delinquent", "sum"),
            "bureau_balance_severe_delinquent_count": ("bb_severe_delinquent", "sum"),
            "bureau_balance_closed_count": ("bb_closed", "sum"),
        },
    )
    features = features.merge(grouped, on="SK_ID_CURR", how="left")
    candidates = notebook_numeric_aggregates(
        balance,
        "SK_ID_CURR",
        "nb_bureau_balance",
        {"SK_ID_BUREAU"},
    )
    features = merge_candidate_aggregates(features, candidates)
    categories = notebook_categorical_aggregates(pd, balance, "SK_ID_CURR", "nb_bureau_balance_cat")
    return merge_candidate_aggregates(features, categories)


def add_previous_features(pd, np, features, data_dir: Path, limit: int):  # type: ignore[no-untyped-def]
    columns = [
        "SK_ID_CURR",
        "SK_ID_PREV",
        "NAME_CONTRACT_STATUS",
        "AMT_ANNUITY",
        "AMT_APPLICATION",
        "AMT_CREDIT",
        "AMT_DOWN_PAYMENT",
        "AMT_GOODS_PRICE",
        "RATE_DOWN_PAYMENT",
        "DAYS_DECISION",
        "CNT_PAYMENT",
    ]
    previous = read_table(pd, data_dir / "previous_application.csv", None, limit)
    if previous is None:
        return features
    previous["prev_approved"] = (previous["NAME_CONTRACT_STATUS"] == "Approved").astype(float)
    previous["prev_refused"] = (previous["NAME_CONTRACT_STATUS"] == "Refused").astype(float)
    previous["prev_canceled"] = (previous["NAME_CONTRACT_STATUS"] == "Canceled").astype(float)
    previous["prev_application_credit_ratio"] = safe_divide(
        np,
        pd.to_numeric(previous.get("AMT_APPLICATION"), errors="coerce"),
        pd.to_numeric(previous.get("AMT_CREDIT"), errors="coerce"),
    )
    grouped = named_group(
        previous,
        "SK_ID_CURR",
        {
            "previous_application_count": ("SK_ID_PREV", "count"),
            "previous_approved_count": ("prev_approved", "sum"),
            "previous_refused_count": ("prev_refused", "sum"),
            "previous_canceled_count": ("prev_canceled", "sum"),
            "previous_credit_sum": ("AMT_CREDIT", "sum"),
            "previous_credit_mean": ("AMT_CREDIT", "mean"),
            "previous_application_sum": ("AMT_APPLICATION", "sum"),
            "previous_annuity_mean": ("AMT_ANNUITY", "mean"),
            "previous_down_payment_sum": ("AMT_DOWN_PAYMENT", "sum"),
            "previous_goods_price_mean": ("AMT_GOODS_PRICE", "mean"),
            "previous_rate_down_payment_mean": ("RATE_DOWN_PAYMENT", "mean"),
            "previous_days_decision_mean": ("DAYS_DECISION", "mean"),
            "previous_days_decision_min": ("DAYS_DECISION", "min"),
            "previous_cnt_payment_mean": ("CNT_PAYMENT", "mean"),
            "previous_application_credit_ratio_mean": ("prev_application_credit_ratio", "mean"),
        },
    )
    features = features.merge(grouped, on="SK_ID_CURR", how="left")
    candidates = notebook_numeric_aggregates(previous, "SK_ID_CURR", "nb_previous", {"SK_ID_PREV"})
    features = merge_candidate_aggregates(features, candidates)
    categories = notebook_categorical_aggregates(pd, previous, "SK_ID_CURR", "nb_previous_cat")
    return merge_candidate_aggregates(features, categories)


def add_pos_features(pd, features, data_dir: Path, limit: int):  # type: ignore[no-untyped-def]
    pos = read_table(pd, data_dir / "POS_CASH_balance.csv", None, limit)
    if pos is None:
        return features
    grouped = named_group(
        pos,
        "SK_ID_CURR",
        {
            "pos_record_count": ("SK_ID_PREV", "count"),
            "pos_contract_count": ("SK_ID_PREV", "nunique"),
            "pos_months_balance_min": ("MONTHS_BALANCE", "min"),
            "pos_instalment_mean": ("CNT_INSTALMENT", "mean"),
            "pos_instalment_future_mean": ("CNT_INSTALMENT_FUTURE", "mean"),
            "pos_dpd_mean": ("SK_DPD", "mean"),
            "pos_dpd_max": ("SK_DPD", "max"),
            "pos_dpd_def_max": ("SK_DPD_DEF", "max"),
        },
    )
    features = features.merge(grouped, on="SK_ID_CURR", how="left")
    candidates = notebook_numeric_aggregates(pos, "SK_ID_CURR", "nb_pos", {"SK_ID_PREV"})
    features = merge_candidate_aggregates(features, candidates)
    categories = notebook_categorical_aggregates(pd, pos, "SK_ID_CURR", "nb_pos_cat")
    return merge_candidate_aggregates(features, categories)


def add_credit_card_features(pd, np, features, data_dir: Path, limit: int):  # type: ignore[no-untyped-def]
    columns = [
        "SK_ID_CURR",
        "SK_ID_PREV",
        "MONTHS_BALANCE",
        "AMT_BALANCE",
        "AMT_CREDIT_LIMIT_ACTUAL",
        "AMT_DRAWINGS_CURRENT",
        "AMT_PAYMENT_CURRENT",
        "AMT_PAYMENT_TOTAL_CURRENT",
        "AMT_TOTAL_RECEIVABLE",
        "CNT_DRAWINGS_CURRENT",
        "SK_DPD",
        "SK_DPD_DEF",
    ]
    credit = read_table(pd, data_dir / "credit_card_balance.csv", None, limit)
    if credit is None:
        return features
    credit["cc_utilization"] = safe_divide(
        np,
        pd.to_numeric(credit.get("AMT_BALANCE"), errors="coerce"),
        pd.to_numeric(credit.get("AMT_CREDIT_LIMIT_ACTUAL"), errors="coerce"),
    )
    grouped = named_group(
        credit,
        "SK_ID_CURR",
        {
            "cc_contract_count": ("SK_ID_PREV", "nunique"),
            "cc_balance_mean": ("AMT_BALANCE", "mean"),
            "cc_balance_max": ("AMT_BALANCE", "max"),
            "cc_credit_limit_mean": ("AMT_CREDIT_LIMIT_ACTUAL", "mean"),
            "cc_drawings_sum": ("AMT_DRAWINGS_CURRENT", "sum"),
            "cc_payment_sum": ("AMT_PAYMENT_TOTAL_CURRENT", "sum"),
            "cc_receivable_mean": ("AMT_TOTAL_RECEIVABLE", "mean"),
            "cc_drawing_count_sum": ("CNT_DRAWINGS_CURRENT", "sum"),
            "cc_dpd_max": ("SK_DPD", "max"),
            "cc_dpd_def_max": ("SK_DPD_DEF", "max"),
            "cc_utilization_mean": ("cc_utilization", "mean"),
            "cc_utilization_max": ("cc_utilization", "max"),
        },
    )
    features = features.merge(grouped, on="SK_ID_CURR", how="left")
    candidates = notebook_numeric_aggregates(credit, "SK_ID_CURR", "nb_credit_card", {"SK_ID_PREV"})
    features = merge_candidate_aggregates(features, candidates)
    categories = notebook_categorical_aggregates(pd, credit, "SK_ID_CURR", "nb_credit_card_cat")
    return merge_candidate_aggregates(features, categories)


def add_installment_features(pd, np, features, data_dir: Path, limit: int):  # type: ignore[no-untyped-def]
    columns = [
        "SK_ID_CURR",
        "SK_ID_PREV",
        "NUM_INSTALMENT_NUMBER",
        "DAYS_INSTALMENT",
        "DAYS_ENTRY_PAYMENT",
        "AMT_INSTALMENT",
        "AMT_PAYMENT",
    ]
    installments = read_table(pd, data_dir / "installments_payments.csv", None, limit)
    if installments is None:
        return features
    installments["inst_late_days"] = (
        pd.to_numeric(installments["DAYS_ENTRY_PAYMENT"], errors="coerce")
        - pd.to_numeric(installments["DAYS_INSTALMENT"], errors="coerce")
    ).clip(lower=0)
    installments["inst_payment_ratio"] = safe_divide(
        np,
        pd.to_numeric(installments["AMT_PAYMENT"], errors="coerce"),
        pd.to_numeric(installments["AMT_INSTALMENT"], errors="coerce"),
    )
    installments["inst_underpayment"] = (
        pd.to_numeric(installments["AMT_INSTALMENT"], errors="coerce")
        - pd.to_numeric(installments["AMT_PAYMENT"], errors="coerce")
    ).clip(lower=0)
    grouped = named_group(
        installments,
        "SK_ID_CURR",
        {
            "installment_record_count": ("NUM_INSTALMENT_NUMBER", "count"),
            "installment_contract_count": ("SK_ID_PREV", "nunique"),
            "installment_amount_sum": ("AMT_INSTALMENT", "sum"),
            "installment_payment_sum": ("AMT_PAYMENT", "sum"),
            "installment_payment_mean": ("AMT_PAYMENT", "mean"),
            "installment_late_days_mean": ("inst_late_days", "mean"),
            "installment_late_days_max": ("inst_late_days", "max"),
            "installment_payment_ratio_mean": ("inst_payment_ratio", "mean"),
            "installment_underpayment_sum": ("inst_underpayment", "sum"),
        },
    )
    features = features.merge(grouped, on="SK_ID_CURR", how="left")
    candidates = notebook_numeric_aggregates(
        installments,
        "SK_ID_CURR",
        "nb_installments",
        {"SK_ID_PREV"},
    )
    features = merge_candidate_aggregates(features, candidates)
    categories = notebook_categorical_aggregates(pd, installments, "SK_ID_CURR", "nb_installments_cat")
    return merge_candidate_aggregates(features, categories)


def main() -> None:
    args = parse_args()
    try:
        import numpy as np
        import pandas as pd
    except ImportError as exc:
        raise SystemExit("Install client dependencies: python -m pip install pandas numpy") from exc

    required = [
        args.application,
        "bureau.csv",
        "bureau_balance.csv",
        "previous_application.csv",
        "POS_CASH_balance.csv",
        "credit_card_balance.csv",
        "installments_payments.csv",
    ]
    missing = [name for name in required if not (args.data_dir / name).is_file()]
    if args.require_all_tables and missing:
        raise FileNotFoundError(f"missing Home Credit tables: {', '.join(missing)}")

    application = read_table(pd, args.data_dir / args.application, None, args.row_limit)
    if application is None or "SK_ID_CURR" not in application:
        raise FileNotFoundError(f"invalid application table: {args.data_dir / args.application}")
    features = add_application_features(pd, np, application)
    features, bureau = add_bureau_features(pd, np, features, args.data_dir, args.related_row_limit)
    features = add_bureau_balance_features(pd, features, bureau, args.data_dir, args.related_row_limit)
    features = add_previous_features(pd, np, features, args.data_dir, args.related_row_limit)
    features = add_pos_features(pd, features, args.data_dir, args.related_row_limit)
    features = add_credit_card_features(pd, np, features, args.data_dir, args.related_row_limit)
    features = add_installment_features(pd, np, features, args.data_dir, args.related_row_limit)
    features = features.replace([np.inf, -np.inf], np.nan)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    features.to_csv(args.output, index=False)
    print(f"scoring features: {args.output}")
    print(f"applicants: {len(features)}")
    print(f"feature columns: {len(features.columns) - 1 - int('TARGET' in features)}")
    print(f"missing optional tables: {', '.join(missing) if missing else 'none'}")


if __name__ == "__main__":
    main()
