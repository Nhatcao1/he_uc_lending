# Client BinFHE Outlier Tools

This track is separate from CKKS.

It prepares bounded integer values, encrypts them with BinFHE/FHEW, and lets the
server evaluate threshold rules under HE.

## Prepare Integer Values

```bash
python3 code/client/prepare_binfhe_outlier_values.py \
  --input data/lending_club_loan_two.csv \
  --output encrypted_payloads/binfhe_outliers/outlier_values.csv \
  --rules encrypted_payloads/binfhe_outliers/outlier_rules.csv \
  --packed-output encrypted_payloads/binfhe_outliers/outlier_packed_values.csv \
  --packed-rules encrypted_payloads/binfhe_outliers/outlier_packed_rules.csv \
  --manifest encrypted_payloads/binfhe_outliers/outlier_prep_manifest.json
```

The client does not prepare masks here. It only encodes bounded integers such as:

```text
annual_inc_k = floor(annual_inc / 1000), capped to 511
revol_bal_k  = floor(revol_bal / 1000), capped to 511
dti          = floor(dti), capped to 511
```

It also writes packed bucket files:

```text
outlier_packed_values.csv
outlier_packed_rules.csv
```

Packed mode stores two 5-bit bucketed features in one plaintext, so the current
six rules use three ciphertexts per row instead of six. This is approximate:
the server compares buckets, not exact scaled values.

## Generate BinFHE Keys

```bash
./build/client_binfhe_keygen \
  --out-dir keys/binfhe_outliers \
  --log-q 12
```

Server can receive:

```text
binfhe_context.bin
binfhe_refresh_key.bin
binfhe_switch_key.bin
```

Server must not receive:

```text
binfhe_secret_key.bin
```

## Encrypt Packed Outlier Values

```bash
./build/client_binfhe_encrypt_outliers \
  --context keys/binfhe_outliers/binfhe_context.bin \
  --secret-key keys/binfhe_outliers/binfhe_secret_key.bin \
  --values encrypted_payloads/binfhe_outliers/outlier_packed_values.csv \
  --rules encrypted_payloads/binfhe_outliers/outlier_packed_rules.csv \
  --output-dir encrypted_payloads/binfhe_outliers/columns \
  --manifest encrypted_payloads/binfhe_outliers/outlier_ciphertexts.csv
```

For exact scalar mode, pass `outlier_values.csv` and `outlier_rules.csv` instead.

Send to server:

```text
binfhe_context.bin
binfhe_refresh_key.bin
binfhe_switch_key.bin
outlier_ciphertexts.csv
columns/*.bin
```

## Decrypt Returned Flags

```bash
./build/client_binfhe_decrypt_outliers \
  --context keys/binfhe_outliers/binfhe_context.bin \
  --secret-key keys/binfhe_outliers/binfhe_secret_key.bin \
  --manifest server_returns/binfhe_outliers/outlier_flag_manifest.csv \
  --input-dir server_returns/binfhe_outliers/flags \
  --output server_returns/binfhe_outliers/decrypted_outlier_flags.csv
```

The decrypted CSV includes:

```text
row_id
any_outlier
one column per threshold rule
```

In packed mode, the extra columns are `pack_0`, `pack_1`, and `pack_2`; the
`any_outlier` column ORs those pack flags locally after decryption.
