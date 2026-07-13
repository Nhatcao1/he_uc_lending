# Home Credit HE EDA Implementation Tracker

Purpose: keep a precise implementation record for Home Credit EDA work from
`home-credit-complete-eda-feature-importance.ipynb`.

This file is report-oriented. It records what the trusted client prepares, what
is encrypted, what the HE server computes, what the trusted side decrypts, and
what still needs improvement.

## Execution Boundary

| Side | Responsibilities |
| --- | --- |
| Client / trusted data side | Read raw CSV, clean/normalize values, decide null policy, decide category/top-K/bin policy, create numeric vectors and 0/1 masks, encrypt with OpenFHE CKKS, keep secret key, decrypt aggregate results |
| HE server | Receive encrypted vectors, public/evaluation keys, and manifests; compute encrypted sums and masked sums; return encrypted aggregate result ciphertexts |
| Analysis / report side | Decrypt aggregate results in a trusted environment, compute final percentages/rates/means, create human-readable tables or charts |

The HE server does not parse raw CSV, inspect nulls, normalize strings, choose
categories, perform pandas groupby, sort values, draw plots, train RandomForest,
or decrypt results.

## Current Benchmark Harness

Main benchmark runner:

```text
code/benchmarks/home_credit_core_eda_benchmark.py
```

Core binaries used by the benchmark:

```text
build/encrypt_home_credit_payload
build/server_home_credit_aggregate
build/decrypt_ckks_results
```

Benchmark output:

```text
benchmark_runs/home_credit_core_eda/<run-name>/
  benchmark_summary.json
  <workload>_report.md
  plaintext_reference.csv
  decrypted.csv
  prepared/
  encrypted/
  keys/
  server_output/
```

`benchmark_summary.json` and the Markdown report include:

- plaintext Python reference time
- client preparation time
- OpenFHE context/key/eval-key/encryption time
- HE server aggregate time
- decrypt time
- artifact sizes, including encrypted vectors and evaluation keys
- correctness result comparing plaintext Python output with decrypted HE output

## OpenFHE Operation Patterns

| EDA pattern | Client encrypted inputs | HE server operations | Decrypted post-process |
| --- | --- | --- | --- |
| Count rows in a category | one 0/1 mask per category | `EvalSum(mask)` | `percent = count / total` |
| Default rate by category | category mask and `TARGET=1` mask | `EvalSum(mask)`, `EvalSum(EvalMultAndRelinearize(mask, target))` | `default_rate = default_count / count` |
| Numeric total / mean | numeric value vector and valid mask | `EvalSum(value * valid_mask)`, `EvalSum(valid_mask)` | `mean = sum / count` |
| Histogram / distribution table, CKKS fast path | one 0/1 mask per numeric bin, optional value vector | `EvalSum(bin_mask)`, optional `EvalSum(bin_mask * value)` | `percent`, optional `mean_per_bin` |
| Histogram / distribution table, FHEW comparison path | encrypted integer bits for numeric value, encrypted valid bit, plaintext min/max/bin count | encrypted comparisons against plaintext bin ranges, encrypted binary count accumulator | bin count and percent after decrypt |
| Correlation support | selected numeric vectors, valid masks | sums of `x`, `y`, `xy`, `x^2`, `y^2` | client computes correlation formula |

## Implemented And Benchmarking Now

These are the currently clean benchmark workloads. They map to notebook section
`5.14.x`, where the notebook compares categories against `TARGET`.

| Workload | Notebook intent | Source table | Client preparation | Encrypted artifacts needed | HE server calculation | Output table | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `app_target_by_education_type` | Education by target/default | `application_train.csv` | normalize `NAME_EDUCATION_TYPE`; create one mask per education label; create `TARGET=1` mask | education masks, target mask, context, public key, eval sum key, eval mult key | `sum(education_mask)`, `sum(education_mask * target_mask)` | education label, count, percent, default count, default rate | benchmarked full application table; correctness passed |
| `app_target_by_income_type` | Income type by target/default | `application_train.csv` | normalize `NAME_INCOME_TYPE`; create one mask per income label; create `TARGET=1` mask | income masks, target mask, context, public key, eval keys | `sum(income_mask)`, `sum(income_mask * target_mask)` | income label, count, percent, default count, default rate | implemented, next benchmark |
| `app_target_by_occupation_type` | Occupation by target/default | `application_train.csv` | normalize `OCCUPATION_TYPE`; use top-K plus missing/other policy; create masks; create `TARGET=1` mask | occupation masks, target mask, context, public key, eval keys | `sum(occupation_mask)`, `sum(occupation_mask * target_mask)` | occupation label, count, percent, default count, default rate | implemented, size-sensitive |

