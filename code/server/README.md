# Server Code

This folder is the tracked server-side runtime area for the HE lending use case.

The server receives encrypted payloads and public/evaluation material, runs
privacy-preserving EDA-style computations, and returns encrypted aggregate
results. The server must not receive the client secret key or raw lending data.

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
server_binfhe_outlier_flags
server_policy_counts
server_rule_score
```

First executable:

- `numeric_summary/server_numeric_summary.cpp`
- computes encrypted sums for prepared numeric columns
- writes encrypted sum ciphertexts and a `summary_manifest.csv`

BinFHE outlier executable:

- `binfhe_outliers/server_binfhe_outlier_flags.cpp`
- evaluates encrypted bounded integer threshold rules
- returns encrypted 0/1 outlier flags
