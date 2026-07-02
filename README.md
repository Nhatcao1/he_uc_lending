# HE UC Lending

Planning and prototype workspace for homomorphic-encryption use cases around
lending and credit-rating data.

Current focus:

- LendingClub notebook context as the simpler first dataset path.
- Non-ML HE experiments first: missing counts, policy threshold counts, and
  rule-based encrypted scoring.
- Home Credit notebook kept as later context for richer multi-table scenarios.
- Server-side EDA over encrypted client-provided lending data.

Key planning notes:

- `HE_USE_CASES_AND_NOTEBOOK_CONTEXT.md`
- `HOMOMORPHIC_ENCRYPTION_DESIGN.md`
- `docs/SERVER_SIDE_EDA_PLAN.md`

Tracked code is server-side only under `code/server/`.

Local-only paths are ignored by git:

- `code/client/`
- `data/`
- `keys/`
- `ciphertexts/`
- `encrypted_payloads/`
- `server_returns/`

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
