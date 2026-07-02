# Server BinFHE Outlier Flags

This server tool evaluates outlier thresholds using BinFHE/FHEW arbitrary
function evaluation.

The client sends encrypted bounded integer values. The server supports both the
exact scalar manifest and the packed bucket manifest. It computes encrypted
outlier flags with LUTs:

```text
Enc(value) -> EvalFunc(value > threshold) -> Enc(0/1 flag)
Enc(packed bucket pair) -> EvalFunc(any bucket > threshold bucket) -> Enc(0/1 flag)
```

The server does not receive raw values, prepared plaintext values, masks, or the
secret key.

## Command

```bash
./build/server_binfhe_outlier_flags \
  --context server_jobs/<job>/work/binfhe_context.bin \
  --refresh-key server_jobs/<job>/work/binfhe_refresh_key.bin \
  --switch-key server_jobs/<job>/work/binfhe_switch_key.bin \
  --manifest server_jobs/<job>/work/outlier_ciphertexts.csv \
  --input-dir server_jobs/<job>/work/columns \
  --output-dir server_jobs/<job>/output/binfhe_outliers
```

Output:

```text
outlier_flag_manifest.csv
flags/*.flag.bin
```

The client decrypts the returned flags and performs actual row elimination
locally.
