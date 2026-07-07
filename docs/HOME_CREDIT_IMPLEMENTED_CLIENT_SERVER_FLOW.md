# Home Credit Implemented Client/Server Flow

This is the implementation map for the current Home Credit HE prototype.

Visual diagrams:

```text
docs/diagrams/README.md
```

## What Changed On Client

Client now has Home Credit preparation and CKKS helper tools:

```text
code/client/home_credit/prepare_home_credit_basic_eda.py
code/client/home_credit/train_home_credit_linear_model.py
code/client/ckks_tools/encrypt_home_credit_payload.cpp
code/client/ckks_tools/decrypt_ckks_results.cpp
```

Client responsibilities:

- load raw `application_train.csv`
- prepare numeric vectors, category masks, bucket masks, ratio masks, and ML
  feature vectors
- keep category/null/top-K policy local
- optionally train/export a small plaintext logistic regression model
- encrypt prepared vectors with CKKS
- keep `secret_key.bin` local
- decrypt returned aggregate or score results

Client must not upload:

```text
raw CSV
plaintext prepared vectors
secret_key.bin
decrypted reports
```

## What Changed On Server

Server now has four runnable OpenFHE jobs:

```text
server_numeric_summary
server_home_credit_aggregate
server_home_credit_token_join_aggregate
server_linear_score
```

Server responsibilities:

- accept encrypted bundles and manifests
- validate required files
- run encrypted aggregate or encrypted score math
- return encrypted result ciphertexts and result manifests

Server still does not do:

- pandas EDA
- raw CSV parsing
- string parsing
- null handling
- category selection
- final plaintext report calculation
- secret-key operations

## Build

From repo root:

```bash
cmake -S . -B build -DOpenFHE_DIR=$HOME/openfhe-development/build
cmake --build build
```

If using installed OpenFHE:

```bash
cmake -S . -B build -DOpenFHE_DIR=$HOME/openfhe-install/lib/OpenFHE
cmake --build build
```

Built executables:

```text
server_numeric_summary
server_home_credit_aggregate
server_linear_score
encrypt_home_credit_payload
decrypt_ckks_results
```

## Client Preparation

Optional trained linear model:

```bash
python3 code/client/home_credit/train_home_credit_linear_model.py \
  --input data/home_credit/application_train.csv \
  --output models/home_credit_linear_score_model.json
```

Prepare all basic Home Credit vectors:

```bash
python3 code/client/home_credit/prepare_home_credit_basic_eda.py \
  --input data/home_credit/application_train.csv \
  --previous-application data/home_credit/previous_application.csv \
  --output-dir prepared_payloads/home_credit_basic \
  --model-json models/home_credit_linear_score_model.json
```

For a quick smoke test, add:

```bash
--row-limit 1000
```

Prepared local files:

```text
prepared_payloads/home_credit_basic/vector_manifest.csv
prepared_payloads/home_credit_basic/aggregate_operations.csv
prepared_payloads/home_credit_basic/numeric_vectors.csv
prepared_payloads/home_credit_basic/linear_score_vectors.csv
prepared_payloads/home_credit_basic/vectors/*.csv
prepared_payloads/home_credit_basic/join/hmac/*.csv
prepared_payloads/home_credit_basic/join/psi/*.csv
```

These are plaintext local artifacts and should not be uploaded to the server.

## Client Encryption

Encrypt prepared vectors into a server bundle:

```bash
./build/encrypt_home_credit_payload \
  --prepared-dir prepared_payloads/home_credit_basic \
  --server-output-dir encrypted_payloads/home_credit_basic \
  --client-key-dir keys/home_credit_basic \
  --slots 4096
```

Server-uploadable encrypted files:

