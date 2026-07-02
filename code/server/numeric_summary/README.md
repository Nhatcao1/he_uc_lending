# Server Numeric Summary

`server_numeric_summary` is the first server-side HE EDA executable.

It receives:

- serialized CKKS crypto context
- serialized EvalSum keys
- serialized encrypted column ciphertext chunks
- a plain CSV manifest describing the encrypted chunks

It computes:

```text
encrypted_sum(column) = EvalSum(chunk_0) + EvalSum(chunk_1) + ...
```

It writes:

- one encrypted sum ciphertext per column
- `summary_manifest.csv` with output filenames and public row/slot metadata

The server never receives raw data or the secret key.

## Input Manifest

CSV format:

```csv
column,ciphertext,rows,slots
AMT_CREDIT,AMT_CREDIT_0000.bin,4096,4096
AMT_CREDIT,AMT_CREDIT_0001.bin,904,904
AMT_INCOME_TOTAL,AMT_INCOME_TOTAL_0000.bin,4096,4096
AMT_INCOME_TOTAL,AMT_INCOME_TOTAL_0001.bin,904,904
```

Fields:

- `column`: logical prepared column name
- `ciphertext`: path relative to `--input-dir`
- `rows`: number of real rows represented by this chunk
- `slots`: number of active packed slots to sum

For most payloads, `rows` and `slots` are the same. Both are kept so later
payloads can describe padding explicitly.

## Command

Build on server, assuming OpenFHE is under `~`:

```bash
cmake -S . -B build -DOpenFHE_DIR=$HOME/openfhe-development/build
cmake --build build
```

Alternative if OpenFHE is installed:

```bash
cmake -S . -B build -DOpenFHE_DIR=$HOME/openfhe-install/lib/OpenFHE
cmake --build build
```

Run:

```bash
./build/server_numeric_summary \
  --context encrypted_payloads/crypto_context.bin \
  --eval-sum-keys encrypted_payloads/eval_sum_keys.bin \
  --manifest encrypted_payloads/column_manifest.csv \
  --input-dir encrypted_payloads/columns \
  --output-dir server_returns/numeric_summary
```

## Output Manifest

```csv
column,encrypted_sum_ciphertext,total_rows,total_slots,chunk_count
AMT_CREDIT,AMT_CREDIT.sum.bin,5000,5000,2
AMT_INCOME_TOTAL,AMT_INCOME_TOTAL.sum.bin,5000,5000,2
```

The client decrypts each encrypted sum and computes:

```text
mean = sum / total_rows
```
