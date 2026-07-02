# Server Code

This folder is the tracked server-side runtime area for the Home Credit HE use
case.

The server receives encrypted payloads and public/evaluation material, runs
privacy-preserving EDA-style computations, and returns encrypted aggregate
results. The server must not receive the client secret key or raw Home Credit
data.

Local-only folders ignored by git:

- `code/client/`
- `data/`
- `keys/`
- `ciphertexts/`
- `encrypted_payloads/`
- `server_returns/`

Planned server executables:

```text
server_numeric_summary
server_home_credit_category_eda
server_home_credit_bucket_eda
server_home_credit_ratio_eda
```

First executable:

- `numeric_summary/server_numeric_summary.cpp`
- computes encrypted sums for prepared numeric columns
- writes encrypted sum ciphertexts and a `summary_manifest.csv`
