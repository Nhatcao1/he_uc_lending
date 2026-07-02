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

Client prep code:

- `code/client/prepare_lending_payload.py`
- `code/client/prepare_binfhe_outlier_values.py`

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
server_binfhe_outlier_flags
client_binfhe_keygen
client_binfhe_encrypt_outliers
client_binfhe_decrypt_outliers
```

Run help:

```bash
./build/server_numeric_summary --help
```

## BinFHE Outlier Track

Client prepares bounded integer values and a packed bucket variant. The packed
variant stores two bucketed rule values per ciphertext, cutting the current six
rules from six ciphertexts per row to three ciphertexts per row.

```bash
python3 code/client/prepare_binfhe_outlier_values.py \
  --input data/lending_club_loan_two.csv \
  --output encrypted_payloads/binfhe_outliers/outlier_values.csv \
  --rules encrypted_payloads/binfhe_outliers/outlier_rules.csv \
  --packed-output encrypted_payloads/binfhe_outliers/outlier_packed_values.csv \
  --packed-rules encrypted_payloads/binfhe_outliers/outlier_packed_rules.csv \
  --manifest encrypted_payloads/binfhe_outliers/outlier_prep_manifest.json
```

Client keygen and packed encryption:

```bash
./build/client_binfhe_keygen --out-dir keys/binfhe_outliers --log-q 12

./build/client_binfhe_encrypt_outliers \
  --context keys/binfhe_outliers/binfhe_context.bin \
  --secret-key keys/binfhe_outliers/binfhe_secret_key.bin \
  --values encrypted_payloads/binfhe_outliers/outlier_packed_values.csv \
  --rules encrypted_payloads/binfhe_outliers/outlier_packed_rules.csv \
  --output-dir encrypted_payloads/binfhe_outliers/columns \
  --manifest encrypted_payloads/binfhe_outliers/outlier_ciphertexts.csv
```

Use `outlier_values.csv` and `outlier_rules.csv` instead for the exact scalar
path. Scalar mode uses one ciphertext per row per rule.

Server threshold evaluation:

```bash
./build/server_binfhe_outlier_flags \
  --context <work>/binfhe_context.bin \
  --refresh-key <work>/binfhe_refresh_key.bin \
  --switch-key <work>/binfhe_switch_key.bin \
  --manifest <work>/outlier_ciphertexts.csv \
  --input-dir <work>/columns \
  --output-dir <work>/output/binfhe_outliers
```

Client decrypts returned flags:

```bash
./build/client_binfhe_decrypt_outliers \
  --context keys/binfhe_outliers/binfhe_context.bin \
  --secret-key keys/binfhe_outliers/binfhe_secret_key.bin \
  --manifest server_returns/binfhe_outliers/outlier_flag_manifest.csv \
  --input-dir server_returns/binfhe_outliers/flags \
  --output server_returns/binfhe_outliers/decrypted_outlier_flags.csv
```
