# HEIR Home Credit EDA Path

This folder is a separate HEIR-oriented lane for Home Credit encrypted EDA.
It does not replace the current handwritten OpenFHE benchmark yet.

The first target is notebook section `5.14.x`:

```text
group_count = sum(group_mask)
default_count = sum(group_mask * target_mask)
```

The Python wrapper prepares fixed-shape numeric tensors and a benchmark report.
The server-side HEIR build can be plugged in with external command templates.

Even in `prepare-only` mode, the report measures the normal notebook-style
pandas baseline:

```text
pandas_load_seconds
pandas_reference_seconds
normal_python_baseline_seconds
```

These timings are the comparison point for later HEIR compiled/evaluated runs.

Each run writes a detailed report:

```text
benchmark_runs/home_credit_heir_eda/<run-name>/benchmark_report.md
```

The report includes:

```text
case metadata
notebook-style pandas reference code
normal Python / pandas baseline timing
HEIR kernel intent
external HEIR execution status
prepared tensor paths
artifact size summary
timing summary
result preview
raw JSON summary
```

## Prepare Only

```bash
python3 code/benchmarks/home_credit_heir_eda_benchmark.py \
  --input data/home_credit/application_train.csv \
  --workload app_target_by_education_type \
  --row-limit 10000 \
  --output-root benchmark_runs/home_credit_heir_eda \
  --run-name education_prepare_only
```

## External HEIR Commands

Use `--backend external` when the server has a HEIR compile/eval command ready.
The following placeholders are available:

```text
{run_dir}
{workload}
{workload_spec}
{tensor_manifest}
{pandas_reference}
{heir_output_json}
{compiled_dir}
```

Example shape:

```bash
python3 code/benchmarks/home_credit_heir_eda_benchmark.py \
  --input data/home_credit/application_train.csv \
  --workload app_target_by_education_type \
  --row-limit 10000 \
  --backend external \
  --heir-compile-cmd "your-heir-compile --spec {workload_spec} --out {compiled_dir}" \
  --heir-eval-cmd "your-heir-run --compiled {compiled_dir} --manifest {tensor_manifest} --out {heir_output_json}"
```

The first stable server target should be `masked_default_count`.

## HEIR Toolchain Probe

Use this before the real Home Credit generated runner exists. It verifies and
times the installed HEIR tools and can run an existing OpenFHE sample executable
such as `dot_product`.

```bash
python3 code/benchmarks/home_credit_heir_eda_benchmark.py \
  --input data/home_credit/application_train.csv \
  --workload app_target_by_education_type \
  --row-limit 0 \
  --output-root benchmark_runs/home_credit_heir_eda \
  --run-name education_heir_toolchain_probe_all \
  --backend heir-toolchain \
  --heir-opt /root/heir-work/.venv/bin/heir-opt \
  --heir-translate /root/heir-work/.venv/bin/heir-translate \
  --heir-openfhe-runner /root/heir-work/build-heir-openfhe/dot_product
```

This is a HEIR/OpenFHE toolchain smoke benchmark, not yet the Home Credit
encrypted EDA kernel. The report will say that explicitly.
