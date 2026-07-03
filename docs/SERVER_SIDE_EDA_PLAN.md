# Server-Side Home Credit EDA Plan

The server-side HE plan is now Home Credit first.

Initial source table:

```text
data/home_credit/application_train.csv
```

Notebook context:

```text
home_credit_start-here-a-gentle-introduction.ipynb
```

## Privacy Boundary

Client owns:

- raw Home Credit CSVs
- null handling and bucket policy
- one-hot/category encoding
- secret key
- final decrypted report

Server receives:

- encrypted masks and numeric vectors
- public/evaluation keys
- plain manifests describing encrypted artifact names and aggregate labels

Server must not receive:

- raw CSV
- plaintext prepared CSV
- secret key
- row-level decrypted values
- plaintext applicant joins

## Active Server Shape

Keep the server as an aggregate executor:

```text
encrypted inputs + manifests -> encrypted aggregate outputs
```

The first reusable executable remains:

```text
server_numeric_summary
```

It can sum packed encrypted Home Credit numeric columns such as:

```text
AMT_CREDIT
AMT_INCOME_TOTAL
AMT_ANNUITY
EXT_SOURCE_1
EXT_SOURCE_2
EXT_SOURCE_3
DAYS_BIRTH
```

## Planned Home Credit EDA Jobs

### 1. Category Default-Rate EDA

Detailed notebook-to-implementation map:

```text
docs/HOME_CREDIT_BASIC_EDA_IMPLEMENTATION_MAP.md
```

Implemented command flow:

```text
docs/HOME_CREDIT_IMPLEMENTED_CLIENT_SERVER_FLOW.md
```

Questions:

- What is the default rate by `NAME_INCOME_TYPE`?
- What is the default rate by `OCCUPATION_TYPE`?
- What is the default rate by `NAME_EDUCATION_TYPE`?
- What is the default rate by `ORGANIZATION_TYPE`?

First implementation subset:

```text
NAME_INCOME_TYPE
NAME_EDUCATION_TYPE
TARGET
```

Client-side category policy:

```text
small columns: keep all categories
large/noisy columns: top-K categories plus __OTHER__
missing values: __MISSING__
```

Server operations:

```text
sum(category_mask)
sum(category_mask * target_mask)
sum(category_mask * AMT_CREDIT)
sum(category_mask * AMT_INCOME_TOTAL)
```

Client decrypts aggregates and computes rates/averages.

### 2. Age / Source Bucket EDA

Questions:

- What is default rate by age bucket?
- What is default rate by `EXT_SOURCE_1/2/3` bucket?
- How different is the `DAYS_EMPLOYED == 365243` anomaly group?

Server operations:

```text
sum(bucket_mask)
sum(bucket_mask * target_mask)
```

### 3. Domain Ratio EDA

Client computes and buckets:

```text
CREDIT_INCOME_PERCENT = AMT_CREDIT / AMT_INCOME_TOTAL
ANNUITY_INCOME_PERCENT = AMT_ANNUITY / AMT_INCOME_TOTAL
CREDIT_TERM = AMT_ANNUITY / AMT_CREDIT
DAYS_EMPLOYED_PERCENT = DAYS_EMPLOYED / DAYS_BIRTH
```

Server aggregates encrypted bucket counts/default counts.

## Next Implementation

Build client preparation first:

```text
code/client/prepare_home_credit_category_eda.py
```

Then build server aggregate support:

```text
code/server/home_credit_aggregate/server_home_credit_aggregate.cpp
```
