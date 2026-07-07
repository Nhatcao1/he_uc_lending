# Home Credit Web App Plan

The web app is a thin receiver for encrypted Home Credit HE jobs.

It should not implement HE math. It should:

- show available Home Credit notebook EDA criteria
- show client-side preparation requirements
- validate required encrypted artifacts before submit
- store each upload under `server_jobs/web/<job_id>/work`
- invoke the matching C++ server executable
- expose a one-click encrypted result bundle zip
- expose job status and encrypted result downloads

## Active EDA Criteria

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

The page also shows a read-only current result view per EDA criterion. It
reports the latest job id, latest status, runtime, and output file count for
each criterion.

Workflow diagrams:

```text
docs/diagrams/README.md
```

Async web job architecture:

```text
docs/diagrams/07_async_web_job_architecture.md
docs/diagrams/07_async_web_job_architecture.svg
```

## Runtime

Manual async run:

```bash
export PYTHONPATH="$PWD/code/server/web_async"
export HE_ASYNC_BUILD_DIR="$PWD/build"
export HE_ASYNC_JOBS_DIR="$PWD/server_jobs/async"
export HE_ASYNC_DB_PATH="$PWD/server_jobs/async/jobs.db"
uvicorn he_async_web.app:app --host 100.84.97.118 --port 8080
```

Worker:

```bash
export PYTHONPATH="$PWD/code/server/web_async"
export HE_ASYNC_BUILD_DIR="$PWD/build"
export HE_ASYNC_JOBS_DIR="$PWD/server_jobs/async"
export HE_ASYNC_DB_PATH="$PWD/server_jobs/async/jobs.db"
python3 -m he_async_web.worker
```

Optional web token:

```bash
export HE_RECEIVER_TOKEN="long-random-token"
```

The token is only web access control. It is not an HE key.

## Next Web App Direction

The old no-dependency HTTP server is legacy. The active implementation is the
FastAPI/RQ async server because HE jobs can take too long for a user to submit a
bundle and stare at one page.

Move toward a small job platform:

```text
submit encrypted bundle -> queue job -> worker runs C++ HE binary
                         -> UI polls progress/logs
                         -> user downloads encrypted result bundle later
```

Keep the core HE work in C++:

```text
server_numeric_summary
server_home_credit_aggregate
server_linear_score
```

The web/API layer should orchestrate jobs only. It should not implement HE math.

## Recommended Stack

Use this stack for the next server-side iteration:

| Layer | Choice | Reason |
| --- | --- | --- |
| API/web backend | FastAPI `0.139.0` | Good Python API ergonomics, upload endpoints, typed request/response models, OpenAPI docs, and easy future SSE/WebSocket status streaming |
| ASGI server | Uvicorn `0.50.0` | Standard FastAPI runtime; use `uvicorn[standard]` for production-friendly extras |
| Job queue | Redis Queue / RQ `2.10.0` | Simple Redis-backed Python queue; enough for one server and one or more HE worker processes |
| Queue broker | Redis server `7.4-alpine` first | Conservative broker image; RQ only needs Redis >= 5, and redis-py supports Redis 7.4 |
| Redis client | redis-py `8.0.1` with `hiredis` | Current Python Redis client; faster parser through `redis[hiredis]` |
| Worker | Python RQ worker wrapper | Pulls queued job, validates files, invokes C++ OpenFHE executable with `subprocess`, records logs/status |
| Persistent metadata | SQLite + SQLAlchemy `2.0.51` | SQLite is enough for current single server; SQLAlchemy keeps a clean path to Postgres later |
| Artifact storage | Local filesystem volume first | Current `server_jobs/` layout already works; later swap to S3/MinIO-compatible object storage |
| Reverse proxy | Nginx stable `1.30.x` | Stable public/Tailscale HTTP entry point, upload size limits, timeout/proxy control, route to FastAPI |
| Deployment | Docker Compose | One command to run `web`, `worker`, `redis`, and optional `nginx` services on the HE server |
| UI | Jinja2 `3.1.6` templates + small HTMX/browser JS | Small multi-page app without a heavy frontend build step |

Server Python target:

```text
Python 3.12
```

Reason:

- the HE server already appears to have Python 3.12 available
- FastAPI, RQ, redis-py, Uvicorn, and SQLAlchemy all support Python 3.12
- avoid Python 3.14 for the server stack until every queue dependency clearly
  publishes Python 3.14 support

Server package file:

```text
code/server/web/requirements-async.txt
```

Implemented async server files:

```text
code/server/web_async/he_async_web/app.py
code/server/web_async/he_async_web/worker.py
code/server/web_async/he_async_web/runner.py
code/server/web_async/README.md
deploy/docker/docker-compose.async.yml
deploy/docker/Dockerfile.server
deploy/docker/nginx.conf
```

Pinned V1 packages:

```text
fastapi==0.139.0
uvicorn[standard]==0.50.0
rq==2.10.0
redis[hiredis]==8.0.1
Jinja2==3.1.6
python-multipart==0.0.32
pydantic-settings==2.14.2
SQLAlchemy==2.0.51
```

Container baseline:

```text
python:3.12-slim
redis:7.4-alpine
nginx:1.30-alpine or nginx:1.30.3-alpine
```

Nginx is optional for local/Tailscale testing. Add it when we want one stable
entry point, upload limits, timeouts, and later HTTPS.