Current known issue: the benchmark still encrypts the broad prepared vector set
before filtering for one workload. This is correct but wasteful. For the full
application table, encrypted vectors can reach many GiB. The next optimization
is workload-specific preparation/encryption.

## 5.1 To 5.3 Numeric Distribution Plan

The original notebook uses plots for amount distributions. In HE, the report
should use decrypted aggregate tables. Charts can be created only after trusted
decryption.

| Notebook section | Original plot | Client preparation | HE server calculation | Report output | Status |
| --- | --- | --- | --- | --- | --- |
| 5.1 `AMT_CREDIT` | distribution plot | FHEW path: encrypt amount integer bits and valid bits only; source does not prepare bin masks | HE server compares encrypted values with plaintext bin ranges and accumulates encrypted count bits | bin, count, percent | experimental FHEW implementation |
| 5.2 `AMT_INCOME_TOTAL` | distribution plot | same as above, with income min/max metadata | same as above | same as above | planned after AMT_CREDIT |
| 5.3 `AMT_GOODS_PRICE` | distribution plot | same as above, with goods-price min/max metadata | same as above | same as above | planned after AMT_CREDIT |

Important design choice: there are now two numeric histogram paths.

- CKKS fast path: source prepares bin masks before encryption. Fast, but
  source-side mask preparation is heavy.
- FHEW comparison path: source sends encrypted integer bits and valid bits only.
  Analyzer/HE side provides plaintext min/max/bin count metadata, and the HE
  server computes encrypted bin membership and encrypted count bits. This is
  more aligned with a "black box source" model, but it is much slower and should
  start with small row limits.

Current FHEW limitation: the experimental path counts rows per bin. It does not
yet compute encrypted `sum(amount)` or `mean(amount)` per bin.

Experimental binaries:

```text
build/encrypt_home_credit_fhew_amt
build/server_home_credit_fhew_amt_bins
build/decrypt_home_credit_fhew_amt_bins
```

Minimal AMT_CREDIT FHEW flow:

```bash
./build/encrypt_home_credit_fhew_amt \
  --input data/home_credit/application_train.csv \
  --column AMT_CREDIT \
  --server-output-dir benchmark_runs/fhew_amt_credit/encrypted \
  --client-key-dir benchmark_runs/fhew_amt_credit/keys \
  --row-limit 5 \
  --bit-width 24 \
  --security TOY

./build/server_home_credit_fhew_amt_bins \
  --context benchmark_runs/fhew_amt_credit/encrypted/amt/fhew/cryptoContext.bin \
  --refresh-key benchmark_runs/fhew_amt_credit/encrypted/amt/fhew/refreshKey.bin \
  --switch-key benchmark_runs/fhew_amt_credit/encrypted/amt/fhew/ksKey.bin \
  --amount-manifest benchmark_runs/fhew_amt_credit/encrypted/amt/fhew/fhew_amt_amount_manifest.csv \
  --valid-manifest benchmark_runs/fhew_amt_credit/encrypted/amt/fhew/fhew_amt_valid_manifest.csv \
  --input-dir benchmark_runs/fhew_amt_credit/encrypted/amt/fhew \
  --output-dir benchmark_runs/fhew_amt_credit/server_output \
  --min 0 \
  --max 2000000 \
  --bin-count 3

./build/decrypt_home_credit_fhew_amt_bins \
  --context benchmark_runs/fhew_amt_credit/keys/fhew_crypto_context.bin \
  --secret-key benchmark_runs/fhew_amt_credit/keys/fhew_secret_key.bin \
  --manifest benchmark_runs/fhew_amt_credit/server_output/fhew_amt_bin_count_manifest.csv \
  --input-dir benchmark_runs/fhew_amt_credit/server_output \
  --output-csv benchmark_runs/fhew_amt_credit/decrypted_counts.csv
```

Tiny local smoke result: 5 rows, 3 bins, 24-bit amount values took about 20
seconds on the HE server path and produced matching decrypted bin counts. This
confirms feasibility, not scalability.

## 5.4 To 5.13 Category Count Plan

These notebook sections are simpler than 5.14. They need only encrypted
category counts, not default-rate multiplication.

