# Web App Plan For Client And Server

## Goal

Build a simple HTTP workflow so the local client can send encrypted lending
payloads to the server at the Tailscale IP and receive encrypted EDA results.

The web layer should be boring. It should not implement HE math. It should only
move job bundles around and invoke the C++ OpenFHE binaries.

```text
Client web/CLI wrapper
  prepare data
  keygen/encrypt locally
  upload encrypted job bundle
  poll job status
  download encrypted result bundle
  decrypt locally

Server web receiver
  accept encrypted job bundle
  validate files
  run server_numeric_summary
  package encrypted results
  expose status/result
```

## Recommendation

Use Python first.

For the server receiver:

```text
FastAPI if installing dependencies is OK.
Python standard library http.server if zero-dependency is more important.
```

For the client:

```text
Python CLI first.
Optional tiny local web UI later.
```

The HE compute should stay in C++:

```text
OpenFHE C++ binaries:
  client_keygen
  client_encrypt
  server_numeric_summary
  client_decrypt
```

The web layer calls these binaries with `subprocess`.

## Framework Choice

| Option | Fit | Pros | Cons | Decision |
| --- | --- | --- | --- | --- |
| FastAPI | Best for V1 web receiver | Small code, good upload API, easy status endpoints, easy docs | Needs `fastapi` and `uvicorn` install | Recommended if server can install Python deps |
| Python stdlib HTTP | Good fallback | No dependencies, works anywhere Python exists | More manual multipart/upload handling, less ergonomic | Use if dependency install is annoying |
| Node.js | Fine but not better | Easy web APIs, good upload libraries | Adds npm dependency tree, no advantage for OpenFHE | Skip for now |
| Go | Strong production option | Single binary web server, good concurrency, easy deploy | More code, separate toolchain, still calls C++ binary | Later if receiver becomes important |
| Rust | Strong but heavier | Safe, fast, robust | More build friction, slower iteration | Not V1 |
| C++ native HTTP | Possible but wrong first move | Same language as OpenFHE | HTTP server, upload parsing, security handling become distractions | Avoid |

## Why Not C++ For Web

C++ should own HE compute. HTTP should be a thin orchestration layer.

Putting the web server in C++ would mean spending time on:

```text
HTTP routing
multipart upload parsing
auth headers
path traversal protection
tar extraction safety
job status storage
result download
logging
```

None of that benefits from being close to OpenFHE. It increases risk and slows
iteration.

## Deployment Boundary

Server listens only on Tailscale:

```text
100.84.97.118:8080
```

Use a shared bearer token:

```bash
export HE_RECEIVER_TOKEN="long-random-token"
```

Requests include:

```text
Authorization: Bearer <token>
```

This is enough for V1 because Tailscale already provides private network access.

## Job Bundle Contract

Client uploads one archive:

```text
job.tar.gz
  job.json
  crypto_context.bin
  eval_sum_keys.bin
  column_manifest.csv
  columns/
    loan_amnt_0000.bin
    annual_inc_0000.bin
    dti_0000.bin
    ...
```

`job.json`:

```json
{
  "job_type": "numeric_summary",
  "schema_version": 1,
  "serialization": "binary",
  "scheme": "CKKS",
  "manifest": "column_manifest.csv",
  "input_dir": "columns"
}
```

Do not include:

```text
secret key
raw CSV
decrypted values
client local config with secrets
```

Reject bundles containing suspicious names:

```text
secret
private
sk
raw
.ssh
```

## Result Bundle Contract

Server returns:

```text
result.tar.gz
  status.json
  summary_manifest.csv
  sums/
    loan_amnt.sum.bin
    annual_inc.sum.bin
    dti.sum.bin
    ...
  server_log.txt
```

`status.json`:

```json
{
  "job_id": "20260702-abc123",
  "job_type": "numeric_summary",
  "status": "done",
  "result": "result.tar.gz"
}
```

## API Design

Minimal endpoints:

```text
GET  /health
POST /jobs
GET  /jobs/{job_id}
GET  /jobs/{job_id}/result
```

`POST /jobs`:

```text
Input:
  multipart file field named "bundle"

Output:
  {"job_id": "...", "status": "queued"}
```

`GET /jobs/{job_id}`:

```text
Output:
  {"job_id": "...", "status": "queued|running|done|failed"}
```

`GET /jobs/{job_id}/result`:

```text
Output:
  result.tar.gz
```

## Server Runtime Layout

Ignored by git:

```text
server_jobs/
  incoming/
  running/
  done/
  failed/
```

For each job:

```text
server_jobs/running/<job_id>/
  input/job.tar.gz
  work/
    crypto_context.bin
    eval_sum_keys.bin
    column_manifest.csv
    columns/
  output/
    summary_manifest.csv
    *.sum.bin
  server_log.txt
```

## Server Command

The receiver invokes:

```bash
./build/server_numeric_summary \
  --context <work>/crypto_context.bin \
  --eval-sum-keys <work>/eval_sum_keys.bin \
  --manifest <work>/column_manifest.csv \
  --input-dir <work>/columns \
  --output-dir <work>/output
```

Then it packages `<work>/output` into `result.tar.gz`.

## Client Flow

V1 client can be a CLI:

```bash
python3 code/client/prepare_lending_payload.py
./build/client_keygen ...
./build/client_encrypt ...
python3 code/client/upload_job.py \
  --server http://100.84.97.118:8080 \
  --bundle encrypted_payloads/job.tar.gz
python3 code/client/download_result.py \
  --server http://100.84.97.118:8080 \
  --job-id <job_id>
./build/client_decrypt ...
```

Later, a local client web UI can wrap these same commands.

## Implementation Order

1. Track server receiver code:

```text
code/server/receiver/receiver.py
code/server/receiver/README.md
```

2. Add server ignored runtime path:

```text
server_jobs/
```

3. Add simple upload validation:

```text
max file size
required files
allowed job_type
safe tar extraction
reject secret-key-looking filenames
```

4. Add client upload/download helpers under tracked `code/client/` only if we
decide client code should be cloned on both machines. Keep data, keys, and
payloads ignored.

5. Add optional local client web UI after CLI works.

## Decision For This Project

Use:

```text
FastAPI receiver on server
Python CLI client first
C++ OpenFHE binaries for all HE operations
Tailscale IP for transport
Bearer token for V1 auth
```

This keeps the system practical:

```text
Python = web/job orchestration
C++ = HE compute
Tailscale = private network
Git = code only
Ignored folders = data, keys, payloads, server jobs
```

