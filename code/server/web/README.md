# HE Job Web Receiver

Tiny no-dependency web interface for submitting encrypted HE jobs to the server.

The receiver does not do HE math itself. It stores encrypted artifacts under
`server_jobs/web/<job_id>/work`, invokes the existing C++ server executable, and
shows status/output files.

The page is organized as:

- job catalog for Home Credit workflows
- selected workflow requirements
- encrypted artifact upload validation
- read-only use-case result summary
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
sudo systemctl start he-uc-credit@$USER.service
```

Open:

```text
http://100.84.97.118:8080
```

## Supported Job Types

```text
home_credit_numeric_summary
home_credit_category_eda
home_credit_bucket_eda
home_credit_domain_ratio_eda
home_credit_linear_score
```

## Home Credit Numeric Summary Upload

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

## Aggregate EDA Upload

Category, bucket, and ratio EDA use the same encrypted aggregate executable with
a different analysis filter.

Upload these files:

```text
crypto_context.bin
eval_sum_keys.bin
eval_mult_keys.bin
aggregate_manifest.csv
vectors/
```

The server runs `server_home_credit_aggregate` and returns:

```text
aggregate_summary_manifest.csv
aggregates/*.bin
```

## Linear Score Upload

Upload these files:

```text
crypto_context.bin
score_manifest.csv
score_features/
```

The server runs `server_linear_score` and returns:

```text
score_summary_manifest.csv
scores/*.bin
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
