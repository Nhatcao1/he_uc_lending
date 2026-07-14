"""Markdown reporting for HEIR Home Credit benchmark packages."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(item) for item in row) + " |")
    return "\n".join(lines)


def write_report(path: Path, summary: dict[str, Any], reference_rows: list[dict[str, Any]]) -> None:
    timings = summary.get("timings_seconds", {})
    timing_rows = [[key, f"{float(value):.6f}"] for key, value in timings.items()]
    preview_rows = [
        [
            row["label"],
            row["count"],
            row["default_count"],
            f"{float(row['default_rate']) * 100:.4f}%",
        ]
        for row in reference_rows[:20]
    ]
    report = f"""# HEIR Home Credit EDA Benchmark Package

## Case

| Field | Value |
| --- | --- |
| Workload | `{summary['workload']}` |
| Notebook section | `{summary.get('notebook_section', '')}` |
| Title | `{summary.get('title', '')}` |
| Input | `{summary['input']}` |
| Requested row limit | `{summary['requested_row_limit'] or 'all'}` |
| Actual rows loaded | `{summary['actual_rows']}` |
| Group column | `{summary['column']}` |
| Kernel | `{summary['kernel']}` |
| Backend status | `{summary.get('backend_status', 'prepared_only')}` |

## Notebook Reference Code

```python
{summary.get('pandas_reference_code', '')}
```

## HEIR Kernel Intent

```text
group_count = sum(group_mask)
default_count = sum(group_mask * target_mask)
default_rate = default_count / group_count after trusted decryption
```

The HEIR kernel should receive fixed-shape numeric tensors. It should not parse
raw strings, discover groups, or reproduce pandas DataFrame behavior.

## Prepared Tensors

| Artifact | Path |
| --- | --- |
| Workload spec | `{summary.get('workload_spec', '')}` |
| Tensor manifest | `{summary.get('tensor_manifest', '')}` |
| Pandas reference | `{summary.get('pandas_reference', '')}` |

## Timing Summary

{markdown_table(["Metric", "Seconds"], timing_rows)}

## Result Preview

{markdown_table(["Segment", "Count", "Default count", "Default rate"], preview_rows)}

## Raw Summary

```json
{json.dumps(summary, indent=2)}
```
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")