```text
encrypted_payloads/home_credit_basic/crypto_context.bin
encrypted_payloads/home_credit_basic/public_key.bin
encrypted_payloads/home_credit_basic/eval_sum_keys.bin
encrypted_payloads/home_credit_basic/eval_mult_keys.bin
encrypted_payloads/home_credit_basic/column_manifest.csv
encrypted_payloads/home_credit_basic/aggregate_manifest.csv
encrypted_payloads/home_credit_basic/score_manifest.csv
encrypted_payloads/home_credit_basic/columns/*.bin
encrypted_payloads/home_credit_basic/vectors/*.bin
encrypted_payloads/home_credit_basic/score_features/*.bin
encrypted_payloads/home_credit_basic/join/hmac/*.csv
encrypted_payloads/home_credit_basic/join/psi/*.csv
```

Client-only secret:

```text
keys/home_credit_basic/secret_key.bin
```

## Client Upload Packaging

Create a small upload zip for one notebook EDA criterion from the encrypted
output folder:

```bash
python3 code/client/home_credit/package_home_credit_upload_bag.py \
  --encrypted-dir encrypted_payloads/home_credit_basic \
  --workload app_target_by_income_type \
  --output-dir client_runs/home_credit_basic/server_uploads \
  --client-key-dir keys/home_credit_basic
```

This writes:

```text
client_runs/home_credit_basic/server_uploads/home_credit_app_target_by_income_type.upload.zip
client_runs/home_credit_basic/client_private/<client_material_id>/secret_key.bin
client_runs/home_credit_basic/client_private/<client_material_id>/crypto_context.bin
client_runs/home_credit_basic/client_private/<client_material_id>/README_DO_NOT_UPLOAD.txt
```

The upload zip contains `upload_bag_manifest.json` with `client_material_id`,
`crypto_context_sha256`, and `public_key_sha256` when available. The server
copies that manifest into the returned result bundle, allowing the client
download helper to choose the matching local key material for decrypt.

Notebook criterion values:

```text
missing_data
app_dist_amt_credit
app_dist_amt_income_total
app_dist_amt_goods_price
app_suite_type
app_target_balance
app_loan_type
app_own_car_realty
app_income_type
app_family_status
app_occupation_type
app_education_type
app_housing_type
app_organization_type
app_target_by_income_type
app_target_by_family_status
app_target_by_occupation_type
app_target_by_education_type
app_target_by_housing_type
app_target_by_organization_type
app_target_by_suite_type
prev_contract_type
prev_weekday_process_start
prev_cash_loan_purpose
prev_contract_status
prev_payment_type
prev_reject_reason
prev_suite_type
prev_client_type
prev_goods_category
prev_portfolio
prev_product_type
prev_channel_type
prev_seller_industry
prev_yield_group
prev_product_combination
prev_insured_on_approval
app_selected_correlation_stats
join_hmac_prev_contract_status
join_psi_prev_contract_status
linear_score_demo
all
```

The specific criterion zips include only the required encrypted artifacts:

```text
app_dist_*: crypto_context.bin, eval_sum_keys.bin, filtered column_manifest.csv, referenced columns/*.bin
category/target/previous/correlation criteria: crypto_context.bin, eval_sum_keys.bin, eval_mult_keys.bin, filtered aggregate_manifest.csv, referenced vectors/*.bin
linear_score_demo: crypto_context.bin, score_manifest.csv, referenced score_features/*.bin
join_*: crypto_context.bin, eval keys, filtered aggregate_manifest.csv, referenced encrypted vectors/*.bin, token CSVs
```

## Merge-Aware Join Timing Workloads

The merge-aware proof-of-concept follows the manual feature engineering
notebooks' pattern: connect `previous_application.SK_ID_CURR` to the current
`application_train.SK_ID_CURR` population, then count previous contract status.

Two upload workloads are available over the same data size:

```text
join_hmac_prev_contract_status
join_psi_prev_contract_status
```

Both run the same CKKS server binary:

```text
server_home_credit_token_join_aggregate
```

The difference is the source of the matched token set:

| Workload | Match source | Server sees | HE operation |
| --- | --- | --- | --- |
| `join_hmac_prev_contract_status` | Local HMAC tokens from `SK_ID_CURR` | deterministic HMAC tokens, encrypted status masks | plaintext token selection mask times encrypted one-hot status mask, then `EvalSum` |
| `join_psi_prev_contract_status` | PSI output token file when supplied; local fixture otherwise | PSI-matched tokens, encrypted status masks | same CKKS work as HMAC path for fair timing |