Why not FastAPI `BackgroundTasks` for HE jobs:

- fine for short post-response work
- not ideal for heavy jobs that need durable queueing, retries, worker restart,
  and eventually multiple workers or multiple servers

Why not Celery yet:

- powerful, but more moving parts than we need now
- use Celery only if we outgrow RQ with scheduling, complex retries, or many
  queues/workers

## Recommended Pages

### 1. Submit Job

Route:

```text
/jobs/new
```

Purpose:

- choose Home Credit EDA criterion
- show upload contract
- upload encrypted bundle
- create job record
- enqueue job
- redirect to job detail page

Important: this page should return quickly after upload and queueing.

### 2. Job Monitor

Routes:

```text
/jobs
/jobs/<job_id>
```

Purpose:

- list queued/running/done/failed jobs
- show status, EDA criterion, created time, runtime, worker hostname
- show command being executed
- show last server log lines
- show output files when done
- provide `Download result bundle`

Status states:

```text
uploaded
queued
running
succeeded
failed
cancelled
expired
```

For V1, polling every 2-5 seconds is enough:

```text
GET /api/jobs/<job_id>
```

Later, add:

```text
GET /api/jobs/<job_id>/events
```

with Server-Sent Events for live logs/status.

### 3. Results

Routes:

```text
/results
/results/<job_id>
```

Purpose:

- show completed jobs only
- download encrypted result bundle
- show decrypt command template for the client
- show expected client output path

The server still does not decrypt anything.

## API Shape

Suggested API:

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

Job record:

```json
{
  "job_id": "20260705-120000-abcd1234",
  "job_type": "home_credit_application_default_rates",
  "status": "running",
  "created_at": "...",
  "started_at": "...",
  "finished_at": null,
  "input_bytes": 123456789,
  "output_bytes": 0,
  "worker": "he-worker-1",
  "command": ["./build/server_numeric_summary", "..."],
  "result_bundle": null,
  "error": null
}
```

## Worker Flow

Worker process:

```text
1. receive job id from RQ
2. load job metadata
3. validate required encrypted files
4. update status = running
5. execute matching C++ binary
6. stream stdout/stderr to server_log.txt
7. collect output files
8. create result bundle zip
9. update status = succeeded or failed
```

Concurrency rule for now:

```text
one HE worker process = one HE job at a time
```

Reason: OpenFHE jobs can be CPU/memory heavy. Add more workers only after
benchmarking memory use.

## Docker Compose Shape

Target services:

```text
web:
  FastAPI app
  handles upload/status/download pages

worker:
  RQ worker
  runs C++ OpenFHE binaries
  mounts same job/artifact volume

redis:
  queue broker

nginx:
  optional reverse proxy
  routes external traffic to web
  sets upload/timeouts
```

Implemented compose file:

```text
deploy/docker/docker-compose.async.yml
```

The default Docker route is:

```text
browser -> nginx:8080 -> FastAPI web:8000 -> Redis/RQ -> worker -> C++ OpenFHE binaries
```

The container image can build the server-side C++ OpenFHE binaries on start
when `HE_BUILD_ON_START=1`. It expects the server's OpenFHE tree to be mounted
into the container, usually:

```text
OPENFHE_HOST_DIR=$HOME/openfhe-development
OpenFHE_DIR=/opt/openfhe/build
```

Shared volumes:

```text
server_jobs/
build/
```

Future split:

```text
web server      -> API/UI only
worker server   -> OpenFHE binaries, CPU/RAM heavy
object storage  -> encrypted bundles/results
redis/postgres  -> queue and metadata
```

## Security Boundary

Even when the web app becomes nicer, the privacy rule does not change.

Server may store:

```text
encrypted payloads
public keys
evaluation keys
encrypted result bundles
job metadata
logs without plaintext row data
```

Server must not store:

```text
raw CSV
plaintext prepared vectors
secret key
decrypted report
```

## Implementation Phases

### Phase 1: Keep Current Server, Improve UX

- split current UI into submit, jobs, and results sections/pages
- keep direct background thread execution
- keep one-click result bundle

This is the smallest change.

### Phase 2: Add Queue And Worker

- add Redis + RQ
- submit page enqueues job and returns immediately
- worker invokes existing C++ binaries
- job monitor polls status/log endpoint

This is the recommended next real backend step.

### Phase 3: Docker Compose Server Stack

- containerize web
- containerize worker with OpenFHE runtime and built HE binaries
- run Redis container
- optionally put Nginx in front

This should be server-only. Do not deploy this stack on the client.

### Phase 4: Multi-Server Later

- move worker to dedicated HE compute host
- use shared object storage for encrypted artifacts
- keep client-side prep/encryption/key management outside server trust boundary

## Bundle Rule

Client sends encrypted artifacts and manifests only.

Never upload:

```text
raw CSV
plaintext prepared CSV
secret key
decrypted report
```

## Reference Notes

- FastAPI supports returning quickly while work continues through background
  tasks, but its own docs point to larger queue systems such as Celery for heavy
  background computation.
- RQ is a small Redis-backed queue where Python functions are enqueued and run
  asynchronously by workers.
- Docker Compose is useful here because it manages `web`, `worker`, `redis`,
  and optional `nginx` as one server stack.
- Nginx can proxy external HTTP requests to an internal app server with
  `proxy_pass`, and can later manage upload/timeouts/reverse-proxy concerns.
