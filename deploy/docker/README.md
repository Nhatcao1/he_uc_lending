# Docker Server Stack

This stack is server-only. It runs:

- one-shot C++ builder service
- FastAPI web/API server
- RQ worker that invokes the C++ OpenFHE binaries
- Redis queue
- Nginx reverse proxy on port `8080` by default

The client should not use this stack for raw data prep or secret-key storage.

## Expected Server Paths

Set the host OpenFHE directory before starting:

```bash
export OPENFHE_HOST_DIR="$HOME/openfhe-development"
export OpenFHE_DIR="/opt/openfhe/build"
```

If your OpenFHE install is different, point `OPENFHE_HOST_DIR` at the host
directory and `OpenFHE_DIR` at the matching path inside the container that
contains `OpenFHEConfig.cmake`.

Examples:

```bash
export OPENFHE_HOST_DIR="$HOME/openfhe-install"
export OpenFHE_DIR="/opt/openfhe/lib/OpenFHE"
```

## Start

From the repo root:

```bash
export HE_RECEIVER_TOKEN="long-random-token"
export OPENFHE_HOST_DIR="$HOME/openfhe-development"
export OpenFHE_DIR="/opt/openfhe/build"
docker compose -f deploy/docker/docker-compose.async.yml up --build
```

On start, the `builder` service compiles:

```text
server_numeric_summary
server_home_credit_aggregate
server_linear_score
```

Then `web` and `worker` reuse the mounted `build/` directory.

Open:

```text
http://100.84.97.118:8080
```

or whatever host/port Docker exposes.

## Run Detached

```bash
docker compose -f deploy/docker/docker-compose.async.yml up --build -d
docker compose -f deploy/docker/docker-compose.async.yml logs -f web worker
```

## Stop

```bash
docker compose -f deploy/docker/docker-compose.async.yml down
```

## Skip C++ Build On Container Start

If the mounted `/app/build` already contains valid server binaries:

```bash
export HE_BUILD_ON_START=0
docker compose -f deploy/docker/docker-compose.async.yml up -d
```

With `HE_BUILD_ON_START=0`, the `builder` service exits without rebuilding.

## Important

Uploaded jobs and SQLite metadata are stored under:

```text
server_jobs/async
```

The server must still never receive:

```text
raw CSV
plaintext prepared vectors
secret_key.bin
decrypted reports
```
