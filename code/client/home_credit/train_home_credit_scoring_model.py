#!/usr/bin/env python3
"""Train and export a bounded logistic model for encrypted CKKS inference."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train Home Credit HE scoring model.")
    parser.add_argument("--features", type=Path, default=Path("prepared_payloads/home_credit_scoring/features.csv"))
    parser.add_argument("--output", type=Path, default=Path("models/home_credit_scoring_model.json"))
    parser.add_argument("--max-features", type=int, default=48)
    parser.add_argument("--max-iter", type=int, default=800)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        import numpy as np
        import pandas as pd
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import roc_auc_score
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
    except ImportError as exc:
        raise SystemExit("Install client dependencies: python -m pip install pandas numpy scikit-learn") from exc

    frame = pd.read_csv(args.features)
    if "TARGET" not in frame:
        raise ValueError("training feature table must contain TARGET")
    feature_names = [
        column
        for column in frame
        if column not in {"SK_ID_CURR", "TARGET"} and frame[column].notna().any()
    ]
    x = frame[feature_names].replace([np.inf, -np.inf], np.nan)
    y = frame["TARGET"].astype(int)

    def fit(columns):  # type: ignore[no-untyped-def]
        pipeline = Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
                ("model", LogisticRegression(max_iter=args.max_iter, class_weight="balanced", solver="liblinear")),
            ]
        )
        pipeline.fit(x[columns], y)
        return pipeline

    initial = fit(feature_names)
    coefficients = initial.named_steps["model"].coef_[0]
    ranked = sorted(zip(feature_names, coefficients), key=lambda item: abs(float(item[1])), reverse=True)
    selected = [name for name, _ in ranked[: max(1, min(args.max_features, len(ranked)))]]
    pipeline = fit(selected)

    imputer = pipeline.named_steps["imputer"]
    scaler = pipeline.named_steps["scaler"]
    model = pipeline.named_steps["model"]
    encoded = pipeline[:-1].transform(x[selected])
    training_auc = float(roc_auc_score(y, model.predict_proba(encoded)[:, 1]))
    exported = []
    for index, source in enumerate(selected):
        exported.append(
            {
                "name": source,
                "source": source,
                "fill": float(imputer.statistics_[index]),
                "mean": float(scaler.mean_[index]),
                "scale": float(scaler.scale_[index]),
                "weight": float(model.coef_[0][index]),
            }
        )
    payload = {
        "model_type": "home_credit_logistic_regression_ckks",
        "model_version": "home-credit-all-notebooks-v1",
        "score_meaning": "logit; trusted client applies sigmoid",
        "bias": float(model.intercept_[0]),
        "features": exported,
        "candidate_feature_count": len(feature_names),
        "selected_feature_count": len(exported),
        "training_rows": len(frame),
        "training_auc_in_sample": training_auc,
        "source_families": [
            "application",
            "domain_ratios",
            "bureau",
            "bureau_balance",
            "previous_application",
            "POS_CASH_balance",
            "credit_card_balance",
            "installments_payments",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"model: {args.output}")
    print(f"selected features: {len(exported)} / {len(feature_names)}")
    print(f"in-sample AUC (prototype diagnostic): {training_auc:.6f}")


if __name__ == "__main__":
    main()