Production PSI should create the matched token file before `prepare`. For
workflow testing without PSI installed, omit `--psi-matched-token-file`; the
prepare script writes a same-size local fixture and marks that in
`join/join_manifest.json`.

Use `all` only when you want the larger compatibility bundle for every current
criterion.

## Client Download Helper

After a web job finishes, download all encrypted result files in one command:

```bash
python3 code/client/home_credit/download_job_bundle.py \
  --server http://100.84.97.118:8080 \
  --job-id latest
```

If the web receiver uses `HE_RECEIVER_TOKEN`, add:

```bash
--token <token>
```

The helper saves:

```text
client_runs/home_credit_basic/server_returns/<job_id>/he_result_<job_id>.zip
client_runs/home_credit_basic/server_returns/<job_id>/job_status.json
client_runs/home_credit_basic/server_returns/<job_id>/server_log.txt
client_runs/home_credit_basic/server_returns/<job_id>/<criterion output files>
```

It also prints the matching `decrypt_ckks_results` command.

## Server Jobs

Notebook 5.1 `AMT_CREDIT` distribution:

```bash
./build/server_numeric_summary \
  --context encrypted_payloads/home_credit_basic/crypto_context.bin \
  --eval-sum-keys encrypted_payloads/home_credit_basic/eval_sum_keys.bin \
  --manifest encrypted_payloads/home_credit_basic/column_manifest.csv \
  --input-dir encrypted_payloads/home_credit_basic/columns \
  --output-dir server_returns/app_dist_amt_credit
```

Notebook 5.14.1 income type by target:

```bash
./build/server_home_credit_aggregate \
  --context encrypted_payloads/home_credit_basic/crypto_context.bin \
  --eval-sum-keys encrypted_payloads/home_credit_basic/eval_sum_keys.bin \
  --eval-mult-keys encrypted_payloads/home_credit_basic/eval_mult_keys.bin \
  --manifest encrypted_payloads/home_credit_basic/aggregate_manifest.csv \
  --input-dir encrypted_payloads/home_credit_basic/vectors \
  --output-dir server_returns/app_target_by_income_type \
  --analysis-filter application_default_rates
```

Notebook 5.15.4 previous contract status:

```bash
./build/server_home_credit_aggregate \
  --context encrypted_payloads/home_credit_basic/crypto_context.bin \
  --eval-sum-keys encrypted_payloads/home_credit_basic/eval_sum_keys.bin \
  --eval-mult-keys encrypted_payloads/home_credit_basic/eval_mult_keys.bin \
  --manifest encrypted_payloads/home_credit_basic/aggregate_manifest.csv \
  --input-dir encrypted_payloads/home_credit_basic/vectors \
  --output-dir server_returns/prev_contract_status \
  --analysis-filter previous_application_category_counts
```

Selected correlation stats:

```bash
./build/server_home_credit_aggregate \
  --context encrypted_payloads/home_credit_basic/crypto_context.bin \
  --eval-sum-keys encrypted_payloads/home_credit_basic/eval_sum_keys.bin \
  --eval-mult-keys encrypted_payloads/home_credit_basic/eval_mult_keys.bin \
  --manifest encrypted_payloads/home_credit_basic/aggregate_manifest.csv \
  --input-dir encrypted_payloads/home_credit_basic/vectors \
  --output-dir server_returns/app_selected_correlation_stats \
  --analysis-filter selected_correlation_stats
```

Linear score demo:

```bash
./build/server_linear_score \
  --context encrypted_payloads/home_credit_basic/crypto_context.bin \
  --manifest encrypted_payloads/home_credit_basic/score_manifest.csv \
  --input-dir encrypted_payloads/home_credit_basic/score_features \
  --output-dir server_returns/linear_score_demo
```

## Client Decryption

Decrypt notebook 5.1 `AMT_CREDIT` distribution:

