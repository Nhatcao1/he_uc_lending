# Client Code

Client code runs where the raw Home Credit data and secret key live.

Tracked here:

- future Home Credit data preparation scripts
- future keygen/encrypt/decrypt wrappers
- future upload/download helpers

Ignored by git:

- raw data under `data/`
- generated prepared CSVs under `encrypted_payloads/`
- secret keys under `keys/`
- returned encrypted results under `server_returns/`

## Next Home Credit Payload

The active target is `data/home_credit/application_train.csv`.

Planned client outputs:

- category masks for `NAME_INCOME_TYPE`, `OCCUPATION_TYPE`,
  `NAME_EDUCATION_TYPE`, and `ORGANIZATION_TYPE`
- bucket masks for age, `EXT_SOURCE_*`, and `DAYS_EMPLOYED` anomaly
- encrypted `TARGET` mask
- encrypted amount vectors for `AMT_CREDIT`, `AMT_INCOME_TOTAL`, and
  `AMT_ANNUITY`
- manifests describing encrypted chunks

These outputs are local artifacts and are ignored by git.
