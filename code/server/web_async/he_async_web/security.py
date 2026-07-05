"""Upload path checks and web token helpers."""

from __future__ import annotations

from pathlib import Path, PurePosixPath


ANCHOR_DIRS = ("columns", "vectors", "score_features", "masks", "target")
BLOCKED_TOKENS = (
    "secret",
    "private",
    ".ssh",
    "id_rsa",
    "application_train.csv",
    "application_test.csv",
    "bureau.csv",
    "bureau_balance.csv",
    "previous_application.csv",
    "pos_cash_balance.csv",
    "credit_card_balance.csv",
    "installments_payments.csv",
)


def normalize_upload_path(raw_path: str) -> Path:
    normalized = raw_path.replace("\\", "/").strip("/")
    parts = [part for part in normalized.split("/") if part]
    if not parts:
        raise ValueError("empty upload path")
    lowered_parts = [part.lower() for part in parts]
    for anchor in ANCHOR_DIRS:
        if anchor in lowered_parts:
            idx = lowered_parts.index(anchor)
            parts = parts[idx:]
            break
    else:
        parts = [parts[-1]]

    safe = "/".join(parts)
    path = PurePosixPath(safe)
    lowered = safe.lower()
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe upload path: {raw_path}")
    if any(token in lowered for token in BLOCKED_TOKENS):
        raise ValueError(f"blocked sensitive/raw-looking path: {raw_path}")
    return Path(*path.parts)

