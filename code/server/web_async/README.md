# Async HE Web Server

FastAPI/RQ version of the HE job receiver.

It keeps HE math in C++ and only handles:

- encrypted artifact upload
- job metadata
- Redis/RQ queueing
- worker execution of existing OpenFHE binaries
- status/log/result pages

## Non-Docker Run

From the repo root on the HE server:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r code/server/web/requirements-async.txt
```

Start Redis separately:

```bash
redis-server
```

Build C++ binaries:

```bash
cmake -S . -B build -DOpenFHE_DIR=$HOME/openfhe-development/build
cmake --build build --target server_numeric_summary server_home_credit_aggregate server_linear_score
```

Run the web server:

```bash
export PYTHONPATH="$PWD/code/server/web_async"
export HE_REDIS_URL="redis://127.0.0.1:6379/0"
export HE_ASYNC_JOBS_DIR="$PWD/server_jobs/async"
export HE_ASYNC_BUILD_DIR="$PWD/build"
export HE_ASYNC_DB_PATH="$PWD/server_jobs/async/jobs.db"
export HE_RECEIVER_TOKEN="long-random-token"
uvicorn he_async_web.app:app --host 100.84.97.118 --port 8080
```

In a second terminal, run the worker:

```bash
export PYTHONPATH="$PWD/code/server/web_async"
export HE_REDIS_URL="redis://127.0.0.1:6379/0"
export HE_ASYNC_JOBS_DIR="$PWD/server_jobs/async"
export HE_ASYNC_BUILD_DIR="$PWD/build"
export HE_ASYNC_DB_PATH="$PWD/server_jobs/async/jobs.db"
python3 -m he_async_web.worker
```

Open:

```text
http://100.84.97.118:8080
```

## Docker Run

See:

```text
deploy/docker/README.md
```

## Pages

```text
/jobs/new
/jobs
/jobs/<job_id>
/results
```

## Upload UX

The submit page accepts one encrypted artifact bundle.

Recommended browser flow:

```text
select Notebook EDA criterion = Auto-detect from artifact
choose the encrypted criterion upload bag zip
queue job
```

Create that zip on the client:

```bash
python3 code/client/home_credit/package_home_credit_upload_bag.py \
  --encrypted-dir encrypted_payloads/home_credit_basic \
  --workload app_target_by_income_type \
  --output-dir client_runs/home_credit_basic/server_uploads \
  --client-key-dir keys/home_credit_basic
```

The server normalizes bundle paths, so a zip containing this layout is enough:

```text
encrypted_payloads/home_credit_basic/
  crypto_context.bin
  eval_sum_keys.bin
  eval_mult_keys.bin
  column_manifest.csv
  aggregate_manifest.csv
  score_manifest.csv
  columns/
  vectors/
  score_features/
```

The server extracts the zip, blocks raw/secret-looking paths, and auto-detects
the EDA criterion when possible. If a bundle contains artifacts for multiple
criteria, choose the exact criterion in the dropdown.

Current notebook criteria:

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
linear_score_demo
```

## API

```text
POST   /api/jobs
GET    /api/jobs
GET    /api/jobs/<job_id>
GET    /api/jobs/<job_id>/logs
GET    /api/jobs/<job_id>/download-bundle
POST   /api/jobs/<job_id>/cancel
GET    /api/workloads
GET    /api/results
```
