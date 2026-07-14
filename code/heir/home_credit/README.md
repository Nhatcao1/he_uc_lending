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

## Real HEIR/OpenFHE Dot-Product Backend

The first real Home Credit HEIR backend reuses the generated `dot_product`
kernel:

```text
dot_product(mask, target) = sum(mask * target)
dot_product(mask, ones)   = sum(mask)
```

The runner chunks tensors into 8-row blocks because the synced sample was
generated from `tensor<8xi16>`.

Small test first:

```bash
python3 code/benchmarks/home_credit_heir_eda_benchmark.py \
  --input data/home_credit/application_train.csv \
  --workload app_target_by_education_type \
  --row-limit 1000 \
  --output-root benchmark_runs/home_credit_heir_eda \
  --run-name education_heir_openfhe_dot_1k \
  --backend heir-openfhe-dot \
  --heir-generated-dir /root/heir-work \
  --openfhe-dir /root/openfhe-install/lib/cmake/OpenFHE \
  --heir-vector-size 8 \
  --heir-scheme BGV
```

All rows:

```bash
python3 code/benchmarks/home_credit_heir_eda_benchmark.py \
  --input data/home_credit/application_train.csv \
  --workload app_target_by_education_type \
  --row-limit 0 \
  --output-root benchmark_runs/home_credit_heir_eda \
  --run-name education_heir_openfhe_dot_all \
  --backend heir-openfhe-dot \
  --heir-generated-dir /root/heir-work \
  --openfhe-dir /root/openfhe-install/lib/cmake/OpenFHE \
  --heir-vector-size 8 \
  --heir-scheme BGV
```

This is real HEIR-generated OpenFHE computation, but still an initial adapter:
it reuses the 8-slot generated sample kernel rather than compiling a new larger
Home Credit-specific kernel.

For an 8192-slot generated kernel, first regenerate `/root/heir-work/heir_output.cpp`
and `/root/heir-work/heir_output.h`, or pass the HEIR lowering pipeline directly
with `--heir-opt-pipeline`. The benchmark writes the source MLIR here:

```text
benchmark_runs/home_credit_heir_eda/<run-name>/heir_openfhe_dot/home_credit_dot_product_8192.mlir
```

If the pipeline is known, run:

```bash
python3 code/benchmarks/home_credit_heir_eda_benchmark.py \
  --input data/home_credit/application_train.csv \
  --workload app_target_by_education_type \
  --row-limit 1000 \
  --output-root benchmark_runs/home_credit_heir_eda \
  --run-name education_heir_openfhe_dot_1k_v8192 \
  --backend heir-openfhe-dot \
  --heir-opt /root/heir-work/.venv/bin/heir-opt \
  --heir-translate /root/heir-work/.venv/bin/heir-translate \
  --heir-generated-dir /root/heir-work \
  --openfhe-dir /root/openfhe-install/lib/cmake/OpenFHE \
  --heir-vector-size 8192 \
  --heir-scheme BGV \
  --heir-opt-pipeline '<PASTE_HEIR_PIPELINE_HERE>'
```

The runner intentionally fails if `--heir-vector-size` does not match the
generated `heir_output.cpp/h`, because otherwise the benchmark would silently
measure the wrong tensor size.

To search for the existing dot-product pipeline on the server:

```bash
cd /root/heir-work
grep -R "pass-pipeline\\|heir-opt\\|emit-openfhe" -n . 2>/dev/null | head -100
history | grep -E "heir-opt|emit-openfhe|pass-pipeline" | tail -80
```
