#!/usr/bin/env python3
"""Train/export a small plaintext linear Home Credit model for CKKS inference.

The exported model is intentionally simple: logistic regression features,
standardization parameters, weights, and bias. The server can later evaluate the
linear logit under CKKS; sigmoid/probability conversion should happen after the
client decrypts.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


FEATURE_SOURCES = [
    "AMT_CREDIT",
    "AMT_INCOME_TOTAL",
    "AMT_ANNUITY",
    "EXT_SOURCE_2",
    "EXT_SOURCE_3",
    "AGE_YEARS",
    "CREDIT_INCOME_PERCENT",
    "ANNUITY_INCOME_PERCENT",
    "DAYS_EMPLOYED_PERCENT",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a small Home Credit linear model JSON.")
    parser.add_argument("--input", default="data/home_credit/application_train.csv")
    parser.add_argument("--output", default="models/home_credit_linear_score_model.json")
    parser.add_argument("--row-limit", type=int, default=0)
    parser.add_argument("--max-iter", type=int, default=500)
    return parser.parse_args()


def add_features(df):  # type: ignore[no-untyped-def]
    df = df.copy()
    df["AGE_YEARS"] = df["DAYS_BIRTH"].abs() / 365.25
    df["CREDIT_INCOME_PERCENT"] = df["AMT_CREDIT"] / df["AMT_INCOME_TOTAL"]
    df["ANNUITY_INCOME_PERCENT"] = df["AMT_ANNUITY"] / df["AMT_INCOME_TOTAL"]
    employed = df["DAYS_EMPLOYED"].where(df["DAYS_EMPLOYED"] != 365243)
    df["DAYS_EMPLOYED_PERCENT"] = employed / df["DAYS_BIRTH"]
    return df


def main() -> None:
    args = parse_args()
    try:
        import numpy as np
        import pandas as pd
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
    except ImportError as exc:
        raise SystemExit(
            "This optional trainer needs pandas, numpy, and scikit-learn. "
            "Install them on the client, or use the default demo model from "
            "prepare_home_credit_basic_eda.py."
        ) from exc

    df = pd.read_csv(args.input)
    if args.row_limit:
        df = df.head(args.row_limit)
    df = add_features(df)
    df = df.replace([np.inf, -np.inf], np.nan)
    x = df[FEATURE_SOURCES]
    y = df["TARGET"].astype(int)

    pipeline = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("model", LogisticRegression(max_iter=args.max_iter, class_weight="balanced")),
        ]
    )
    pipeline.fit(x, y)

    imputer = pipeline.named_steps["imputer"]
    scaler = pipeline.named_steps["scaler"]
    model = pipeline.named_steps["model"]

    features = []
    for index, source in enumerate(FEATURE_SOURCES):
        features.append(
            {
                "name": f"{source}_scaled",
                "source": source,
                "fill": float(imputer.statistics_[index]),
                "mean": float(scaler.mean_[index]),
                "scale": float(scaler.scale_[index]),
                "weight": float(model.coef_[0][index]),
            }
        )

    payload = {
        "model_type": "sklearn_logistic_regression_linear_ckks",
        "trained": True,
        "score_meaning": "logit; client may apply sigmoid after decrypt",
        "bias": float(model.intercept_[0]),
        "features": features,
        "training_rows": int(len(df)),
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote model: {output}")
    print(f"features: {len(features)}")


if __name__ == "__main__":
    main()
