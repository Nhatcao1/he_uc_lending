# Home Credit HE Plan

> Current primary direction: [Home Credit HE Credit-Scoring Workload](HOME_CREDIT_CREDIT_SCORING.md).
> Fine-grained notebook EDA is now a supporting validation layer, not the main product workflow.

Active notebook context:

```text
notebooks/home_credit_start-here-a-gentle-introduction.ipynb
notebooks/home-credit-complete-eda-feature-importance.ipynb
notebooks/introduction-to-manual-feature-engineering.ipynb
notebooks/introduction-to-manual-feature-engineering-p2.ipynb
```

Keep the current notebook-facing EDA jobs as the first demo path. Add a limited
merge-aware path next, based on the manual feature engineering notebooks. The
goal is not encrypted SQL in CKKS; the goal is to reproduce the notebook's
practical pattern:

```text
child Home Credit table -> groupby loan/client id -> aggregate features
-> merge aggregated client features into application_train rows -> score/report
```

For the HE prototype, joins should be introduced only where they support this
feature-engineering pattern and where the server can do useful encrypted
aggregate math.

## Implemented HE Criteria

The current implementation follows notebook-facing criteria instead of the older
separate bucket/domain use-case names.

| Priority | Criterion | Client preparation | Server HE work | Result after decrypt |
| --- | --- | --- | --- | --- |
| 1 | `missing_data` | Create null masks for selected columns | Sum encrypted missing masks | Missing count/percent table |
| 2 | `app_dist_amt_credit`, `app_dist_amt_income_total`, `app_dist_amt_goods_price` | Clean selected numeric values | Sum encrypted numeric vectors | Sum/mean support table |
| 3 | `app_suite_type`, `app_loan_type`, `app_own_car_realty`, etc. | One-hot application categories | Sum category masks | Category count table |
| 4 | `app_target_balance` | Encode TARGET default/repaid masks | Sum encrypted target masks | Repaid/default count table |
| 5 | `app_target_by_income_type`, `app_target_by_family_status`, etc. | Category masks plus TARGET mask | Sum masks; sum mask times TARGET | Count and default-rate table |
| 6 | `prev_contract_type`, `prev_contract_status`, etc. | One-hot previous_application categories | Sum previous masks | Previous category count tables |
| 7 | `app_selected_correlation_stats` | Select small numeric pairs and valid masks | Sum x, y, xy, x2, y2 support values | Client computes selected correlations |
| 8 | `linear_score_demo` | Optional scaled numeric feature vectors | CKKS weighted sum | Encrypted inference smoke test |
| 9 | `join_hmac_prev_contract_status` | HMAC-tokenized `SK_ID_CURR`, encrypted previous status masks | Token-match plaintext mask times encrypted mask, then sum | Joined previous-status count table |
| 10 | `join_psi_prev_contract_status` | PSI/trusted step creates row-aligned match mask, encrypted previous status masks | CKKS mask times encrypted status mask, then sum | PSI joined status count table |
| 11 | `join_fhew_prev_contract_status` | HMAC-derived token-prefix integers encrypted bit-by-bit | FHEW encrypted equality gates over a capped sample | Encrypted match flags for timing comparison |

## Merge-Aware Extension Plan

The two manual feature engineering notebooks give the strongest boss-facing
reason to include joins. They do not join raw tables for EDA decoration; they
aggregate child tables into per-client features and merge those features into
the main application table for ML.

Notebook patterns to mirror:

| Notebook source | Raw relation | Notebook operation | HE-friendly target |
| --- | --- | --- | --- |
| `introduction-to-manual-feature-engineering.ipynb` | `bureau.SK_ID_CURR -> application_train.SK_ID_CURR` | `bureau.groupby(SK_ID_CURR)` then merge | Previous external-credit count/sum/mean per applicant |
| `introduction-to-manual-feature-engineering.ipynb` | `bureau_balance.SK_ID_BUREAU -> bureau.SK_ID_BUREAU -> SK_ID_CURR` | group by loan, merge client id, group by client | Bureau monthly-status counts per applicant |
| `introduction-to-manual-feature-engineering-p2.ipynb` | `previous_application.SK_ID_CURR -> application_train.SK_ID_CURR` | aggregate previous applications by client and merge | Previous Home Credit approval/refusal/count features |
| `introduction-to-manual-feature-engineering-p2.ipynb` | `POS_CASH_balance`, `credit_card_balance`, `installments_payments` via `SK_ID_PREV`, `SK_ID_CURR` | aggregate by previous loan, attach client id, aggregate by client | Payment/count/balance summaries per applicant |

Recommended implementation order:

1. Keep current EDA upload jobs unchanged for presentation stability.
2. Add one merge-aware proof of concept over current available prep:
   `join_hmac_prev_contract_status`, `join_psi_prev_contract_status`, and
   the capped `join_fhew_prev_contract_status` encrypted equality benchmark.
3. Add one bureau proof of concept:
   `bureau_previous_loan_counts_by_applicant`.
4. Add one two-hop proof of concept:
   `bureau_balance_status_by_applicant`, using `SK_ID_BUREAU -> SK_ID_CURR`.
5. Add one broader Home Credit previous-loan proof of concept:
   `previous_application_status_by_applicant`.
6. Feed selected merged aggregate features into the existing
   `linear_score_demo` or a new `joined_feature_score_demo`.

Privacy/HE design:

- Best practical design: client/trusted side creates deterministic join tokens
  such as `HMAC(join_secret, SK_ID_CURR)` and `HMAC(join_secret, SK_ID_PREV)`.
- Server may group or join on tokens, but never sees raw IDs.
- Sensitive numeric values and 0/1 masks remain CKKS encrypted.
- Server computes encrypted sums and masked sums from the PSI row mask.
- Client decrypts the final per-client aggregate feature table or final score.
- FHEW can compare encrypted ID bits, but it is pairwise and gate-heavy. Keep it
  as a small benchmark unless a later design adds a scalable private matching
  protocol.

What we should not promise yet:

- Fully encrypted SQL joins on encrypted IDs.
- Encrypted sorting/top-K over arbitrary IDs.
- RandomForest/LightGBM training under HE.
- End-to-end private feature engineering over all 2.68 GB of Kaggle data.

Detailed mapping from original notebook EDA to the HE implementation choices:

```text
docs/HOME_CREDIT_COMPLETE_EDA_HE_MAPPING.md
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
