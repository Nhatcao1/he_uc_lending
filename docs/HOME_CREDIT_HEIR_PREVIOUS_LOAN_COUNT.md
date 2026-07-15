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
