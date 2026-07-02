# HE Job Web Receiver

Tiny no-dependency web interface for submitting encrypted HE jobs to the server.

The receiver does not do HE math itself. It stores encrypted artifacts under
`server_jobs/web/<job_id>/work`, invokes the existing C++ server executable, and
shows status/output files.

The page is organized as:

- job catalog for Lending and Home Credit workflows
- selected workflow requirements
- encrypted artifact upload validation
- server job status and encrypted result downloads

## Run

```bash
python3 code/server/web/he_job_server.py \
  --host 0.0.0.0 \
  --port 8080 \
  --build-dir build
```

For Tailscale-only V1:

```bash
export HE_RECEIVER_TOKEN="long-random-token"
python3 code/server/web/he_job_server.py --host 100.84.97.118 --port 8080
```

For always-running server deployment, use:

```bash
deploy/systemd/install_he_job_service.sh "$USER" "$PWD"
```

Then start it with:

```bash
sudo systemctl start he-uc-lending@$USER.service
```

Open:

```text
http://100.84.97.118:8080
```

## Supported Job Types

```text
ckks_numeric_summary
binfhe_outlier_flags
home_credit_category_eda   planned UI placeholder only
```

## BinFHE Outlier Upload

Upload these files:

```text
binfhe_context.bin
binfhe_refresh_key.bin
binfhe_switch_key.bin
outlier_ciphertexts.csv
columns/
```

The UI preserves files under `columns/` and saves top-level files by basename.
The server runs:

```bash
./build/server_binfhe_outlier_flags \
  --context <work>/binfhe_context.bin \
  --refresh-key <work>/binfhe_refresh_key.bin \
  --switch-key <work>/binfhe_switch_key.bin \
  --manifest <work>/outlier_ciphertexts.csv \
  --input-dir <work>/columns \
  --output-dir <work>/output/binfhe_outliers
```

## CKKS Numeric Summary Upload

Upload these files:

```text
crypto_context.bin
eval_sum_keys.bin
column_manifest.csv
columns/
```

The server runs:

```bash
./build/server_numeric_summary \
  --context <work>/crypto_context.bin \
  --eval-sum-keys <work>/eval_sum_keys.bin \
  --manifest <work>/column_manifest.csv \
  --input-dir <work>/columns \
  --output-dir <work>/output/numeric_summary
```

## Security Boundaries

Do not upload:

```text
secret_key.bin
private keys
raw CSVs
plaintext prepared CSVs
```

The receiver blocks paths containing `secret`, `private`, `raw`, `.ssh`, or
`id_rsa`. Secret keys must remain on the client.
