# Client Code

Client code runs where the raw Home Credit data and secret key live.

Tracked here:

- Home Credit data preparation scripts
- CKKS keygen/encrypt/decrypt wrappers
- optional plaintext linear-model export helper

Ignored by git:

- raw data under `data/`
- generated prepared CSVs under `encrypted_payloads/`
- secret keys under `keys/`
- returned encrypted results under `server_returns/`

## Next Home Credit Payload

The active target is `data/home_credit/application_train.csv`.

Basic categorical EDA is mostly client-side because the client must choose and
document the category policy before encryption. The first slice keeps all values
for `NAME_INCOME_TYPE` and `NAME_EDUCATION_TYPE`; later high-cardinality columns
should use top-K plus an `__OTHER__` bucket.

Planned client outputs:

- category masks for `NAME_INCOME_TYPE`, `OCCUPATION_TYPE`,
  `NAME_EDUCATION_TYPE`, and `ORGANIZATION_TYPE`
- bucket masks for age, `EXT_SOURCE_*`, and `DAYS_EMPLOYED` anomaly
- encrypted `TARGET` mask
- encrypted amount vectors for `AMT_CREDIT`, `AMT_INCOME_TOTAL`, and
  `AMT_ANNUITY`
- manifests describing encrypted chunks

These outputs are local artifacts and are ignored by git.

## Implemented Tools

```text
home_credit/prepare_home_credit_basic_eda.py
home_credit/train_home_credit_linear_model.py
home_credit/download_job_bundle.py
ckks_tools/encrypt_home_credit_payload.cpp
ckks_tools/decrypt_ckks_results.cpp
```

Full client/server command flow:

```text
docs/HOME_CREDIT_IMPLEMENTED_CLIENT_SERVER_FLOW.md
```
