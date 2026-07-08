# Home Credit Join Matching Commands

This covers the merge-aware timing jobs:

```text
join_hmac_prev_contract_status
join_psi_prev_contract_status
```

Both jobs use the same encrypted previous-application status masks. The
difference is how the matched `SK_ID_CURR` token set is produced.

## Server Pull, Build, Run

```bash
cd ~/he_uc_lending
git pull

cmake -S . -B build -DOpenFHE_DIR=$HOME/openfhe-development/build
cmake --build build --target server_home_credit_token_join_aggregate server_home_credit_aggregate server_numeric_summary server_linear_score

docker compose -f deploy/docker/docker-compose.async.yml up --build -d
```

Open:

```text
http://100.84.97.118:8080
```

## Optional PSI Install On Server

Keep PSI separate from OpenFHE. OpenFHE runs encrypted numeric computation; PSI
only produces/private-confirms matched IDs or matched tokens.

Lightweight Python package path:

```bash
cd ~/he_uc_lending
python3 -m venv .venv-psi
source .venv-psi/bin/activate
python -m pip install --upgrade pip
python -m pip install openmined-psi
python - <<'PY'
import private_set_intersection.python as psi
print("openmined-psi import ok")
print(psi.__file__)
print([name for name in ("client", "server", "psi", "Request", "Response", "ServerSetup") if hasattr(psi, name)])
PY
```

The PyPI package name is `openmined-psi`, but the import path is:

```python
import private_set_intersection.python as psi
```

Heavier upstream C++ benchmark path, only if needed:

```bash
sudo apt update
sudo apt install -y git build-essential clang cmake ninja-build pkg-config curl zip unzip tar python3 python3-venv python3-pip openjdk-17-jdk

sudo curl -L \
  -o /usr/local/bin/bazel \
  https://github.com/bazelbuild/bazelisk/releases/latest/download/bazelisk-linux-amd64
sudo chmod +x /usr/local/bin/bazel
bazel version

cd ~
git clone https://github.com/OpenMined/PSI.git openmined-psi
cd openmined-psi
bazel build -c opt //private_set_intersection/cpp/...
bazel run -c opt //private_set_intersection/cpp:psi_benchmark
```

## Client Prepare

Quick same-size timing fixture without external PSI output:

```bash
python3 code/client/home_credit/prepare_home_credit_basic_eda.py \
  --input data/home_credit/application_train.csv \
  --previous-application data/home_credit/previous_application.csv \
  --output-dir prepared_payloads/home_credit_basic \
  --row-limit 1000 \
  --previous-row-limit 1000 \
  --join-secret "replace-this-demo-join-secret"
```

If a PSI process has already produced matched HMAC tokens, pass them in:

```bash
python3 code/client/home_credit/prepare_home_credit_basic_eda.py \
  --input data/home_credit/application_train.csv \
  --previous-application data/home_credit/previous_application.csv \
  --output-dir prepared_payloads/home_credit_basic \
  --row-limit 1000 \
  --previous-row-limit 1000 \
  --join-secret "replace-this-demo-join-secret" \
  --psi-matched-token-file client_runs/home_credit_basic/psi/matched_tokens.csv
```

The matched token file is newline or CSV format with one HMAC token per row.
Do not put raw `SK_ID_CURR` values in it.

## Client Encrypt Once

```bash
./build/encrypt_home_credit_payload \
  --prepared-dir prepared_payloads/home_credit_basic \
  --server-output-dir encrypted_payloads/home_credit_basic \
  --client-key-dir keys/home_credit_basic \
  --slots 4096
```

## Package Both Join Jobs

```bash
for workload in \
  join_hmac_prev_contract_status \
  join_psi_prev_contract_status
do
  python3 code/client/home_credit/package_home_credit_upload_bag.py \
    --encrypted-dir encrypted_payloads/home_credit_basic \
    --workload "$workload" \
    --output-dir client_runs/home_credit_basic/server_uploads \
    --client-key-dir keys/home_credit_basic
done
```

Upload these two zip files through the server web UI:

```text
client_runs/home_credit_basic/server_uploads/home_credit_join_hmac_prev_contract_status.upload.zip
client_runs/home_credit_basic/server_uploads/home_credit_join_psi_prev_contract_status.upload.zip
```

## Client Result Dashboard

```bash
python3 code/client/home_credit/result_client_dashboard.py \
  --server http://100.84.97.118:8080 \
  --port 8090
```

Open:

```text
http://127.0.0.1:8090
```

Use the server job runtime columns to compare the two matching paths. The HE
operation is intentionally the same, so any extra PSI timing should be recorded
as PSI preparation time, not CKKS evaluation time.
