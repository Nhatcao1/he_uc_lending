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
            ["absolute_tolerance", heir_correctness.get("tolerance", summary.get("accuracy_tolerance", ""))],
            ["checked_labels", heir_correctness.get("checked_labels", "")],
            ["max_absolute_error", heir_correctness.get("max_absolute_error", "")],
            ["mean_absolute_error", heir_correctness.get("mean_absolute_error", "")],
            ["failure_count", len(heir_correctness.get("failures", [])) if isinstance(heir_correctness.get("failures", []), list) else ""],
        ]
        failure_rows = [[failure] for failure in heir_correctness.get("failures", [])] or [["none"]]
        accuracy_rows = [
            [
                detail.get("label", ""),
                detail.get("expected_count", ""),
                detail.get("actual_count", ""),
                detail.get("count_absolute_error", ""),
                detail.get("secondary_metric", ""),
                detail.get("expected_secondary", ""),
                detail.get("actual_secondary", ""),
                detail.get("secondary_absolute_error", ""),
                detail.get("passed", ""),
            ]
            for detail in heir_correctness.get("details", [])
            if isinstance(detail, dict)
        ] or [["not run", "", "", "", "", "", "", "", ""]]
    else:
        correctness_rows = [["status", "not run"]]
        failure_rows = [["not run"]]
        accuracy_rows = [["not run", "", "", "", "", "", "", "", ""]]
    heir_result = summary.get("heir_result", {})
    heir_result_rows = []
    proof_rows = [["status", "not run"]]
    if isinstance(heir_result, dict):
        heir_result_rows = [
            ["backend", heir_result.get("backend", "")],
            ["scheme", heir_result.get("scheme", "")],
            ["slots", heir_result.get("slots", "")],
            ["codegen", heir_result.get("codegen", "")],
            ["generated_function", heir_result.get("generated_function", "")],
            ["chunk_size", heir_result.get("chunk_size", "")],
            ["context_setup_seconds", heir_result.get("context_setup_seconds", "")],
            ["keygen_configure_seconds", heir_result.get("keygen_configure_seconds", "")],
            ["encryption_seconds", heir_result.get("encryption_seconds", "")],
            ["encrypted_compute_seconds", heir_result.get("encrypted_compute_seconds", "")],
            ["decryption_seconds", heir_result.get("decryption_seconds", "")],
            ["eval_seconds_inside_runner", heir_result.get("eval_seconds_inside_runner", "")],
            ["total_seconds_inside_runner", heir_result.get("total_seconds_inside_runner", "")],
            ["runner_binary", heir_result.get("runner_binary", "")],
            ["mlir_input", heir_result.get("mlir_input", "")],
            ["decrypted_csv", heir_result.get("decrypted_csv", "")],
        ]
        proof = heir_result.get("heir_proof", {})
        if isinstance(proof, dict) and proof:
            proof_rows = [
                ["heir_output.cpp", proof.get("heir_output_cpp", "")],
                ["heir_output.cpp sha256", proof.get("heir_output_cpp_sha256", "")],
                ["heir_output.h", proof.get("heir_output_h", "")],
                ["heir_output.h sha256", proof.get("heir_output_h_sha256", "")],
                ["detected_vector_size", proof.get("detected_vector_size", "")],
                ["required_symbols", ", ".join(proof.get("required_symbols", []))],
            ]
    if not heir_result_rows:
        heir_result_rows = [["status", "not run"]]
    is_target_by_group = bool(reference_rows and "default_count" in reference_rows[0])
    if is_target_by_group:
        preview_headers = ["Segment", "Count", "Default count", "Default rate"]
        preview_rows = [
            [
                row["label"],
                row["count"],
                row["default_count"],
                f"{float(row['default_rate']) * 100:.4f}%",
            ]
            for row in reference_rows[:20]
        ]
        kernel_intent = (
            "group_count = sum(group_mask)\n"
            "default_count = sum(group_mask * target_mask)\n"
            "default_rate = default_count / group_count after trusted decryption"
        )
    else:
        preview_headers = ["Segment", "Count", "Percent"]
        preview_rows = [
            [row["label"], row["count"], f"{float(row['percent']):.4f}%"]
            for row in reference_rows[:20]
        ]
        kernel_intent = (
            "category_count = sum(category_mask * count_weight)\n"
            "category_percent = sum(category_mask * percent_weight)\n"
            "# percent_weight is the encrypted vector 100 / valid_category_rows"
        )
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
| CKKS slots | `{summary.get('ckks_slots', '')}` |
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
{kernel_intent}
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

