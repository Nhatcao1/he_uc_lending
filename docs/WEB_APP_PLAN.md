# Home Credit Web App Plan

The web app is a thin receiver for encrypted Home Credit HE jobs.

It should not implement HE math. It should:

- show available Home Credit workflows
- show client-side preparation requirements
- validate required encrypted artifacts before submit
- store each upload under `server_jobs/web/<job_id>/work`
- invoke the matching C++ server executable
- expose job status and encrypted result downloads

## Active Workflows

```text
home_credit_numeric_summary
home_credit_category_eda
home_credit_bucket_eda
home_credit_domain_ratio_eda
home_credit_linear_score
```

The page also shows a read-only current result view per use case. It reports
the latest job id, latest status, and output file count for each workflow.

Workflow diagrams:

```text
docs/diagrams/README.md
```

## Runtime

Manual run:

```bash
python3 code/server/web/he_job_server.py \
  --host 100.84.97.118 \
  --port 8080 \
  --build-dir build
```

Optional web token:

```bash
export HE_RECEIVER_TOKEN="long-random-token"
```

The token is only web access control. It is not an HE key.

## Bundle Rule

Client sends encrypted artifacts and manifests only.

Never upload:

```text
raw CSV
plaintext prepared CSV
secret key
decrypted report
```
