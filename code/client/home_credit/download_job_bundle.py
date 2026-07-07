#!/usr/bin/env python3
"""Download and extract a completed HE web job result bundle.

Runs on the client side. It downloads only encrypted server results plus job
metadata, then prints the local decrypt command to run with the client's secret
key.
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def numeric_decrypt_config(output_dir: str) -> dict[str, str]:
    return {
        "manifest": f"{output_dir}/summary_manifest.csv",
        "input_dir": output_dir,
        "output_csv": f"decrypted_{output_dir}.csv",
        "manifest_type": "numeric",
    }


def aggregate_decrypt_config(output_dir: str) -> dict[str, str]:
    return {
        "manifest": f"{output_dir}/aggregate_summary_manifest.csv",
        "input_dir": output_dir,
        "output_csv": f"decrypted_{output_dir}.csv",
        "manifest_type": "aggregate",
    }


DECRYPT_CONFIG = {
    "home_credit_missing_data": aggregate_decrypt_config("missing_data"),
    "home_credit_app_dist_amt_credit": numeric_decrypt_config("app_dist_amt_credit"),
    "home_credit_app_dist_amt_income_total": numeric_decrypt_config("app_dist_amt_income_total"),
    "home_credit_app_dist_amt_goods_price": numeric_decrypt_config("app_dist_amt_goods_price"),
    "home_credit_app_target_balance": aggregate_decrypt_config("app_target_balance"),
    "home_credit_app_selected_correlation_stats": aggregate_decrypt_config("app_selected_correlation_stats"),
    "home_credit_join_hmac_prev_contract_status": aggregate_decrypt_config("join_hmac_prev_contract_status"),
    "home_credit_join_psi_prev_contract_status": aggregate_decrypt_config("join_psi_prev_contract_status"),
    "home_credit_linear_score_demo": {
        "manifest": "linear_score_demo/score_summary_manifest.csv",
        "input_dir": "linear_score_demo",
        "output_csv": "decrypted_linear_score_demo.csv",
        "manifest_type": "score",
    },
}

for _suffix in (
    "app_suite_type",
    "app_loan_type",
    "app_own_car_realty",
    "app_income_type",
    "app_family_status",
    "app_occupation_type",
    "app_education_type",
    "app_housing_type",
    "app_organization_type",
    "app_target_by_income_type",
    "app_target_by_family_status",
    "app_target_by_occupation_type",
    "app_target_by_education_type",
    "app_target_by_housing_type",
    "app_target_by_organization_type",
    "app_target_by_suite_type",
    "prev_contract_type",
    "prev_weekday_process_start",
    "prev_cash_loan_purpose",
    "prev_contract_status",
    "prev_payment_type",
    "prev_reject_reason",
    "prev_suite_type",
    "prev_client_type",
    "prev_goods_category",
    "prev_portfolio",
    "prev_product_type",
    "prev_channel_type",
    "prev_seller_industry",
    "prev_yield_group",
    "prev_product_combination",
    "prev_insured_on_approval",
):
    DECRYPT_CONFIG[f"home_credit_{_suffix}"] = aggregate_decrypt_config(_suffix)

DECRYPT_CONFIG.update(
    {
        "home_credit_target_balance": aggregate_decrypt_config("target_balance"),
        "home_credit_application_numeric_summary": numeric_decrypt_config("application_numeric_summary"),
        "home_credit_application_category_counts": aggregate_decrypt_config("application_category_counts"),
        "home_credit_application_default_rates": aggregate_decrypt_config("application_default_rates"),
        "home_credit_application_numeric_histograms": aggregate_decrypt_config("application_numeric_histograms"),
        "home_credit_previous_application_category_counts": aggregate_decrypt_config("previous_application_category_counts"),
        "home_credit_previous_application_target_rates": aggregate_decrypt_config("previous_application_target_rates"),
        "home_credit_selected_correlation_stats": aggregate_decrypt_config("selected_correlation_stats"),
    }
)

DECRYPT_CONFIG.update(
    {
        "home_credit_numeric_summary": {
            "manifest": "numeric_summary/summary_manifest.csv",
            "input_dir": "numeric_summary",
            "output_csv": "decrypted_numeric_summary.csv",
            "manifest_type": "numeric",
        },
        "home_credit_category_eda": {
            "manifest": "category_eda/aggregate_summary_manifest.csv",
            "input_dir": "category_eda",
            "output_csv": "decrypted_category_eda.csv",
            "manifest_type": "aggregate",
        },
        "home_credit_bucket_eda": {
            "manifest": "bucket_eda/aggregate_summary_manifest.csv",
            "input_dir": "bucket_eda",
            "output_csv": "decrypted_bucket_eda.csv",
            "manifest_type": "aggregate",
        },
        "home_credit_domain_ratio_eda": {
            "manifest": "ratio_eda/aggregate_summary_manifest.csv",
            "input_dir": "ratio_eda",
            "output_csv": "decrypted_ratio_eda.csv",
            "manifest_type": "aggregate",
        },
        "home_credit_linear_score": {
            "manifest": "linear_score/score_summary_manifest.csv",
            "input_dir": "linear_score",
            "output_csv": "decrypted_linear_scores.csv",
            "manifest_type": "score",
        },
    }
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download a HE web job result bundle.")
    parser.add_argument("--server", required=True, help="Web receiver URL, e.g. http://100.84.97.118:8080")
    parser.add_argument("--job-id", required=True, help="Job id to download, or 'latest' for newest succeeded job.")
    parser.add_argument("--output-dir", default="client_runs/home_credit_basic/server_returns")
    parser.add_argument("--token", default="", help="Bearer token when HE_RECEIVER_TOKEN is set.")
    parser.add_argument("--client-private-root", default="client_runs/home_credit_basic/client_private")
    parser.add_argument("--context", default="", help="Override crypto_context.bin path. Normally inferred from job manifest.")
    parser.add_argument("--secret-key", default="", help="Override secret_key.bin path. Normally inferred from job manifest.")
    parser.add_argument("--decrypt-bin", default="./build/decrypt_ckks_results")
    return parser.parse_args()


def safe_job_id(job_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", job_id):
        raise ValueError(f"unsafe job id: {job_id}")
    return job_id


def download(url: str, token: str) -> bytes:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    try:
        with urlopen(request) as response:  # noqa: S310 - user-provided trusted internal receiver URL
            return response.read()
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"download failed: {exc.code} {exc.reason}: {body}") from exc


def download_json(url: str, token: str) -> dict[str, object]:
    payload = download(url, token)
    return json.loads(payload.decode("utf-8"))


def resolve_job_id(args: argparse.Namespace) -> str:
    requested = args.job_id.strip()
    if requested.lower() != "latest":
        return safe_job_id(requested)

    base = args.server.rstrip("/")
    data = download_json(f"{base}/api/results?limit=1", args.token)
    results = data.get("results")
    if not isinstance(results, list) or not results:
        raise SystemExit("no succeeded jobs found on server")
    latest = results[0]
    if not isinstance(latest, dict) or not latest.get("job_id"):
        raise SystemExit("server returned an invalid latest result payload")
    return safe_job_id(str(latest["job_id"]))


def safe_extract(zip_path: Path, output_dir: Path) -> None:
    root = output_dir.resolve()
    with zipfile.ZipFile(zip_path) as bundle:
        for member in bundle.infolist():
            target = (output_dir / member.filename).resolve()
            if root != target and root not in target.parents:
                raise ValueError(f"unsafe zip member path: {member.filename}")
        bundle.extractall(output_dir)


def load_json_if_exists(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def infer_client_material(args: argparse.Namespace, job_dir: Path) -> tuple[Path, Path, str]:
    context_override = Path(args.context) if args.context else None
    secret_override = Path(args.secret_key) if args.secret_key else None
    if context_override and secret_override:
        return context_override, secret_override, "manual override"

    upload_manifest = load_json_if_exists(job_dir / "upload_bag_manifest.json")
    material_id = str(upload_manifest.get("client_material_id") or "").strip()
    if material_id:
        material_dir = Path(args.client_private_root) / material_id
        context = context_override or (material_dir / "crypto_context.bin")
        secret = secret_override or (material_dir / "secret_key.bin")
        return context, secret, f"client_material_id={material_id}"

    fallback_context = context_override or Path("encrypted_payloads/home_credit_basic/crypto_context.bin")
    fallback_secret = secret_override or Path("client_runs/home_credit_basic/client_private/secret_key.bin")
    return fallback_context, fallback_secret, "legacy fallback; result bundle has no upload_bag_manifest.json"


def print_decrypt_command(args: argparse.Namespace, job_dir: Path) -> None:
    status_path = job_dir / "job_status.json"
    if not status_path.exists():
        print("No job_status.json found; cannot infer decrypt command.")
        return

    status = json.loads(status_path.read_text(encoding="utf-8"))
    job_type = status.get("job_type")
    cfg = DECRYPT_CONFIG.get(job_type)
    if cfg is None:
        print(f"No decrypt template for job_type={job_type!r}")
        return

    manifest = job_dir / cfg["manifest"]
    input_dir = job_dir / cfg["input_dir"]
    output_csv = job_dir / cfg["output_csv"]
    context, secret_key, material_source = infer_client_material(args, job_dir)
    print("\nDecrypt command:")
    print(f"# key material: {material_source}")
    print(
        f"{args.decrypt_bin} \\\n"
        f"  --context {context} \\\n"
        f"  --secret-key {secret_key} \\\n"
        f"  --manifest {manifest} \\\n"
        f"  --input-dir {input_dir} \\\n"
        f"  --output-csv {output_csv} \\\n"
        f"  --manifest-type {cfg['manifest_type']}"
    )


def main() -> None:
    args = parse_args()
    job_id = resolve_job_id(args)
    base = args.server.rstrip("/")
    output_root = Path(args.output_dir)
    job_dir = output_root / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    url = f"{base}/api/jobs/{job_id}/download-bundle"
    data = download(url, args.token)
    zip_path = job_dir / f"he_result_{job_id}.zip"
    zip_path.write_bytes(data)
    safe_extract(zip_path, job_dir)

    print(f"downloaded: {zip_path}")
    print(f"extracted: {job_dir}")
    print(f"job id: {job_id}")
    print_decrypt_command(args, job_dir)


if __name__ == "__main__":
    main()
