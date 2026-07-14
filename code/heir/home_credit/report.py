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
    runner_result = toolchain.get("heir_openfhe_runner_result", {}) if isinstance(toolchain, dict) else {}
    smoke_rows = []
    if isinstance(runner_result, dict) and runner_result.get("found"):
        smoke_rows = [
            ["expected", runner_result.get("expected", "")],
            ["actual", runner_result.get("actual", "")],
            ["absolute_error", runner_result.get("absolute_error", "")],
            ["passed", runner_result.get("passed", "")],
        ]
    else:
        smoke_rows = [["result", "not found in runner output"]]
    heir_correctness = summary.get("heir_correctness", {})
    if isinstance(heir_correctness, dict):
        correctness_rows = [
            ["passed", heir_correctness.get("passed", "")],
            ["checked_labels", heir_correctness.get("checked_labels", "")],
            ["failure_count", len(heir_correctness.get("failures", [])) if isinstance(heir_correctness.get("failures", []), list) else ""],
        ]
        failure_rows = [[failure] for failure in heir_correctness.get("failures", [])] or [["none"]]
    else:
        correctness_rows = [["status", "not run"]]
        failure_rows = [["not run"]]
    heir_result = summary.get("heir_result", {})
    heir_result_rows = []
    if isinstance(heir_result, dict):
        heir_result_rows = [
            ["backend", heir_result.get("backend", "")],
            ["chunk_size", heir_result.get("chunk_size", "")],
            ["eval_seconds_inside_runner", heir_result.get("eval_seconds_inside_runner", "")],
            ["total_seconds_inside_runner", heir_result.get("total_seconds_inside_runner", "")],
        ]
    if not heir_result_rows:
        heir_result_rows = [["status", "not run"]]
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
| HEIR scheme requested | `{summary.get('heir_scheme', '')}` |
| HEIR vector size | `{summary.get('heir_vector_size', '')}` |
| HEIR opt pipeline supplied | `{bool(summary.get('heir_opt_pipeline'))}` |
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

### OpenFHE Runner Smoke Result

{markdown_table(["Field", "Value"], smoke_rows)}

`heir_toolchain_probe_completed` means the report measured real HEIR tool
availability and optional sample-run timing. It still does not mean the Home
Credit `masked_default_count` kernel has been compiled and evaluated under HE.
That requires a generated runner that accepts this benchmark's tensor manifest
and writes `heir_result.json`.

## Home Credit HEIR/OpenFHE Result

{markdown_table(["Field", "Value"], heir_result_rows)}

### Correctness Against Pandas Reference

{markdown_table(["Field", "Value"], correctness_rows)}

### Correctness Failures

{markdown_table(["Failure"], failure_rows)}

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
