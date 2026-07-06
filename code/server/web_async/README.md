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
select workload = Auto-detect from artifact
choose the encrypted payload folder
queue job
```

The server normalizes bundle paths, so a folder shaped like this is enough:

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

The API also accepts a zip of that folder. The server extracts the zip, blocks
raw/secret-looking paths, and auto-detects the workload when possible. If a
bundle contains artifacts for multiple workloads, choose the exact workload in
the dropdown.

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
