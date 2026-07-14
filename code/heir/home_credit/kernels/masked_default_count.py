"""High-level Home Credit kernels intended for HEIR lowering.

These functions are deliberately plain, fixed-shape arithmetic. They are not a
pandas replacement and they do not discover groups. The surrounding Python code
prepares numeric vectors; HEIR should own the encrypted arithmetic kernel.
"""

from __future__ import annotations

from collections.abc import Sequence


def sum_vector(mask: Sequence[float]) -> float:
    """Return sum(mask). Intended HE primitive: packed encrypted reduction."""
    total = 0.0
    for value in mask:
        total += value
    return total


def masked_default_count(group_mask: Sequence[float], target_mask: Sequence[float]) -> float:
    """Return sum(group_mask * target_mask)."""
    total = 0.0
    for group, target in zip(group_mask, target_mask, strict=True):
        total += group * target
    return total


def masked_sum(group_mask: Sequence[float], values: Sequence[float]) -> float:
    """Return sum(group_mask * values)."""
    total = 0.0
    for group, value in zip(group_mask, values, strict=True):
        total += group * value
    return total


KERNEL_INTENT = {
    "sum_vector": "count = sum(mask)",
    "masked_default_count": "default_count = sum(group_mask * target_mask)",
    "masked_sum": "masked_total = sum(group_mask * numeric_values)",
}

