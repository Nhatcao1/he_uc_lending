# Home Credit Basic EDA Implementation Map

This note maps the original notebook EDA ideas to the HE implementation choice.
The important split is simple: the client owns data interpretation and encoding;
the server only runs encrypted aggregate math.

Active source:

```text
home_credit_start-here-a-gentle-introduction.ipynb
application_train.csv
```

Additional notebook context was also copied from:

```text
home-credit-complete-eda-feature-importance.ipynb
```

## Client/Server Rule

Client does:

- raw CSV loading
- column selection
- null policy
- category cleanup
- top-K/category limiting
- one-hot mask generation
- bucket generation
- local plaintext validation
- encryption
- final decryption and readable report

Server does:

- manifest validation
- encrypted sums
- encrypted masked sums
- encrypted result packaging

Server does not do:

- pandas EDA
- string category parsing
- null detection from raw data
- top-K category selection
- final plaintext rates
- secret-key operations

## Basic EDA Map

| Original notebook EDA | Original code shape | HE implementation choice | Client work | Server work | Status |
| --- | --- | --- | --- | --- | --- |
| Missing-value audit | `application_train.isnull().sum()` and percent | Client prepares missing masks if we need a privacy-preserving missing report; otherwise client cleans before encryption | Decide null policy; optionally create `is_null_<column>` masks; encrypt masks | Sum encrypted null masks | Deferred; cleaning is required before first category EDA |
| Numeric distributions | `sns.distplot(AMT_CREDIT)`, `AMT_INCOME_TOTAL`, `AMT_GOODS_PRICE` | Replace plots with encrypted sums/counts or client-prepared histogram bucket masks | Clean numeric values; optionally bucket numeric ranges; encrypt numeric columns or bucket masks | Sum numeric vectors or bucket masks | Numeric summary executable exists; histogram buckets planned |
| Target counts | `application_train["TARGET"].value_counts()` | Encrypted count of `TARGET == 1` and total rows | Encode `TARGET` as 0/1 mask; encrypt target mask | Sum encrypted target mask | First category EDA dependency |
| Category-by-target counts | For each category value, count `TARGET == 0` and `TARGET == 1` | Encrypted category default-rate table | Select categorical columns; normalize nulls; limit high-cardinality columns; create one-hot category masks; encrypt masks and target | `sum(mask)` and `sum(mask * target)` | First basic EDA implementation target |
| Category amount averages | Notebook compares groups visually or through grouped values | Add encrypted amount sums by category | Encrypt selected amount columns such as `AMT_CREDIT`, `AMT_INCOME_TOTAL`, `AMT_ANNUITY` | `sum(mask * amount)` | Second slice after count/default count |
| Correlation heatmap | `application_train.corr()` heatmap | Not first HE target | None for V1 | None for V1 | Defer; expensive and less useful for first proof |
| Label encoding | `LabelEncoder` over object columns | Do not send label-encoded categories for group EDA; use one-hot masks instead | Convert strings into explicit category masks | Aggregate masks only | Replaced by mask encoding |
| Fill missing numeric values | `application_train.fillna(-999)` | Use explicit missing buckets or remove rows depending on report | Apply policy before encryption; document it in manifest | Trust manifest only | Client responsibility |

## First Basic EDA Slice

Start with count/default-count tables only:

```text
NAME_INCOME_TYPE
NAME_EDUCATION_TYPE
```

Client output:

```text
home_credit_category_config.json
category_manifest.csv
masks/<column>/<category>/*.bin
target/*.bin
```

Server output:

```text
category_summary_manifest.csv
aggregates/<column>/<category>/count.bin
aggregates/<column>/<category>/default_count.bin
```

Client decrypted report:

```text
column
category
count
default_count
default_rate
```

## Category Selection Policy

This policy is an implementation choice, not something already implemented in
the original notebook.

Recommended first config:

```json
{
  "categorical_columns": {
    "NAME_INCOME_TYPE": { "mode": "all" },
    "NAME_EDUCATION_TYPE": { "mode": "all" },
    "OCCUPATION_TYPE": { "mode": "top_k", "k": 20, "other_bucket": true },
    "ORGANIZATION_TYPE": { "mode": "top_k", "k": 30, "other_bucket": true }
  },
  "missing_bucket": "__MISSING__",
  "other_bucket": "__OTHER__"
}
```

Reason:

- `NAME_INCOME_TYPE` and `NAME_EDUCATION_TYPE` are small enough to keep all
  categories.
- `OCCUPATION_TYPE` and `ORGANIZATION_TYPE` can create many encrypted masks, so
  top-K keeps the payload and server work manageable.
- `__MISSING__` avoids silently dropping nulls.
- `__OTHER__` keeps rare values counted without exploding ciphertext count.

## Manifest Requirements

The client manifest should record:

- source table name
- row count
- selected columns
- category policy per column
- missing bucket label
- other bucket label
- category labels included in each mask
- ciphertext chunking parameters
- HE scheme and parameter profile
- whether amount columns are included

The server can validate shape and presence, but it cannot know whether the
client's category cleanup was semantically correct.

## Practical Order

1. Implement plaintext client preparation for category masks and manifest.
2. Add encryption wrapper around those masks.
3. Implement server encrypted `sum(mask)` and `sum(mask * target)`.
4. Add optional encrypted amount sums.
5. Add bucket EDA using the same mask aggregate pattern.
