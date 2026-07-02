# Home Credit HE Plan

Active notebook context:

```text
home_credit_start-here-a-gentle-introduction.ipynb
```

Use `application_train.csv` first. Avoid the full multi-table join problem until
the single-table encrypted aggregate path is working.

## First HE Use Cases

| Priority | Use case | Client preparation | Server HE work | Result after decrypt |
| --- | --- | --- | --- | --- |
| 1 | Category default-rate table | One-hot masks for `NAME_INCOME_TYPE`, `OCCUPATION_TYPE`, `NAME_EDUCATION_TYPE`, `ORGANIZATION_TYPE`; encrypted `TARGET` mask | Sum category masks; sum category mask times target mask; sum selected amount columns by category | Count, default count, default rate, average credit/income by category |
| 2 | Age bucket default-rate table | Convert `DAYS_BIRTH` to age years; bucket locally; encrypt bucket masks and target mask | Encrypted count and default count per age bucket | Failure-to-repay rate by age group |
| 3 | `DAYS_EMPLOYED` anomaly report | Encode `DAYS_EMPLOYED == 365243` as anomaly mask; encode normal/invalid buckets | Encrypted anomaly count and anomaly default count | Compare anomaly default rate vs normal |
| 4 | `EXT_SOURCE` bucket reports | Null handling plus score buckets for `EXT_SOURCE_1/2/3` | Encrypted count/default count per bucket | Default rate by external-source score bucket |
| 5 | Domain ratio bucket reports | Compute `CREDIT_INCOME_PERCENT`, `ANNUITY_INCOME_PERCENT`, `CREDIT_TERM`, `DAYS_EMPLOYED_PERCENT`; bucket ratios | Encrypted count/default count per ratio bucket | Risk trend by financial ratio |

## Client Responsibilities

- Load `data/home_credit/application_train.csv`.
- Remove invalid rows or map nulls into explicit buckets.
- Encode categorical values into one-hot masks.
- Encode `TARGET` as an encrypted 0/1 mask.
- Pack numeric/mask vectors into ciphertext chunks.
- Send only encrypted chunks, public/evaluation keys, and manifests.

Never send:

```text
raw CSV
plaintext prepared CSV
SK_ID_CURR row-level joins in plaintext
secret key
decrypted report
```

## Server Responsibilities

- Validate manifest and encrypted artifact presence.
- Run aggregate HE operations only.
- Return encrypted aggregate files and result manifests.
- Never attempt raw dataframe cleaning, category parsing, or null handling.

## Scheme Direction

- CKKS for packed numeric sums and approximate aggregate reports.
- BFV/BGV is a possible later option for exact integer counts.
- Scalar comparison schemes are not the first Home Credit path because the
  useful work is aggregate counting/summing, not per-row comparison.

## Next Implementation Slice

Create a Home Credit client preparation script that emits:

```text
category_manifest.csv
masks/*.bin or prepared mask CSV before encryption wrapper exists
target/*.bin or prepared target mask CSV before encryption wrapper exists
amounts/*.bin or prepared amount CSV before encryption wrapper exists
home_credit_prep_manifest.json
```

Then add the server aggregate executable for:

```text
sum(mask)
sum(mask * target)
sum(mask * amount_column)
```
