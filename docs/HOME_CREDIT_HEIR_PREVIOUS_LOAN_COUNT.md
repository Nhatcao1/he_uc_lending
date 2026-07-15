# HEIR CKKS: Previous-Loan Count Per Applicant

## Purpose

This is a deliberately narrow Home Credit feature-engineering benchmark. It
tests whether HEIR-generated OpenFHE CKKS code can calculate the number of
historical loan applications for each current applicant, without exposing the
applicant identifier to the HE computation.

The feature is:

```text
previous_loan_count(SK_ID_CURR) = number of previous_application rows for that applicant
```

## Normal Pandas Reference

```python
previous_counts = previous_application.groupby("SK_ID_CURR").size().rename("previous_loan_count")
joined = application_train[["SK_ID_CURR", "TARGET"]].merge(
    previous_counts, on="SK_ID_CURR", how="left"
).fillna({"previous_loan_count": 0})
```

This reference is timed and saved on every run. It is the correctness oracle
for the decrypted HEIR result.

## Source Preparation

The trusted source reads both tables and establishes the same `SK_ID_CURR`
alignment as the pandas reference. It then assigns every application row an
anonymous sequential index and creates a fixed-width history layout:

```text
history_mask_matrix[anonymous_applicant_index, history_slot]
```

- `1`: one matching `previous_application` row occupies this slot.
- `0`: padding; the applicant has no record in this slot.
- `slots_per_application`: maximum historical-row count in the selected run.

The mapping below is not an HE input and remains client-private:

```text
anonymous_applicant_index -> SK_ID_CURR, TARGET
```

It is saved at `client_private/applicant_mapping.csv` only so the trusted
client can interpret the returned anonymous counts.

## Exact Code Flow

### 1. Pandas baseline: the ordinary dataframe implementation

`prepare_previous_loan_count_tensors()` first calculates the normal reference:

```python
previous_counts = previous.groupby("SK_ID_CURR").size()
joined = application[["SK_ID_CURR", "TARGET"]].merge(
    previous_counts, on="SK_ID_CURR", how="left"
).fillna({"previous_loan_count": 0})
```

This produces one expected count for every `application_train` row. It is
saved as `pandas_reference.csv`, indexed only by anonymous `app_index`.

### 2. Source alignment: create a fixed HE tensor shape

The source assigns its application rows indexes `0..N-1`, filters historical
rows to those IDs, and finds the maximum number of prior rows for any selected
applicant, `K`.

```text
N = number of selected application_train rows
K = maximum previous_application rows belonging to one selected applicant
```

It creates a flattened `N x K` matrix. For applicant index `i`, each matching
historical row sets one position in `history_mask_matrix[i]` to `1`; remaining
positions are `0` padding.

```text
Applicant 0 has 3 history rows, K = 5:  [1, 1, 1, 0, 0]
Applicant 1 has 0 history rows:         [0, 0, 0, 0, 0]
Applicant 2 has 2 history rows:         [1, 1, 0, 0, 0]
```

The source needs IDs only for this local alignment. The identifier mapping is
never an input to the HE kernel. `K`, `N`, and padding volume are public shape
metadata in this prototype.

### 3. Material written by preparation

| File | Holder | Meaning |
| --- | --- | --- |
| `tensors/history_mask_matrix.csv` | HE benchmark input | Flattened anonymous `N x K` matrix of 0/1 values. |
| `tensors/unit_weights.csv` | HE benchmark input | `K` values, all `1`. |
| `pandas_reference.csv` | Benchmark validation | Expected count per anonymous index. |
| `client_private/applicant_mapping.csv` | Trusted source only | `app_index -> SK_ID_CURR, TARGET`; never needed by HE compute. |

### 4. Generated HEIR CKKS runner

`run_previous_loan_count_generated_ckks_backend()` copies the pre-generated
HEIR CKKS `heir_output.cpp/h`, validates that it is CKKS code, then builds a
small C++ runner alongside it.

