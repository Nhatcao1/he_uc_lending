#!/usr/bin/env python3
"""Create safe upload bags from an encrypted Home Credit payload directory."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import shutil
import zipfile
from pathlib import Path


WORKLOADS = (
    "all",
    "numeric_summary",
    "category_eda",
    "bucket_eda",
    "domain_ratio_eda",
    "linear_score",
)
WORKLOAD_FILE_STEMS = {
    "all": "home_credit_all",
    "numeric_summary": "home_credit_numeric_summary",
    "category_eda": "home_credit_category_eda",
    "bucket_eda": "home_credit_bucket_eda",
    "domain_ratio_eda": "home_credit_domain_ratio_eda",
    "linear_score": "home_credit_linear_score",
}
AGGREGATE_ANALYSIS = {
    "category_eda": "category",
    "bucket_eda": "bucket",
    "domain_ratio_eda": "ratio",
}
REQUIRED_TOP_LEVEL = (
    "crypto_context.bin",
)
OPTIONAL_TOP_LEVEL = (
    "column_manifest.csv",
    "eval_sum_keys.bin",
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
    parser = argparse.ArgumentParser(description="Package encrypted Home Credit server artifacts into upload zips.")
    parser.add_argument("--encrypted-dir", required=True, type=Path, help="Directory produced by encrypt_home_credit_payload.")
    parser.add_argument(
        "--workload",
        choices=WORKLOADS,
        default="all",
        help="Upload bag to create. Use a specific workload for smaller browser uploads.",
    )
    parser.add_argument("--output", type=Path, help="Output zip path. Overrides --output-dir naming.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for the generated upload zip. Defaults to <encrypted-dir>/upload_bags when --output is omitted.",
    )
    parser.add_argument(
        "--include-public-key",
        action="store_true",
        help="Include public_key.bin. It is not needed by current server jobs, but is safe to share.",
    )
    parser.add_argument(
        "--client-key-dir",
        type=Path,
        help="Client key directory produced by encrypt_home_credit_payload. If set, secret_key.bin is copied near the upload dir.",
    )
    parser.add_argument(
        "--secret-output-dir",
        type=Path,
        help="Root directory for copied client-only key material. Defaults to <upload-dir>/../client_private.",
    )
    parser.add_argument(
        "--no-copy-secret",
        action="store_true",
        help="Do not copy secret_key.bin even when --client-key-dir is provided.",
    )
    return parser.parse_args()


def is_blocked(path: Path) -> bool:
    lowered_parts = {part.lower() for part in path.parts}
    lowered_name = path.name.lower()
    return bool(lowered_parts & BLOCKED_PARTS) or lowered_name in RAW_DATA_NAMES


def require_file(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"missing required encrypted artifact: {path}")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    require_file(path)
    with path.open("r", encoding="utf-8-sig", newline="") as input_file:
        reader = csv.DictReader(input_file)
        if not reader.fieldnames:
            raise ValueError(f"manifest has no header: {path}")
        return list(reader.fieldnames), [dict(row) for row in reader]


def write_manifest_text(fieldnames: list[str], rows: list[dict[str, str]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def referenced_paths(rows: list[dict[str, str]], fields: tuple[str, ...]) -> set[str]:
    paths: set[str] = set()
    for row in rows:
        for field in fields:
            value = (row.get(field) or "").strip()
            if value:
                paths.add(value)
    return paths


def add_required_file(files: list[Path], encrypted_dir: Path, name: str) -> None:
    path = encrypted_dir / name
    require_file(path)
    files.append(path)


def add_optional_file(files: list[Path], encrypted_dir: Path, name: str) -> None:
    path = encrypted_dir / name
    if path.is_file():
        files.append(path)


def collect_all_files(encrypted_dir: Path, include_public_key: bool) -> tuple[list[Path], dict[str, str]]:
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
    return safe_files, {}


def collect_numeric_summary_files(encrypted_dir: Path) -> tuple[list[Path], dict[str, str]]:
    files: list[Path] = []
    generated: dict[str, str] = {}
    add_required_file(files, encrypted_dir, "crypto_context.bin")
    add_required_file(files, encrypted_dir, "eval_sum_keys.bin")
    add_required_file(files, encrypted_dir, "column_manifest.csv")
    fieldnames, rows = read_csv_rows(encrypted_dir / "column_manifest.csv")
    if "ciphertext" not in fieldnames:
        raise ValueError("column_manifest.csv must contain a ciphertext column")
    for rel in sorted(referenced_paths(rows, ("ciphertext",))):
        path = encrypted_dir / "columns" / rel
        require_file(path)
        files.append(path)
    return files, generated


def collect_aggregate_files(encrypted_dir: Path, workload: str) -> tuple[list[Path], dict[str, str]]:
    analysis = AGGREGATE_ANALYSIS[workload]
    files: list[Path] = []
    generated: dict[str, str] = {}
    add_required_file(files, encrypted_dir, "crypto_context.bin")
    add_required_file(files, encrypted_dir, "eval_sum_keys.bin")
    add_required_file(files, encrypted_dir, "eval_mult_keys.bin")

    fieldnames, rows = read_csv_rows(encrypted_dir / "aggregate_manifest.csv")
    if "analysis" not in fieldnames:
        raise ValueError("aggregate_manifest.csv must contain an analysis column")
    filtered_rows = [row for row in rows if (row.get("analysis") or "").strip() == analysis]
    if not filtered_rows:
        raise ValueError(f"aggregate_manifest.csv has no rows for analysis={analysis}")
    generated["aggregate_manifest.csv"] = write_manifest_text(fieldnames, filtered_rows)

    for rel in sorted(referenced_paths(filtered_rows, ("mask_ciphertext", "value_ciphertext"))):
        path = encrypted_dir / "vectors" / rel
        require_file(path)
        files.append(path)
    return files, generated


def collect_linear_score_files(encrypted_dir: Path) -> tuple[list[Path], dict[str, str]]:
    files: list[Path] = []
    generated: dict[str, str] = {}
    add_required_file(files, encrypted_dir, "crypto_context.bin")
    add_required_file(files, encrypted_dir, "score_manifest.csv")
    fieldnames, rows = read_csv_rows(encrypted_dir / "score_manifest.csv")
    if "ciphertext" not in fieldnames:
        raise ValueError("score_manifest.csv must contain a ciphertext column")
    for rel in sorted(referenced_paths(rows, ("ciphertext",))):
        path = encrypted_dir / "score_features" / rel
        require_file(path)
        files.append(path)
    return files, generated


def collect_files(encrypted_dir: Path, workload: str, include_public_key: bool) -> tuple[list[Path], dict[str, str]]:
    if workload == "all":
        return collect_all_files(encrypted_dir, include_public_key)
    if workload == "numeric_summary":
        files, generated = collect_numeric_summary_files(encrypted_dir)
    elif workload in AGGREGATE_ANALYSIS:
        files, generated = collect_aggregate_files(encrypted_dir, workload)
    elif workload == "linear_score":
        files, generated = collect_linear_score_files(encrypted_dir)
    else:
        raise ValueError(f"unknown workload: {workload}")

    if include_public_key:
        add_optional_file(files, encrypted_dir, "public_key.bin")

    safe_files = []
    for path in files:
        rel = path.relative_to(encrypted_dir)
        if is_blocked(rel):
            raise ValueError(f"blocked unsafe upload artifact path: {rel}")
        safe_files.append(path)
    for rel in generated:
        if is_blocked(Path(rel)):
            raise ValueError(f"blocked unsafe generated artifact path: {rel}")
    return safe_files, generated


def output_path_for(args: argparse.Namespace, encrypted_dir: Path) -> Path:
    if args.output:
        return args.output
    output_dir = args.output_dir or (encrypted_dir / "upload_bags")
    return output_dir / f"{WORKLOAD_FILE_STEMS[args.workload]}.upload.zip"


def secret_output_dir_for(args: argparse.Namespace, upload_dir: Path) -> Path:
    if args.secret_output_dir:
        return args.secret_output_dir
    return upload_dir.parent / "client_private"


def client_material_metadata(encrypted_dir: Path, args: argparse.Namespace) -> dict[str, str]:
    context_path = encrypted_dir / "crypto_context.bin"
    require_file(context_path)
    metadata = {
        "crypto_context_sha256": file_sha256(context_path),
    }
    public_key_path = encrypted_dir / "public_key.bin"
    if public_key_path.is_file():
        metadata["public_key_sha256"] = file_sha256(public_key_path)
        material_basis = metadata["public_key_sha256"]
    elif args.client_key_dir and (args.client_key_dir / "secret_key.bin").is_file():
        metadata["secret_key_sha256"] = file_sha256(args.client_key_dir / "secret_key.bin")
        material_basis = metadata["secret_key_sha256"]
    else:
        material_basis = metadata["crypto_context_sha256"]
    metadata["client_material_id"] = material_basis[:16]
    return metadata


def write_zip(
    encrypted_dir: Path,
    output_path: Path,
    workload: str,
    files: list[Path],
    generated: dict[str, str],
    material_metadata: dict[str, str],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in files:
            bundle.write(path, path.relative_to(encrypted_dir).as_posix())
        for rel, content in generated.items():
            bundle.writestr(rel, content)
        manifest = {
            "artifact_type": "home_credit_encrypted_upload_bag",
            "workload": workload,
            "source_dir": str(encrypted_dir),
            "file_count": len(files) + len(generated),
            "files": [path.relative_to(encrypted_dir).as_posix() for path in files],
            "generated_files": sorted(generated),
            **material_metadata,
            "blocked": sorted(BLOCKED_PARTS | RAW_DATA_NAMES),
        }
        bundle.writestr("upload_bag_manifest.json", json.dumps(manifest, indent=2))


def copy_client_material(
    args: argparse.Namespace,
    encrypted_dir: Path,
    upload_dir: Path,
    material_metadata: dict[str, str],
) -> Path | None:
    if args.no_copy_secret or not args.client_key_dir:
        return None
    source = args.client_key_dir / "secret_key.bin"
    require_file(source)
    material_id = material_metadata["client_material_id"]
    secret_dir = secret_output_dir_for(args, upload_dir) / material_id
    upload_dir_resolved = upload_dir.resolve()
    secret_dir_resolved = secret_dir.resolve()
    if secret_dir_resolved == upload_dir_resolved or upload_dir_resolved in secret_dir_resolved.parents:
        raise ValueError("secret-output-dir must not be inside the upload output dir")
    secret_dir.mkdir(parents=True, exist_ok=True)
    destination = secret_dir / "secret_key.bin"
    shutil.copy2(source, destination)
    context_destination = secret_dir / "crypto_context.bin"
    shutil.copy2(encrypted_dir / "crypto_context.bin", context_destination)
    material_manifest = {
        "artifact_type": "home_credit_client_material",
        **material_metadata,
        "secret_key": "secret_key.bin",
        "crypto_context": "crypto_context.bin",
    }
    (secret_dir / "client_material_manifest.json").write_text(
        json.dumps(material_manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    readme = secret_dir / "README_DO_NOT_UPLOAD.txt"
    readme.write_text(
        "Client-only Home Credit HE secret key.\n"
        "\n"
        "Do not upload this directory to the HE server.\n"
        "Use this key material only on the trusted client side to decrypt matching result bundles.\n",
        encoding="utf-8",
    )
    return destination


def main() -> None:
    args = parse_args()
    encrypted_dir = args.encrypted_dir.resolve()
    if not encrypted_dir.is_dir():
        raise NotADirectoryError(f"encrypted-dir is not a directory: {encrypted_dir}")
    files, generated = collect_files(encrypted_dir, args.workload, args.include_public_key)
    output_path = output_path_for(args, encrypted_dir)
    material_metadata = client_material_metadata(encrypted_dir, args)
    write_zip(encrypted_dir, output_path, args.workload, files, generated, material_metadata)
    copied_secret = copy_client_material(args, encrypted_dir, output_path.parent, material_metadata)
    print(f"upload bag: {output_path}")
    print(f"upload dir: {output_path.parent}")
    print(f"workload: {args.workload}")
    print(f"client material id: {material_metadata['client_material_id']}")
    print(f"files: {len(files) + len(generated)}")
    print("secret key included: no")
    if copied_secret:
        print(f"client secret copy: {copied_secret}")


if __name__ == "__main__":
    main()
