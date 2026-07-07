# Home Credit HE Plan

Active notebook context:

```text
home_credit_start-here-a-gentle-introduction.ipynb
home-credit-complete-eda-feature-importance.ipynb
```

Use `application_train.csv` first. Avoid the full multi-table join problem until
the single-table encrypted aggregate path is working.

## Implemented HE Criteria

The current implementation follows notebook-facing criteria instead of the older
separate bucket/domain use-case names.

| Priority | Criterion | Client preparation | Server HE work | Result after decrypt |
| --- | --- | --- | --- | --- |
| 1 | `missing_data` | Create null masks for selected columns | Sum encrypted missing masks | Missing count/percent table |
| 2 | `target_balance` | Encode TARGET default/repaid masks | Sum encrypted target masks | Repaid/default count table |
| 3 | `application_numeric_summary` | Clean selected numeric values | Sum encrypted numeric vectors | Sum/mean support table |
| 4 | `application_category_counts` | One-hot application categories | Sum category masks | Category count table |
| 5 | `application_default_rates` | Category masks, TARGET mask, amount vectors | Sum masks; sum mask times TARGET; sum mask times amount | Count, default rate, amount means |
| 6 | `application_numeric_histograms` | Client bins AMT, age, EXT_SOURCE, and ratio fields | Sum encrypted bin masks and target-conditioned masks | Histogram/default-rate tables |
| 7 | `previous_application_category_counts` | One-hot previous_application categories | Sum previous masks | Previous category count tables |
| 8 | `previous_application_target_rates` | Client joins previous_application to TARGET by `SK_ID_CURR` before encryption | Sum joined masks and joined mask times TARGET | Historical category risk tables |
| 9 | `selected_correlation_stats` | Select small numeric pairs and valid masks | Sum x, y, xy, x2, y2 support values | Client computes selected correlations |
| 10 | `linear_score_demo` | Optional scaled numeric feature vectors | CKKS weighted sum | Encrypted inference smoke test |

Detailed mapping from original notebook EDA to the HE implementation choices:

```text
docs/HOME_CREDIT_COMPLETE_EDA_HE_MAPPING.md
docs/HOME_CREDIT_BASIC_EDA_IMPLEMENTATION_MAP.md
```

Implemented client/server flow and run commands:

```text
docs/HOME_CREDIT_IMPLEMENTED_CLIENT_SERVER_FLOW.md
```

## Basic EDA First Slice

The old first slice was category-only. The active implementation now prepares
all criteria from one client script, while each browser upload is still one
small criterion zip.

```text
NAME_INCOME_TYPE
NAME_EDUCATION_TYPE
TARGET
```

This is mostly client-side work. The client selects categories, applies missing
and rare-category policy, creates masks, encrypts them, and later decrypts the
final report. The server only computes encrypted aggregate sums.

Add larger category columns after the path works:

```text
OCCUPATION_TYPE      top-K + __OTHER__
ORGANIZATION_TYPE   top-K + __OTHER__
```

## Client Responsibilities

- Load `data/home_credit/application_train.csv`.
- Remove invalid rows or map nulls into explicit buckets.
- Encode categorical values into one-hot masks.
- Apply category selection policy such as all-values or top-K plus `__OTHER__`.
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

Current client preparation script emits:

```text
vector_manifest.csv
aggregate_operations.csv
numeric_vectors.csv
linear_score_vectors.csv
vectors/*.csv
preparation_manifest.json
```

Server aggregate executable supports:

```text
sum(mask)
sum(mask * target)
sum(mask * amount_column)
```
