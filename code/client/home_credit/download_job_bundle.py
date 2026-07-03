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


DECRYPT_CONFIG = {
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download a HE web job result bundle.")
    parser.add_argument("--server", required=True, help="Web receiver URL, e.g. http://100.84.97.118:8080")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--output-dir", default="server_returns")
    parser.add_argument("--token", default="", help="Bearer token when HE_RECEIVER_TOKEN is set.")
    parser.add_argument("--context", default="encrypted_payloads/home_credit_basic/crypto_context.bin")
    parser.add_argument("--secret-key", default="keys/home_credit_basic/secret_key.bin")
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


def safe_extract(zip_path: Path, output_dir: Path) -> None:
    root = output_dir.resolve()
    with zipfile.ZipFile(zip_path) as bundle:
        for member in bundle.infolist():
            target = (output_dir / member.filename).resolve()
            if root != target and root not in target.parents:
                raise ValueError(f"unsafe zip member path: {member.filename}")
        bundle.extractall(output_dir)


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
    print("\nDecrypt command:")
    print(
        f"{args.decrypt_bin} \\\n"
        f"  --context {args.context} \\\n"
        f"  --secret-key {args.secret_key} \\\n"
        f"  --manifest {manifest} \\\n"
        f"  --input-dir {input_dir} \\\n"
        f"  --output-csv {output_csv} \\\n"
        f"  --manifest-type {cfg['manifest_type']}"
    )


def main() -> None:
    args = parse_args()
    job_id = safe_job_id(args.job_id)
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
    print_decrypt_command(args, job_dir)


if __name__ == "__main__":
    main()
