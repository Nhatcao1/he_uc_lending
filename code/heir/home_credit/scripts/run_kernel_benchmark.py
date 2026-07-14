#!/usr/bin/env python3
"""Run a HEIR Home Credit benchmark package through optional external commands."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from code.heir.home_credit.report import write_report
from code.heir.home_credit.runner import probe_tool, run_template
from code.heir.home_credit.workloads import TARGET_GROUP_WORKLOADS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare and optionally run HEIR Home Credit EDA benchmark.")
    parser.add_argument("--input", default="data/home_credit/application_train.csv")
    parser.add_argument("--workload", default="app_target_by_education_type", choices=sorted(TARGET_GROUP_WORKLOADS))
    parser.add_argument("--row-limit", type=int, default=0, help="0 means all rows.")
    parser.add_argument("--output-root", default="benchmark_runs/home_credit_heir_eda")
    parser.add_argument("--run-name", default="")
    parser.add_argument(
        "--backend",
        default="prepare-only",
        choices=["prepare-only", "external", "heir-toolchain", "heir-openfhe-dot"],
    )
    parser.add_argument("--heir-compile-cmd", default="", help="Optional command template for HEIR compilation.")
    parser.add_argument("--heir-eval-cmd", default="", help="Optional command template for HEIR evaluation.")
    parser.add_argument("--heir-opt", default="heir-opt", help="Path to heir-opt for heir-toolchain backend.")
    parser.add_argument("--heir-translate", default="heir-translate", help="Path to heir-translate for heir-toolchain backend.")
    parser.add_argument(
        "--heir-openfhe-runner",
        default="",
        help="Optional generated/OpenFHE executable to run as a HEIR smoke benchmark, e.g. dot_product.",
    )
    parser.add_argument(
        "--heir-generated-dir",
        default="/root/heir-work",
        help="Directory containing HEIR-generated heir_output.cpp/h for heir-openfhe-dot.",
    )
    parser.add_argument(
        "--openfhe-dir",
        default="",
        help="Optional OpenFHE_DIR for CMake, e.g. /root/openfhe-install/lib/cmake/OpenFHE.",
    )
    parser.add_argument(
        "--heir-vector-size",
        type=int,
        default=8,
        help="Static vector size expected by HEIR-generated dot_product sources.",
    )
    parser.add_argument(
        "--heir-scheme",
        default="BGV",
        choices=["BGV", "CKKS"],
        help="Scheme requested for HEIR backend. Current generated dot backend supports BGV only.",
    )
    return parser.parse_args()


def read_reference(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as input_file:
        return list(csv.DictReader(input_file))


def compare_heir_result(reference_rows: list[dict[str, str]], result: dict[str, object]) -> dict[str, object]:
    actual_rows = result.get("results", [])
    if not isinstance(actual_rows, list):
        return {"passed": False, "failures": ["heir_result.json has no results list"]}
    actual_by_label = {
        str(row.get("label")): row
        for row in actual_rows
        if isinstance(row, dict)
    }
    failures = []
    for row in reference_rows:
        label = row["label"]
        actual = actual_by_label.get(label)
        if actual is None:
            failures.append(f"missing label {label}")
            continue
        expected_count = int(float(row["count"]))
        expected_default = int(float(row["default_count"]))
        actual_count = int(float(actual.get("count", -1)))
        actual_default = int(float(actual.get("default_count", -1)))
        if expected_count != actual_count or expected_default != actual_default:
            failures.append(
                f"{label}: expected count/default {expected_count}/{expected_default}, "
                f"actual {actual_count}/{actual_default}"
            )
    return {
        "passed": not failures,
        "failures": failures[:20],
        "checked_labels": len(reference_rows),
    }


def path_size_bytes(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        total = 0
        for child in path.rglob("*"):
            if child.is_file():
                total += child.stat().st_size
        return total
    return 0


def collect_artifact_sizes(run_dir: Path) -> dict[str, int]:
    return {
        "run_dir_total": path_size_bytes(run_dir),
        "tensor_dir": path_size_bytes(run_dir / "tensors"),
        "tensor_manifest": path_size_bytes(run_dir / "tensor_manifest.csv"),
        "pandas_reference": path_size_bytes(run_dir / "pandas_reference.csv"),
        "workload_spec": path_size_bytes(run_dir / "heir_workload_spec.json"),
        "heir_result_json": path_size_bytes(run_dir / "heir_result.json"),
        "compiled_dir": path_size_bytes(run_dir / "compiled"),
        "heir_openfhe_dot_dir": path_size_bytes(run_dir / "heir_openfhe_dot"),
    }


def write_log(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", errors="replace")


def parse_expected_actual(output: str) -> dict[str, object]:
    expected = re.search(r"Expected:\s*([-+0-9.eE]+)", output)
    actual = re.search(r"Actual:\s*([-+0-9.eE]+)", output)
    if not expected or not actual:
        return {"found": False}
    expected_value = float(expected.group(1))
    actual_value = float(actual.group(1))
    return {
        "found": True,
        "expected": expected_value,
        "actual": actual_value,
        "absolute_error": abs(expected_value - actual_value),
        "passed": expected_value == actual_value,
    }


def main() -> None:
    args = parse_args()
    from code.heir.home_credit.prepare import prepare_target_group_tensors

    repo = Path.cwd()
    run_name = args.run_name or f"{args.workload}_{args.row_limit or 'all'}_{int(time.time())}"
    run_dir = Path(args.output_root) / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    summary = prepare_target_group_tensors(Path(args.input), args.workload, args.row_limit, run_dir)
    summary["workload_spec"] = str(run_dir / "heir_workload_spec.json")
    summary["backend_status"] = "prepared_only"
    summary["heir_compile_cmd"] = args.heir_compile_cmd
    summary["heir_eval_cmd"] = args.heir_eval_cmd
    summary["heir_opt"] = args.heir_opt
    summary["heir_translate"] = args.heir_translate
    summary["heir_openfhe_runner"] = args.heir_openfhe_runner
    summary["heir_generated_dir"] = args.heir_generated_dir
    summary["openfhe_dir"] = args.openfhe_dir
    summary["heir_vector_size"] = args.heir_vector_size
    summary["heir_scheme"] = args.heir_scheme

    context = {
        "run_dir": str(run_dir),
        "workload": args.workload,
        "workload_spec": str(run_dir / "heir_workload_spec.json"),
        "tensor_manifest": str(run_dir / "tensor_manifest.csv"),
        "pandas_reference": str(run_dir / "pandas_reference.csv"),
        "heir_output_json": str(run_dir / "heir_result.json"),
        "compiled_dir": str(run_dir / "compiled"),
    }
    timings = dict(summary.get("timings_seconds", {}))

    if args.backend == "external":
        if not args.heir_eval_cmd:
            raise SystemExit("--backend external requires --heir-eval-cmd")
        if args.heir_compile_cmd:
            timings["heir_compile_seconds"], compile_output = run_template(args.heir_compile_cmd, context, repo)
            (run_dir / "heir_compile.log").write_text(compile_output, encoding="utf-8")
        timings["heir_eval_seconds"], eval_output = run_template(args.heir_eval_cmd, context, repo)
        (run_dir / "heir_eval.log").write_text(eval_output, encoding="utf-8")
        summary["backend_status"] = "external_commands_completed"
    elif args.backend == "heir-toolchain":
        toolchain = {}
        timings["heir_opt_probe_seconds"], opt_status, opt_output = probe_tool([args.heir_opt, "--help"], repo)
        write_log(run_dir / "heir_opt_probe.log", opt_output)
        toolchain["heir_opt_status"] = opt_status

        timings["heir_translate_probe_seconds"], translate_status, translate_output = probe_tool(
            [args.heir_translate, "--help"], repo
        )
        write_log(run_dir / "heir_translate_probe.log", translate_output)
        toolchain["heir_translate_status"] = translate_status

        if args.heir_openfhe_runner:
            timings["heir_openfhe_runner_seconds"], runner_status, runner_output = probe_tool(
                [args.heir_openfhe_runner], repo
            )
            write_log(run_dir / "heir_openfhe_runner.log", runner_output)
            toolchain["heir_openfhe_runner_status"] = runner_status
            toolchain["heir_openfhe_runner_result"] = parse_expected_actual(runner_output)
        else:
            toolchain["heir_openfhe_runner_status"] = "not_configured"
            toolchain["heir_openfhe_runner_result"] = {"found": False}

        summary["heir_toolchain"] = toolchain
        summary["backend_status"] = "heir_toolchain_probe_completed"
    elif args.backend == "heir-openfhe-dot":
        if args.heir_scheme != "BGV":
            raise SystemExit("heir-openfhe-dot currently supports only BGV generated sources, not CKKS.")
        from code.heir.home_credit.backends.openfhe_dot import run_openfhe_dot_backend

        backend_timings, heir_result, backend_log = run_openfhe_dot_backend(
            run_dir=run_dir,
            generated_dir=Path(args.heir_generated_dir),
            openfhe_dir=args.openfhe_dir,
            vector_size=args.heir_vector_size,
        )
        timings.update(backend_timings)
        write_log(run_dir / "heir_openfhe_dot.log", backend_log)
        reference_rows_for_compare = read_reference(Path(summary["pandas_reference"]))
        summary["heir_result"] = heir_result
        summary["heir_correctness"] = compare_heir_result(reference_rows_for_compare, heir_result)
        summary["backend_status"] = "heir_openfhe_dot_completed"

    summary["timings_seconds"] = timings
    summary["artifact_sizes_bytes"] = collect_artifact_sizes(run_dir)
    (run_dir / "benchmark_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    reference_rows = read_reference(Path(summary["pandas_reference"]))
    write_report(run_dir / "benchmark_report.md", summary, reference_rows)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
