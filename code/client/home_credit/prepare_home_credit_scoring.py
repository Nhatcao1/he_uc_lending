#!/usr/bin/env python3
"""Prepare plaintext feature vectors for the OpenFHE client encryptor."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare Home Credit scoring vectors.")
    parser.add_argument("--features", type=Path, default=Path("prepared_payloads/home_credit_scoring/features.csv"))
    parser.add_argument("--model", type=Path, default=Path("models/home_credit_scoring_model.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("prepared_payloads/home_credit_scoring/he"))
    parser.add_argument("--row-limit", type=int, default=0)
    return parser.parse_args()


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "feature"


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    model = json.loads(args.model.read_text(encoding="utf-8"))
    model_features = list(model.get("features") or [])
    if not model_features:
        raise ValueError("model contains no features")

    output_dir = args.output_dir
    vector_dir = output_dir / "vectors"
    vector_dir.mkdir(parents=True, exist_ok=True)
    handles: dict[str, object] = {}
    manifest_rows: list[dict[str, object]] = []
    score_rows: list[dict[str, object]] = []
    try:
        for feature_index, feature in enumerate(model_features):
            source = str(feature["source"])
            source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()[:8]
            vector = f"score.{feature_index:03d}.{safe_name(source)[:80]}.{source_hash}"
            path = vector_dir / f"{safe_name(vector)}.csv"
            handles[source] = path.open("w", encoding="utf-8", newline="")
            manifest_rows.append(
                {
                    "table": "home_credit_scoring_features",
                    "name": vector,
                    "kind": "ml_feature",
                    "source_column": source,
                    "analysis": "credit_risk_scoring",
                    "group": "applicant",
                    "label": source,
                    "rows": 0,
                    "file": f"vectors/{path.name}",
                }
            )
            score_rows.append(
                {
                    "feature": source,
                    "vector": vector,
                    "weight": feature["weight"],
                    "bias": model["bias"],
                }
            )

        row_map: list[dict[str, object]] = []
        with args.features.open("r", encoding="utf-8-sig", newline="") as input_file:
            reader = csv.DictReader(input_file)
            if not reader.fieldnames or "SK_ID_CURR" not in reader.fieldnames:
                raise ValueError("feature table must contain SK_ID_CURR")
            for row_index, row in enumerate(reader):
                if args.row_limit and row_index >= args.row_limit:
                    break
                row_map.append(
                    {
                        "row_index": row_index,
                        "SK_ID_CURR": row["SK_ID_CURR"],
                        "TARGET": row.get("TARGET", ""),
                    }
                )
                for feature in model_features:
                    source = str(feature["source"])
                    raw = row.get(source, "")
                    try:
                        value = float(raw) if raw not in {"", None} else float(feature["fill"])
                    except ValueError:
                        value = float(feature["fill"])
                    if not math.isfinite(value):
                        value = float(feature["fill"])
                    scale = float(feature.get("scale", 1.0))
                    if abs(scale) <= 1e-12:
                        scale = 1.0
                    scaled = (value - float(feature.get("mean", 0.0))) / scale
                    handles[source].write(f"{scaled:.17g}\n")  # type: ignore[attr-defined]
    finally:
        for handle in handles.values():
            handle.close()  # type: ignore[attr-defined]

    for row in manifest_rows:
        row["rows"] = len(row_map)
    write_csv(
        output_dir / "vector_manifest.csv",
        ["table", "name", "kind", "source_column", "analysis", "group", "label", "rows", "file"],
        manifest_rows,
    )
    write_csv(output_dir / "linear_score_vectors.csv", ["feature", "vector", "weight", "bias"], score_rows)
    write_csv(output_dir / "scoring_row_map.client.csv", ["row_index", "SK_ID_CURR", "TARGET"], row_map)
    write_csv(
        output_dir / "numeric_vectors.csv",
        ["column", "vector"],
        [],
    )
    write_csv(
        output_dir / "aggregate_operations.csv",
        ["analysis", "group", "label", "operation", "value_name", "mask_vector", "value_vector"],
        [],
    )
    (output_dir / "credit_scoring_model.client.json").write_text(
        json.dumps(model, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"prepared HE scoring directory: {output_dir}")
    print(f"applicants: {len(row_map)}")
    print(f"encrypted feature vectors: {len(model_features)}")


if __name__ == "__main__":
    main()
