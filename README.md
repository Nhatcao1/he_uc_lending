# HE UC Credit

Planning and prototype workspace for homomorphic-encryption use cases around
credit-risk EDA.

Current focus:

- Home Credit `application_train.csv` from the gentle-introduction notebook.
- Non-ML HE experiments first: category-risk tables, age/source-score bucket
  tables, anomaly counts, and encrypted numeric aggregates.
- Server-side EDA over encrypted client-provided Home Credit artifacts.
- Earlier single-table prototype code is retired from the active build/UI for now.

Key planning notes:

- `HE_USE_CASES_AND_NOTEBOOK_CONTEXT.md`
- `HOMOMORPHIC_ENCRYPTION_DESIGN.md`
- `docs/SERVER_SIDE_EDA_PLAN.md`

Tracked code lives under `code/client/` and `code/server/`.

Local-only paths are ignored by git:

- `data/`
- `keys/`
- `ciphertexts/`
- `encrypted_payloads/`
- `server_returns/`
- `server_jobs/`

Web app planning:

- `docs/WEB_APP_PLAN.md`

Web receiver:

- `code/server/web/he_job_server.py`
- `deploy/systemd/README.md`

Client prep code:

- Home Credit client prep is the next implementation target.

## Build Server Code

From the repo root:

```bash
cmake -S . -B build -DOpenFHE_DIR=$HOME/openfhe-development/build
cmake --build build
```

If OpenFHE was installed instead of built in-place, use:

```bash
cmake -S . -B build -DOpenFHE_DIR=$HOME/openfhe-install/lib/OpenFHE
cmake --build build
```

The first tracked executable is:

```text
server_numeric_summary
```

Run help:

```bash
./build/server_numeric_summary --help
```

## Home Credit HE Direction

The active HE target is encrypted aggregate EDA from
`home_credit_start-here-a-gentle-introduction.ipynb`:

- category default-rate tables
- age / `EXT_SOURCE_*` bucket default-rate tables
- `DAYS_EMPLOYED == 365243` anomaly aggregate counts
- domain-ratio bucket tables for `CREDIT_INCOME_PERCENT`,
  `ANNUITY_INCOME_PERCENT`, `CREDIT_TERM`, and `DAYS_EMPLOYED_PERCENT`