For each anonymous applicant row, the runner:

```text
1. extracts the K history-mask values;
2. pads them to the generated HEIR vector size (normally 8192);
3. calls dot_product__encrypt__arg0(history_mask_row, public_key);
4. calls dot_product__encrypt__arg1(unit_weights, public_key);
5. calls the HEIR-generated dot_product(ciphertext_a, ciphertext_b);
6. calls dot_product__decrypt__result0(..., secret_key);
7. writes anonymous app_index and decrypted previous_loan_count.
```

The encrypted mathematical operation is therefore:

```text
Enc([1, 1, 1, 0, 0]) dot Enc([1, 1, 1, 1, 1]) = Enc(3)
```

### 5. Correctness validation

The Python benchmark reads `heir_decrypted_previous_loan_count.csv`, joins it
to `pandas_reference.csv` by `app_index`, and checks every absolute error
against the configured threshold, normally `1e-4`.

`TARGET` is shown only in the client-side preview to demonstrate that this
feature can later enter a risk analysis. This first kernel does **not** read,
encrypt, or calculate on `TARGET`.

## Encrypted HEIR Calculation

The benchmark runner creates keys, encrypts the flattened history-mask matrix
and a vector of ones, evaluates, then decrypts so that all phases can be
timed together. In deployment, key generation/encryption and final decryption
move to the trusted source. For each anonymous applicant row, the
HEIR-generated CKKS `dot_product` kernel computes:

```text
previous_loan_count = dot_product(history_mask_row, unit_weights)
```

The benchmark records separate timings for context setup, key generation,
encryption, generated CKKS compute, and decryption.

## Benchmark Boundary Versus Deployment

For convenient end-to-end performance measurement, the current generated C++
runner creates the key pair, encrypts, computes, and decrypts in one local
process. This is a benchmark harness, not the final multi-party deployment.

In deployment:

```text
Trusted source: align rows, create keys, encrypt tensors, retain secret key
HE server:      receive ciphertext/context/evaluation material, evaluate only
Trusted source: decrypt anonymous counts and restore SK_ID_CURR locally
```

The HE calculation itself is valid CKKS work, but the current harness must not
be interpreted as the server receiving a secret key.

## Current Limits

- The `SK_ID_CURR` join is local trusted-source alignment, not encrypted join
  or PSI.
- The runner executes one encrypted dot product per applicant. It proves
  correctness but is intentionally inefficient for hundreds of thousands of
  applicants.
- The result is a feature vector, not yet an encrypted correlation or credit
  score. Those are the next kernel stages.

## Output And Accuracy

The benchmark emits:

- `heir_decrypted_previous_loan_count.csv`: anonymous app index and decrypted count.
- `heir_accuracy.csv`: pandas expected count, CKKS result, absolute error, pass/fail.
- `benchmark_report.md`: pandas flow, HE data boundary, HEIR source proof,
  artifact sizes, timings, and output preview.

The acceptance criterion is absolute error less than or equal to `1e-4` for
every applicant count.

## Run

Start with a small, realistic smoke run because this correctness-first kernel
performs one generated encrypted dot product per applicant:

```bash
cd ~/he_uc_lending
source .venv/bin/activate

python3 code/benchmarks/home_credit_previous_loan_count_heir_benchmark.py \
  --input data/home_credit/application_train.csv \
  --previous-application data/home_credit/previous_application.csv \
  --application-row-limit 100 \
  --previous-row-limit 0 \
  --output-root benchmark_runs/home_credit_previous_loan_count \
  --run-name previous_loan_count_100 \
  --backend heir-generated-ckks \
  --heir-generated-dir /root/heir-work \
  --openfhe-dir "$HOME/openfhe-development/build" \
  --heir-vector-size 8192
```

This is not yet a privacy-preserving join between independent parties. It
assumes one trusted source can align its two tables. PSI or another record
linkage protocol is a later boundary when the tables originate from different
organizations.
