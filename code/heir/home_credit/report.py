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


def human_bytes(value: Any) -> str:
    try:
        size = float(value)
    except (TypeError, ValueError):
        return ""
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    unit = 0
    while size >= 1024 and unit < len(units) - 1:
        size /= 1024
        unit += 1
    if unit == 0:
        return f"{int(size)} {units[unit]}"
    return f"{size:.2f} {units[unit]}"


def write_report(path: Path, summary: dict[str, Any], reference_rows: list[dict[str, Any]]) -> None:
    timings = summary.get("timings_seconds", {})
    timing_rows = [[key, f"{float(value):.6f}"] for key, value in timings.items()]
    artifact_sizes = summary.get("artifact_sizes_bytes", {})
    artifact_rows = [
        [key, human_bytes(value), value]
        for key, value in artifact_sizes.items()
        if value
    ]
    baseline_rows = [
        ["Pandas CSV load", f"{float(timings.get('pandas_load_seconds', 0.0)):.6f}"],
        ["Notebook-style pandas calculation", f"{float(timings.get('pandas_reference_seconds', 0.0)):.6f}"],
        ["Normal Python baseline total", f"{float(timings.get('normal_python_baseline_seconds', 0.0)):.6f}"],
    ]
    toolchain = summary.get("heir_toolchain", {})
    toolchain_rows = [
        ["heir-opt", summary.get("heir_opt", ""), toolchain.get("heir_opt_status", "") if isinstance(toolchain, dict) else ""],
        [
            "heir-translate",
            summary.get("heir_translate", ""),
            toolchain.get("heir_translate_status", "") if isinstance(toolchain, dict) else "",
        ],
        [
            "OpenFHE runner",
            summary.get("heir_openfhe_runner", ""),
            toolchain.get("heir_openfhe_runner_status", "") if isinstance(toolchain, dict) else "",
        ],
    ]
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

## Normal Python / Pandas Baseline

This section measures the same notebook-style calculation before any HEIR
compile/evaluation step. It is the baseline for comparing HEIR-generated
encrypted kernels against ordinary pandas execution.

{markdown_table(["Baseline step", "Seconds"], baseline_rows)}

## HEIR Kernel Intent

```text
group_count = sum(group_mask)
default_count = sum(group_mask * target_mask)
default_rate = default_count / group_count after trusted decryption
```

The HEIR kernel should receive fixed-shape numeric tensors. It should not parse
raw strings, discover groups, or reproduce pandas DataFrame behavior.

## HEIR Execution Status

| Field | Value |
| --- | --- |
| Backend status | `{summary.get('backend_status', 'prepared_only')}` |
| External compile command used | `{bool(summary.get('heir_compile_cmd'))}` |
| External eval command used | `{bool(summary.get('heir_eval_cmd'))}` |

## HEIR Toolchain Probe

{markdown_table(["Tool", "Path", "Status"], toolchain_rows)}

`heir_toolchain_probe_completed` means the report measured real HEIR tool
availability and optional sample-run timing. It still does not mean the Home
Credit `masked_default_count` kernel has been compiled and evaluated under HE.
That requires a generated runner that accepts this benchmark's tensor manifest
and writes `heir_result.json`.

## Prepared Tensors

| Artifact | Path |
| --- | --- |
| Workload spec | `{summary.get('workload_spec', '')}` |
| Tensor manifest | `{summary.get('tensor_manifest', '')}` |
| Pandas reference | `{summary.get('pandas_reference', '')}` |

## Artifact Size Summary

{markdown_table(["Artifact", "Size", "Bytes"], artifact_rows)}

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
