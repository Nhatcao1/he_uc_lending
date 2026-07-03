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

Implemented server executables:

```text
server_numeric_summary
server_home_credit_aggregate
server_linear_score
```

First executable:

- `numeric_summary/server_numeric_summary.cpp`
- computes encrypted sums for prepared numeric columns
- writes encrypted sum ciphertexts and a `summary_manifest.csv`

Aggregate executable:

- `home_credit_aggregate/server_home_credit_aggregate.cpp`
- computes encrypted `sum(mask)`, `sum(mask * target)`, and
  `sum(mask * amount)`
- supports `--analysis-filter category`, `bucket`, or `ratio`

Linear score executable:

- `linear_score/server_linear_score.cpp`
- computes encrypted CKKS weighted sums for exported linear/logistic models
