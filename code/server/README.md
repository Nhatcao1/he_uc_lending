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
server_missing_counts
server_policy_counts
server_rule_score
```

Input/output contract will be added once the first OpenFHE C++ command is
implemented.