| Notebook section | Candidate workload | Column(s) | Client preparation | HE server calculation | Output table | Status |
| --- | --- | --- | --- | --- | --- | --- |
| 5.4 Suite / accompanied client | `app_suite_type` | `NAME_TYPE_SUITE` | normalize category, missing bucket, one-hot masks | `sum(mask)` | label, count, percent | supported in broad flow, not clean benchmarked |
| 5.5 Target balance | `app_target_balance` | `TARGET` | create `TARGET=0` and `TARGET=1` masks | `sum(mask)` | target value, count, percent | supported in broad flow, not clean benchmarked |
| 5.6 Loan type | `app_loan_type` | `NAME_CONTRACT_TYPE` | one-hot masks | `sum(mask)` | label, count, percent | supported in broad flow, not clean benchmarked |
| 5.7 Own car / realty | `app_own_car_realty` | `FLAG_OWN_CAR`, `FLAG_OWN_REALTY` | one-hot masks for each flag | `sum(mask)` | flag, value, count, percent | supported in broad flow, not clean benchmarked |
| 5.8 Income type | `app_income_type` | `NAME_INCOME_TYPE` | one-hot masks | `sum(mask)` | label, count, percent | supported in broad flow, not clean benchmarked |
| 5.9 Family status | `app_family_status` | `NAME_FAMILY_STATUS` | one-hot masks | `sum(mask)` | label, count, percent | supported in broad flow, not clean benchmarked |
| 5.10 Occupation | `app_occupation_type` | `OCCUPATION_TYPE` | top-K plus missing/other masks | `sum(mask)` | label, count, percent | supported in broad flow, size-sensitive |
| 5.11 Education | `app_education_type` | `NAME_EDUCATION_TYPE` | one-hot masks | `sum(mask)` | label, count, percent | count is indirectly proven by 5.14 education benchmark |
| 5.12 Housing type | `app_housing_type` | `NAME_HOUSING_TYPE` | one-hot masks | `sum(mask)` | label, count, percent | supported in broad flow, not clean benchmarked |
| 5.13 Organization type | `app_organization_type` | `ORGANIZATION_TYPE` | top-K plus missing/other masks | `sum(mask)` | label, count, percent | supported in broad flow, size-sensitive |

Recommended next clean benchmark: implement workload-specific count-only
benchmarks for 5.4-5.13 after reducing bundle size. They should not require
`eval_mult_keys` unless the code path still uses masked numeric sums.

## 5.15 Previous Application EDA

These sections use `previous_application.csv`, which is larger than
`application_train.csv`. The current broad flow has mappings, but full-size HE
benchmarking is not yet practical without bundle-size optimization.

| Notebook area | Source table | Client preparation | HE server calculation | Risk |
| --- | --- | --- | --- | --- |
| previous contract type/status/reject reason/product/channel/etc. | `previous_application.csv` | normalize category fields, use top-K where needed, create one-hot masks | `sum(previous_mask)` | ciphertext volume grows quickly because the table has about 1.67M rows |

Recommended first previous-table benchmark:

```text
previous contract status count
```

Reason: it is business-readable, category cardinality is small, and it is a
natural bridge to future join/matching work.

## Correlation And Feature Importance

| Notebook area | HE interpretation | Status |
| --- | --- | --- |
| Pearson correlation heatmap | compute selected sufficient statistics: `sum(x)`, `sum(y)`, `sum(x*y)`, `sum(x^2)`, `sum(y^2)`; client decrypts and computes correlation | path exists, needs focused validation |
| RandomForest feature importance | not a direct HE target in this prototype; use trusted training and optional HE linear scoring demo | separate ML/scoring track |

## Required Improvements

1. Workload-specific preparation and encryption:
   - prepare only vectors needed by one EDA
   - avoid encrypting all Home Credit vectors for one report
2. Session artifact cache:
   - upload context, public/eval keys, and shared masks once
   - reference them by `dataset_session_id`
3. Shared vector reuse:
   - reuse `TARGET=1` mask across all 5.14 target-by-category EDA jobs
4. Size-aware reports:
   - keep artifact-size table in every benchmark report
   - track encrypted vectors, eval keys, and result bundle size
5. Streaming/chunked preparation:
   - avoid large in-memory prepared vectors
   - support resumable large-table runs
6. Optional threading:
   - add a controlled `--threads` path for server aggregate work
   - benchmark before/after with the same slot count and row count

## Reporting Rule

For every EDA case, keep this wording discipline:

```text
Original notebook graph/table:
HE equivalent:
Client preparation:
Encrypted artifacts:
HE server operations:
Trusted decrypted output:
Correctness check:
Performance metrics:
Known limitation:
```
