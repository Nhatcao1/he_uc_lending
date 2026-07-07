# Docker Server Stack

This stack is server-only. It runs:

- FastAPI web/API server
- RQ worker that invokes the C++ OpenFHE binaries
- Redis queue
- Nginx reverse proxy on port `8080` by default

The client should not use this stack for raw data prep or secret-key storage.

## Expected Server Paths

Set the host OpenFHE directory before starting:

```bash
export OPENFHE_HOST_DIR="$HOME/openfhe-development"
```

The container mounts that host directory to both:

```text
/opt/openfhe
the same absolute host path, for example /root/openfhe-development
```

OpenFHE's generated CMake config can contain absolute host paths. Mounting the
tree at the same absolute path keeps those include/library paths valid inside
Docker. The entrypoint also searches the mounted tree for `OpenFHEConfig.cmake`.
If you want to set it manually, `OpenFHE_DIR` must be the container-side
directory that contains `OpenFHEConfig.cmake`.

Examples:

```bash
export OPENFHE_HOST_DIR="$HOME/openfhe-install"
export OpenFHE_DIR="/opt/openfhe/lib/OpenFHE"
```

Debug the host path with:

```bash
find "$HOME" -name OpenFHEConfig.cmake 2>/dev/null
```

## Start

From the repo root:

Before starting Docker, build the C++ OpenFHE server binaries on the host:

```bash
cmake -S . -B build -DOpenFHE_DIR=$HOME/openfhe-development/build
cmake --build build --target server_numeric_summary server_home_credit_aggregate server_linear_score
```

Then start the Docker web stack:

```bash
export HE_RECEIVER_TOKEN="long-random-token"
export OPENFHE_HOST_DIR="$HOME/openfhe-development"
docker compose -f deploy/docker/docker-compose.async.yml up --build
```

Docker mounts the host `build/` directory read-only at:

```text
/app/build
```

The worker uses those host-built binaries. Docker does not compile OpenFHE code
in the default path.

Open:

```text
http://100.84.97.118:8080
```

or whatever host/port Docker exposes.

For upload, select a small encrypted workload zip produced by:

```bash
python3 code/client/home_credit/package_home_credit_upload_bag.py \
  --encrypted-dir encrypted_payloads/home_credit_basic \
  --workload app_dist_amt_credit \
  --output-dir client_runs/home_credit_basic/server_uploads \
  --client-key-dir keys/home_credit_basic
```

The server extracts the zip, normalizes the bundle layout, and can auto-detect
the workload from `upload_bag_manifest.json`. Use notebook workload names such
as `app_target_by_income_type`, `prev_contract_status`,
`app_selected_correlation_stats`, or `linear_score_demo` for other smaller
upload artifacts. Only upload files from `server_uploads/`; `client_private/`
is the local decrypt key area.

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

The default Docker stack already skips C++ compilation:

```text
HE_BUILD_ON_START=0
```

Keep building C++ on the host until the OpenFHE container build path is worth
debugging again.

## Important

Uploaded jobs and SQLite metadata are stored under:

```text
server_jobs/async
```

Host-built C++ binaries are mounted from:

```text
build/
```

The server must still never receive:

```text
raw CSV
plaintext prepared vectors
secret_key.bin
decrypted reports
```
