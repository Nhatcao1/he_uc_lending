# Client Code

Client code runs where the raw lending data and secret key live.

Tracked here:

- data preparation scripts
- future keygen/encrypt/decrypt wrappers
- future upload/download helpers

Ignored by git:

- raw data under `data/`
- generated prepared CSVs under `encrypted_payloads/`
- secret keys under `keys/`
- returned encrypted results under `server_returns/`

## Prepare LendingClub Payload

```bash
python3 code/client/prepare_lending_payload.py \
  --input data/lending_club_loan_two.csv \
  --output encrypted_payloads/prepared_lending_values.csv \
  --clean-output encrypted_payloads/prepared_lending_clean_values.csv \
  --policy-mask-output encrypted_payloads/prepared_lending_policy_masks.csv \
  --manifest encrypted_payloads/prepared_lending_manifest.json \
  --report encrypted_payloads/prepared_lending_report.json
```

Outputs:

- `prepared_lending_values.csv`: normalized numeric payload for CKKS encryption
- `prepared_lending_clean_values.csv`: cleaned but unnormalized local baseline
- `prepared_lending_policy_masks.csv`: local threshold masks for future count EDA
- `prepared_lending_manifest.json`: schema and normalization metadata
- `prepared_lending_report.json`: client-side cleaning/quality report

These outputs are local artifacts and are ignored by git.

## Prepare BinFHE Outlier Values

This prepares bounded integer values for server-side FHEW/BinFHE threshold
checks. It does not create outlier masks.

```bash
python3 code/client/prepare_binfhe_outlier_values.py \
  --input data/lending_club_loan_two.csv \
  --output encrypted_payloads/binfhe_outliers/outlier_values.csv \
  --rules encrypted_payloads/binfhe_outliers/outlier_rules.csv \
  --packed-output encrypted_payloads/binfhe_outliers/outlier_packed_values.csv \
  --packed-rules encrypted_payloads/binfhe_outliers/outlier_packed_rules.csv \
  --manifest encrypted_payloads/binfhe_outliers/outlier_prep_manifest.json
```

Then use the C++ tools in `code/client/binfhe_outliers/`. The packed files are
the default testing path because they cut six scalar rule ciphertexts per row to
three packed ciphertexts per row.
