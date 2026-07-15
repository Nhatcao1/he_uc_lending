# HEIR Home Credit EDA Path

This folder is a separate HEIR-oriented lane for Home Credit encrypted EDA.
It does not replace the current handwritten OpenFHE benchmark yet.

Scheme rule for Home Credit EDA:

```text
Active target scheme: CKKS
```

Any non-CKKS HEIR sample in this folder is a toolchain smoke/bridge only. It
must not be used as the product-facing Home Credit EDA scheme.

The initial targets are notebook sections `5.14.x` and `5.15.x`:

```text
group_count = sum(group_mask)
default_count = sum(group_mask * target_mask)

# 5.15 previous_application category distribution
category_count = sum(category_mask * count_weight)
category_percent = sum(category_mask * percent_weight)
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

The concise source-input, Python-output, and decrypted-HE-output contract is
documented in [`HOME_CREDIT_HEIR_EDA_INPUT_OUTPUT.md`](../../../docs/HOME_CREDIT_HEIR_EDA_INPUT_OUTPUT.md).

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

## Active Full-HEIR CKKS Benchmark

Use this path for proof that HEIR generated and executed the encrypted kernel.
The benchmark refuses to pass unless `heir_output.cpp/h` are HEIR-generated,
CKKS-only, compiled into the runner, and the runner calls the generated
`dot_product(...)` function.

```text
HEIR tensor manifest
-> HEIR-generated CKKS OpenFHE source
-> CMake builds generated source plus runner
-> runner calls generated dot_product(mask, target)
-> compare against notebook-style pandas reference
-> report generated source hashes and correctness
```

Run with pre-generated CKKS `heir_output.cpp/h` in `/root/heir-work`:

```bash
python3 code/benchmarks/home_credit_heir_eda_benchmark.py \
  --input data/home_credit/application_train.csv \
  --workload app_target_by_education_type \
  --row-limit 1000 \
  --output-root benchmark_runs/home_credit_heir_eda \
  --run-name education_heir_generated_ckks_1k \
  --backend heir-generated-ckks \
  --heir-generated-dir /root/heir-work \
  --openfhe-dir /root/openfhe-development/build \
  --heir-vector-size 8192
```

Or regenerate source in the benchmark run when the HEIR CKKS lowering pipeline
is known:

```bash
python3 code/benchmarks/home_credit_heir_eda_benchmark.py \
  --input data/home_credit/application_train.csv \
  --workload app_target_by_education_type \
  --row-limit 1000 \
  --output-root benchmark_runs/home_credit_heir_eda \
  --run-name education_heir_generated_ckks_1k_regen \
  --backend heir-generated-ckks \
  --heir-opt /root/heir-work/.venv/bin/heir-opt \
  --heir-translate /root/heir-work/.venv/bin/heir-translate \
  --openfhe-dir /root/openfhe-development/build \
  --heir-vector-size 8192 \
  --heir-opt-pipeline '<PASTE_HEIR_CKKS_PIPELINE_HERE>'
```

This is the one-shot convenience path: it materializes tensors, generates the
CKKS source, builds the generated runner, encrypts the tensors, invokes the
generated `dot_product`, decrypts, checks against pandas, and writes the
report. The report separates source generation/build overhead from runtime and
also separates context/key setup, encryption, encrypted computation, and
decryption. `encrypted_compute_seconds` is the pure HE calculation metric.

The report is written to `benchmark_report.md` under the run directory. The
proof section must include `heir_output.cpp`, `heir_output.h`, both SHA-256
hashes, the runner binary, and `backend = heir_generated_ckks_openfhe`.

## 5.15 Previous Application Category Benchmark

All `5.15.1` through `5.15.16` workloads use the same generated CKKS
dot-product kernel. The wrapper prepares encrypted category masks from
`previous_application.csv`, plus encrypted `1` and `100/N` weight vectors, so
the server returns both encrypted count and encrypted percent. `N` is the
non-null row count for the selected column. High-cardinality columns use the
configured top-K labels plus `__OTHER__`.

```bash
python3 code/benchmarks/home_credit_heir_eda_benchmark.py \
  --previous-application data/home_credit/previous_application.csv \
  --workload prev_contract_status \
  --row-limit 10000 \
  --output-root benchmark_runs/home_credit_heir_eda \
  --run-name previous_contract_status_heir_ckks_10k \
  --backend heir-generated-ckks \
  --heir-generated-dir /root/heir-work \
  --openfhe-dir /root/openfhe-development/build \
  --heir-vector-size 8192
```

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

## Archived Non-Proof Bridges

Archived status: the current generated `dot_product` sample proves the
HEIR/OpenFHE toolchain can emit and build OpenFHE code, but it is not an active
Home Credit EDA benchmark path because it is not CKKS.

The target CKKS kernel remains:

```text
dot_product(mask, target) = sum(mask * target)
dot_product(mask, ones)   = sum(mask)
```

`heir-ckks-openfhe` is useful only as a fallback CKKS OpenFHE benchmark over the
HEIR tensor contract. It does not prove HEIR generated the kernel.

`heir-openfhe-dot` is archived and blocked because the synced sample is not the
active CKKS proof path.

To search for the existing dot-product pipeline on the server:

```bash
cd /root/heir-work
grep -R "pass-pipeline\\|heir-opt\\|emit-openfhe" -n . 2>/dev/null | head -100
history | grep -E "heir-opt|emit-openfhe|pass-pipeline" | tail -80
```