## HEIR Generated Source Proof

This section is the proof that the benchmark used HEIR-generated source. A
valid full-HEIR run must show generated `heir_output.cpp/h` paths and hashes,
and the runner must compile those files.

{markdown_table(["Field", "Value"], proof_rows)}

### Correctness Against Pandas Reference

{markdown_table(["Field", "Value"], correctness_rows)}

### Correctness Failures

{markdown_table(["Failure"], failure_rows)}

### CKKS Accuracy Detail

Every count and secondary result must have absolute error less than or equal to
the configured tolerance. The full machine-readable table is `heir_accuracy.csv`.

{markdown_table(["Label", "Pandas count", "CKKS count", "Count error", "Secondary metric", "Pandas value", "CKKS value", "Value error", "Pass"], accuracy_rows)}

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

{markdown_table(preview_headers, preview_rows)}

## Raw Summary

```json
{json.dumps(summary, indent=2)}
```
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")


def write_previous_loan_count_report(
    path: Path,
    summary: dict[str, Any],
    reference_rows: list[dict[str, Any]],
    actual_by_index: dict[str, float],
    mapping_by_index: dict[str, dict[str, str]],
) -> None:
    """Write the explicit report for the one-feature applicant-history flow."""
    timings = summary.get("timings_seconds", {})
    artifact_sizes = summary.get("artifact_sizes_bytes", {})
    accuracy = summary.get("heir_correctness", {})
    result = summary.get("heir_result", {})
    details = accuracy.get("details", []) if isinstance(accuracy, dict) else []
    preview_rows = []
    for row in reference_rows[:20]:
        index = str(row["app_index"])
        mapping = mapping_by_index.get(index, {})
        expected = float(row["previous_loan_count"])
        actual = actual_by_index.get(index, float("nan"))
        preview_rows.append(
            [
                index,
                mapping.get("TARGET", ""),
                int(expected),
                actual,
                abs(expected - actual) if actual == actual else "",
            ]
        )
    accuracy_rows = [
        [
            detail.get("app_index", ""),
            detail.get("expected_previous_loan_count", ""),
            detail.get("actual_previous_loan_count", ""),
            detail.get("absolute_error", ""),
            detail.get("passed", ""),
        ]
        for detail in details[:50]
        if isinstance(detail, dict)
    ] or [["not run", "", "", "", ""]]
    timing_rows = [[key, f"{float(value):.6f}"] for key, value in timings.items()]
    size_rows = [
        [key, human_bytes(value), value]
        for key, value in artifact_sizes.items()
        if value
    ]
    result_rows = [
        ["backend", result.get("backend", "") if isinstance(result, dict) else ""],
        ["scheme", result.get("scheme", "") if isinstance(result, dict) else ""],
        ["generated function", result.get("generated_function", "") if isinstance(result, dict) else ""],
        ["application count", result.get("application_count", "") if isinstance(result, dict) else ""],
        ["slots per applicant", result.get("slots_per_application", "") if isinstance(result, dict) else ""],
        ["encrypted compute seconds", result.get("encrypted_compute_seconds", "") if isinstance(result, dict) else ""],
        ["decrypted output", result.get("decrypted_output_csv", "") if isinstance(result, dict) else ""],
    ]
    proof = result.get("heir_proof", {}) if isinstance(result, dict) else {}
    proof_rows = [
        ["heir_output.cpp sha256", proof.get("heir_output_cpp_sha256", "")],
        ["heir_output.h sha256", proof.get("heir_output_h_sha256", "")],
        ["detected vector size", proof.get("detected_vector_size", "")],
    ] if isinstance(proof, dict) and proof else [["status", "not run"]]
    failures = accuracy.get("failures", []) if isinstance(accuracy, dict) else []
    failure_rows = [[item] for item in failures[:20]] if failures else [["none"]]

    report = f"""# HEIR CKKS Previous-Loan Count Benchmark

## Scope

One derived feature only: `previous_loan_count` for every applicant in
`application_train`. This benchmark intentionally does not compute approval
rate, amounts, or a risk score.

## Input And Boundary

| Field | Value |
| --- | --- |
| Application input | `{summary.get('application_input', '')}` |
| Previous-application input | `{summary.get('previous_application_input', '')}` |
| Application rows | `{summary.get('application_rows', '')}` |
| Previous rows loaded | `{summary.get('previous_application_rows', '')}` |
| Previous rows aligned to selected applicants | `{summary.get('matched_previous_rows', '')}` |
| Fixed slots per applicant | `{summary.get('slots_per_application', '')}` |
| Padding slots | `{summary.get('padding_slots', '')}` |

Source-side alignment maps `SK_ID_CURR` to an anonymous row index and assigns
each matching historical application to one fixed slot. It does **not** send
the ID mapping to the HE runner. `client_private/applicant_mapping.csv` stays
with the trusted source and is used only to interpret decrypted row indexes.

## Normal Pandas Reference

```python
{summary.get('pandas_reference_code', '')}
```

This is the ordinary dataframe flow: `groupby(SK_ID_CURR).size()`, then
`merge(..., how="left")`, then fill missing history counts with zero.

## Encrypted HEIR Input

```text
history_mask_matrix[applicant_index, history_slot] = 1 for a real previous row; 0 for padding
unit_weights[history_slot] = 1
```

For benchmark convenience, the generated runner creates keys, encrypts these
tensors, evaluates, and decrypts in one timed process. A deployment moves key
generation/encryption and final decryption to the trusted source. The HE
compute receives only anonymous row indexes, encrypted values, and public
tensor dimensions; it does not need `SK_ID_CURR` or `TARGET`.

## HEIR CKKS Calculation

```text
previous_loan_count[applicant] = dot_product(history_mask_row, unit_weights)
```

The generated `dot_product` kernel is evaluated once per applicant row. This
is deliberately a correctness-first implementation; its per-row ciphertext
work is expected to be expensive at full population scale.

## HEIR/OpenFHE Result

{markdown_table(["Field", "Value"], result_rows)}

## Generated Source Proof

{markdown_table(["Field", "Value"], proof_rows)}

## Accuracy Against Pandas

{markdown_table(["Field", "Value"], [
    ["passed", accuracy.get("passed", "") if isinstance(accuracy, dict) else "not run"],
    ["absolute tolerance", accuracy.get("tolerance", "") if isinstance(accuracy, dict) else ""],
    ["checked applicants", accuracy.get("checked_rows", "") if isinstance(accuracy, dict) else ""],
    ["max absolute error", accuracy.get("max_absolute_error", "") if isinstance(accuracy, dict) else ""],
])}

### Accuracy Detail

{markdown_table(["Anonymous app index", "Pandas count", "CKKS decrypted count", "Absolute error", "Pass"], accuracy_rows)}

### Failures

{markdown_table(["Failure"], failure_rows)}

## Decrypted Output Preview

`TARGET` below comes from the client-private mapping and is shown only to make
the later risk-analysis join visible. It is not consumed by this HE kernel.

{markdown_table(["Anonymous app index", "Client TARGET", "Pandas previous-loan count", "CKKS decrypted count", "Absolute error"], preview_rows)}

## Artifact Size Summary

{markdown_table(["Artifact", "Size", "Bytes"], size_rows)}

## Timing Summary

{markdown_table(["Metric", "Seconds"], timing_rows)}

## Next Scope

This benchmark proves encrypted per-applicant historical aggregation. A later
kernel may consume the encrypted count vector together with encrypted `TARGET`
to calculate correlation or a linear score without exposing either input.

## Raw Summary

```json
{json.dumps(summary, indent=2)}
```
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")