```bash
./build/decrypt_ckks_results \
  --context encrypted_payloads/home_credit_basic/crypto_context.bin \
  --secret-key keys/home_credit_basic/secret_key.bin \
  --manifest server_returns/app_dist_amt_credit/summary_manifest.csv \
  --input-dir server_returns/app_dist_amt_credit \
  --output-csv server_returns/decrypted_app_dist_amt_credit.csv \
  --manifest-type numeric
```

Decrypt aggregate EDA criterion:

```bash
./build/decrypt_ckks_results \
  --context encrypted_payloads/home_credit_basic/crypto_context.bin \
  --secret-key keys/home_credit_basic/secret_key.bin \
  --manifest server_returns/app_target_by_income_type/aggregate_summary_manifest.csv \
  --input-dir server_returns/app_target_by_income_type \
  --output-csv server_returns/decrypted_app_target_by_income_type.csv \
  --manifest-type aggregate
```

Decrypt linear score demo:

```bash
./build/decrypt_ckks_results \
  --context encrypted_payloads/home_credit_basic/crypto_context.bin \
  --secret-key keys/home_credit_basic/secret_key.bin \
  --manifest server_returns/linear_score_demo/score_summary_manifest.csv \
  --input-dir server_returns/linear_score_demo \
  --output-csv server_returns/decrypted_linear_score_demo.csv \
  --manifest-type score
```

For aggregate EDA, the decrypted file contains counts and sums. The final
readable report is still client-side:

```text
default_rate = default_count / count
average_amount = masked_sum / count
```

For linear scoring, the decrypted score is a logit-like score. If it came from
`train_home_credit_linear_model.py`, the client may apply:

```text
probability = 1 / (1 + exp(-score))
```

## Web Receiver

The web receiver now lists runnable EDA criteria:

```text
home_credit_missing_data
home_credit_app_dist_amt_credit
home_credit_app_dist_amt_income_total
home_credit_app_dist_amt_goods_price
home_credit_app_suite_type
home_credit_app_target_balance
home_credit_app_loan_type
home_credit_app_own_car_realty
home_credit_app_income_type
home_credit_app_family_status
home_credit_app_occupation_type
home_credit_app_education_type
home_credit_app_housing_type
home_credit_app_organization_type
home_credit_app_target_by_income_type
home_credit_app_target_by_family_status
home_credit_app_target_by_occupation_type
home_credit_app_target_by_education_type
home_credit_app_target_by_housing_type
home_credit_app_target_by_organization_type
home_credit_app_target_by_suite_type
home_credit_prev_contract_type
home_credit_prev_weekday_process_start
home_credit_prev_cash_loan_purpose
home_credit_prev_contract_status
home_credit_prev_payment_type
home_credit_prev_reject_reason
home_credit_prev_suite_type
home_credit_prev_client_type
home_credit_prev_goods_category
home_credit_prev_portfolio
home_credit_prev_product_type
home_credit_prev_channel_type
home_credit_prev_seller_industry
home_credit_prev_yield_group
home_credit_prev_product_combination
home_credit_prev_insured_on_approval
home_credit_app_selected_correlation_stats
home_credit_linear_score_demo
```

It also exposes a simple read-only result view:

```text
/api/results
```

Manual run:

```bash
export PYTHONPATH="$PWD/code/server/web_async"
export HE_ASYNC_BUILD_DIR="$PWD/build"
export HE_ASYNC_JOBS_DIR="$PWD/server_jobs/async"
export HE_ASYNC_DB_PATH="$PWD/server_jobs/async/jobs.db"
uvicorn he_async_web.app:app --host 100.84.97.118 --port 8080
```

In another terminal:

```bash
export PYTHONPATH="$PWD/code/server/web_async"
export HE_ASYNC_BUILD_DIR="$PWD/build"
export HE_ASYNC_JOBS_DIR="$PWD/server_jobs/async"
export HE_ASYNC_DB_PATH="$PWD/server_jobs/async/jobs.db"
python3 -m he_async_web.worker
```

Upload a criterion zip from `client_runs/home_credit_basic/server_uploads/`, not
the plaintext prepared files or `client_private/`.

Completed jobs can be downloaded as one zip from:

```text
/api/jobs/<job_id>/download-bundle
```
