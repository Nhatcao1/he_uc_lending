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

Server now has three runnable OpenFHE jobs:

```text
server_numeric_summary
server_home_credit_aggregate
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
  --workload application_default_rates \
  --output-dir client_runs/home_credit_basic/server_uploads \
  --client-key-dir keys/home_credit_basic
```

This writes:

```text
client_runs/home_credit_basic/server_uploads/home_credit_application_default_rates.upload.zip
client_runs/home_credit_basic/client_private/<client_material_id>/secret_key.bin
client_runs/home_credit_basic/client_private/<client_material_id>/crypto_context.bin
client_runs/home_credit_basic/client_private/<client_material_id>/README_DO_NOT_UPLOAD.txt
```

The upload zip contains `upload_bag_manifest.json` with `client_material_id`,
`crypto_context_sha256`, and `public_key_sha256` when available. The server
copies that manifest into the returned result bundle, allowing the client
download helper to choose the matching local key material for decrypt.

Other criterion values:

```text
missing_data
target_balance
application_numeric_summary
application_category_counts
application_default_rates
application_numeric_histograms
previous_application_category_counts
previous_application_target_rates
selected_correlation_stats
linear_score_demo
all
```

The specific criterion zips include only the required encrypted artifacts:

```text
application_numeric_summary: crypto_context.bin, eval_sum_keys.bin, column_manifest.csv, columns/*.bin referenced by the manifest
all aggregate criteria: crypto_context.bin, eval_sum_keys.bin, eval_mult_keys.bin, filtered aggregate_manifest.csv, referenced vectors/*.bin
linear_score_demo: crypto_context.bin, score_manifest.csv, referenced score_features/*.bin
```

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

Application numeric summary:

```bash
./build/server_numeric_summary \
  --context encrypted_payloads/home_credit_basic/crypto_context.bin \
  --eval-sum-keys encrypted_payloads/home_credit_basic/eval_sum_keys.bin \
  --manifest encrypted_payloads/home_credit_basic/column_manifest.csv \
  --input-dir encrypted_payloads/home_credit_basic/columns \
  --output-dir server_returns/application_numeric_summary
```

Application category default-rate EDA:

```bash
./build/server_home_credit_aggregate \
  --context encrypted_payloads/home_credit_basic/crypto_context.bin \
  --eval-sum-keys encrypted_payloads/home_credit_basic/eval_sum_keys.bin \
  --eval-mult-keys encrypted_payloads/home_credit_basic/eval_mult_keys.bin \
  --manifest encrypted_payloads/home_credit_basic/aggregate_manifest.csv \
  --input-dir encrypted_payloads/home_credit_basic/vectors \
  --output-dir server_returns/application_default_rates \
  --analysis-filter application_default_rates
```

Application numeric histograms:

```bash
./build/server_home_credit_aggregate \
  --context encrypted_payloads/home_credit_basic/crypto_context.bin \
  --eval-sum-keys encrypted_payloads/home_credit_basic/eval_sum_keys.bin \
  --eval-mult-keys encrypted_payloads/home_credit_basic/eval_mult_keys.bin \
  --manifest encrypted_payloads/home_credit_basic/aggregate_manifest.csv \
  --input-dir encrypted_payloads/home_credit_basic/vectors \
  --output-dir server_returns/application_numeric_histograms \
  --analysis-filter application_numeric_histograms
```

Selected correlation stats:

```bash
./build/server_home_credit_aggregate \
  --context encrypted_payloads/home_credit_basic/crypto_context.bin \
  --eval-sum-keys encrypted_payloads/home_credit_basic/eval_sum_keys.bin \
  --eval-mult-keys encrypted_payloads/home_credit_basic/eval_mult_keys.bin \
  --manifest encrypted_payloads/home_credit_basic/aggregate_manifest.csv \
  --input-dir encrypted_payloads/home_credit_basic/vectors \
  --output-dir server_returns/selected_correlation_stats \
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

Decrypt application numeric summary:

```bash
./build/decrypt_ckks_results \
  --context encrypted_payloads/home_credit_basic/crypto_context.bin \
  --secret-key keys/home_credit_basic/secret_key.bin \
  --manifest server_returns/application_numeric_summary/summary_manifest.csv \
  --input-dir server_returns/application_numeric_summary \
  --output-csv server_returns/decrypted_application_numeric_summary.csv \
  --manifest-type numeric
```

Decrypt aggregate EDA criterion:

```bash
./build/decrypt_ckks_results \
  --context encrypted_payloads/home_credit_basic/crypto_context.bin \
  --secret-key keys/home_credit_basic/secret_key.bin \
  --manifest server_returns/application_default_rates/aggregate_summary_manifest.csv \
  --input-dir server_returns/application_default_rates \
  --output-csv server_returns/decrypted_application_default_rates.csv \
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
home_credit_target_balance
home_credit_application_numeric_summary
home_credit_application_category_counts
home_credit_application_default_rates
home_credit_application_numeric_histograms
home_credit_previous_application_category_counts
home_credit_previous_application_target_rates
home_credit_selected_correlation_stats
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
