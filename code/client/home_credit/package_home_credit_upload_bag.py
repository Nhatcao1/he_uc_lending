#!/usr/bin/env python3
"""Create one safe upload bag from an encrypted Home Credit payload directory."""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path


REQUIRED_TOP_LEVEL = (
    "crypto_context.bin",
    "eval_sum_keys.bin",
    "column_manifest.csv",
)
OPTIONAL_TOP_LEVEL = (
    "eval_mult_keys.bin",
    "aggregate_manifest.csv",
    "score_manifest.csv",
    "bundle_manifest.json",
    "public_key.bin",
)
OPTIONAL_DIRS = (
    "columns",
    "vectors",
    "score_features",
)
BLOCKED_PARTS = {
    "secret_key.bin",
    "secret",
    "private",
    ".ssh",
    "id_rsa",
}
RAW_DATA_NAMES = {
    "application_train.csv",
    "application_test.csv",
    "bureau.csv",
    "bureau_balance.csv",
    "previous_application.csv",
    "pos_cash_balance.csv",
    "credit_card_balance.csv",
    "installments_payments.csv",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Package encrypted Home Credit server artifacts into one zip.")
    parser.add_argument("--encrypted-dir", required=True, type=Path, help="Directory produced by encrypt_home_credit_payload.")
    parser.add_argument("--output", required=True, type=Path, help="Output zip path.")
    parser.add_argument(
        "--include-public-key",
        action="store_true",
        help="Include public_key.bin. It is not needed by current server jobs, but is safe to share.",
    )
    return parser.parse_args()


def is_blocked(path: Path) -> bool:
    lowered_parts = {part.lower() for part in path.parts}
    lowered_name = path.name.lower()
    return bool(lowered_parts & BLOCKED_PARTS) or lowered_name in RAW_DATA_NAMES


def require_file(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"missing required encrypted artifact: {path}")


def collect_files(encrypted_dir: Path, include_public_key: bool) -> list[Path]:
    for name in REQUIRED_TOP_LEVEL:
        require_file(encrypted_dir / name)

    files: list[Path] = []
    for name in REQUIRED_TOP_LEVEL:
        files.append(encrypted_dir / name)

    for name in OPTIONAL_TOP_LEVEL:
        if name == "public_key.bin" and not include_public_key:
            continue
        path = encrypted_dir / name
        if path.is_file():
            files.append(path)

    for dirname in OPTIONAL_DIRS:
        root = encrypted_dir / dirname
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file():
                files.append(path)

    safe_files = []
    for path in files:
        rel = path.relative_to(encrypted_dir)
        if is_blocked(rel):
            raise ValueError(f"blocked unsafe upload artifact path: {rel}")
        safe_files.append(path)
    return safe_files


def write_zip(encrypted_dir: Path, output_path: Path, files: list[Path]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in files:
            bundle.write(path, path.relative_to(encrypted_dir).as_posix())
        manifest = {
            "artifact_type": "home_credit_encrypted_upload_bag",
            "source_dir": str(encrypted_dir),
            "file_count": len(files),
            "files": [path.relative_to(encrypted_dir).as_posix() for path in files],
            "blocked": sorted(BLOCKED_PARTS | RAW_DATA_NAMES),
        }
        bundle.writestr("upload_bag_manifest.json", json.dumps(manifest, indent=2))


def main() -> None:
    args = parse_args()
    encrypted_dir = args.encrypted_dir.resolve()
    if not encrypted_dir.is_dir():
        raise NotADirectoryError(f"encrypted-dir is not a directory: {encrypted_dir}")
    files = collect_files(encrypted_dir, args.include_public_key)
    write_zip(encrypted_dir, args.output, files)
    print(f"upload bag: {args.output}")
    print(f"files: {len(files)}")
    print("secret key included: no")


if __name__ == "__main__":
    main()
