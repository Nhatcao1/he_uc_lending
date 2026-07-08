# Homomorphic Encryption Design For Home Credit

## Objective

Evaluate whether homomorphic encryption makes practical sense for the Home
Credit notebook workflow, then define a proof of concept that is useful without
trying to move the whole Kaggle-style EDA and ML pipeline under FHE.

Active notebook context:

```text
home_credit_start-here-a-gentle-introduction.ipynb
```

Earlier LendingClub ideas are retired from the active implementation for now.
The current build should focus on Home Credit `application_train.csv` and on
server-side aggregate EDA over encrypted client-prepared artifacts.

## Recommended Use Case

Use homomorphic encryption for privacy-preserving Home Credit aggregate EDA.

```text
Client owns raw Home Credit rows
        |
        | clean, normalize, bucket, one-hot encode, encrypt
        v
Server receives encrypted masks/numeric columns plus public/evaluation keys
        |
        | encrypted sums and masked sums
        v
Client decrypts aggregate counts, totals, and rates
```

This protects raw applicant rows from the server. It does not hide row count,
schema, selected feature names, manifest metadata, request timing, or the final
report from whoever holds the secret key.

## What Makes Sense Now

### 1. Encrypted Category Default-Rate Tables

This is the strongest Home Credit first use case.

Client prepares:

```text
TARGET default mask: 0/1
NAME_INCOME_TYPE one-hot masks
NAME_EDUCATION_TYPE one-hot masks
OCCUPATION_TYPE one-hot masks
ORGANIZATION_TYPE one-hot masks
optional amount columns: AMT_CREDIT, AMT_INCOME_TOTAL, AMT_ANNUITY
```

Server computes encrypted aggregates:

```text
count(category)          = sum(category_mask)
defaults(category)       = sum(category_mask * target_mask)
credit_sum(category)     = sum(category_mask * AMT_CREDIT)
income_sum(category)     = sum(category_mask * AMT_INCOME_TOTAL)
annuity_sum(category)    = sum(category_mask * AMT_ANNUITY)
```

Client decrypts and reports:

```text
default_rate = defaults / count
average_credit = credit_sum / count
average_income = income_sum / count
average_annuity = annuity_sum / count
```

Why it fits:

- The notebook already studies target distribution by categorical fields.
- Client-side one-hot masks avoid encrypted string handling.
- Server work is mostly multiply masks and sum, which is HE-friendly.
- The result is a useful EDA report, not fake encrypted plotting.

### 2. Encrypted Bucket Reports

Client turns difficult values into simple bucket masks before encryption:

```text
age buckets from DAYS_BIRTH
EXT_SOURCE_1 / EXT_SOURCE_2 / EXT_SOURCE_3 score buckets
DAYS_EMPLOYED normal/anomaly buckets
domain-ratio buckets
```

Recommended domain ratios:

```text
CREDIT_INCOME_PERCENT = AMT_CREDIT / AMT_INCOME_TOTAL
ANNUITY_INCOME_PERCENT = AMT_ANNUITY / AMT_INCOME_TOTAL
CREDIT_TERM = AMT_ANNUITY / AMT_CREDIT
DAYS_EMPLOYED_PERCENT = DAYS_EMPLOYED / DAYS_BIRTH
```

Server computes encrypted count/default-count tables for each bucket. Client
decrypts trend tables such as default rate by age group or by EXT_SOURCE range.

### 3. Encrypted Numeric Summary

The current tracked C++ executable, `server_numeric_summary`, supports the
simple packed numeric aggregate path:

```text
encrypted numeric vectors -> encrypted column sums -> client decrypts totals
```

This is useful as the baseline HE plumbing test before masked category EDA.

### 4. Later CKKS Linear Risk Score

Linear scoring is still valid HE work, but it is not the first Home Credit EDA
target.

Possible later shape:

```text
risk_score =
    w0
  + w1 * AMT_CREDIT_scaled
  + w2 * AMT_INCOME_TOTAL_scaled
  + w3 * AMT_ANNUITY_scaled
  + w4 * DAYS_BIRTH_scaled
  + w5 * EXT_SOURCE_2_scaled
  + w6 * CREDIT_INCOME_PERCENT_scaled
  + ...
```

Why this fits later:

- CKKS handles approximate real-valued weighted sums well.
- Public model weights mean low multiplicative depth.
- It can reuse the same client/server payload discipline.

Do not treat this as notebook-derived truth. It needs either documented public
policy weights or a separately trained plaintext model whose weights are then
exported for encrypted inference.

## What Does Not Make Sense For V1

### Raw Encrypted EDA

The server cannot magically inspect encrypted CSVs, strings, dates, nulls, or
plots. The client must prepare the data into numeric vectors, binary masks, and
manifest metadata before encryption.

### Full Encrypted Home Credit Multi-Table Join

Home Credit has multiple related tables in the full dataset. Joining by
`SK_ID_CURR`, building historical aggregates, and engineering bureau/POS/card
features should stay outside the first HE path. Start with
`application_train.csv`.

### FHE Training

Training RandomForest, XGBoost, or neural networks fully under FHE is not a
good starting point. Training needs many iterations, branching, comparisons,
and nonlinear functions. Use plaintext training/export if scoring becomes the
target later.

### Encrypted String/Date Handling

Names, occupation labels, organization names, and dates should be converted on
the client into numeric codes, one-hot masks, date-derived numbers, or buckets.
The server should not receive plaintext raw strings unless the privacy design
explicitly allows that metadata.

## Proposed Active Architecture

```text
uc_credit_rating/
  code/
    client/
      prepare_home_credit_*.py          # local raw-data preparation, encryption
    server/
      numeric_summary/                  # current encrypted numeric aggregate
      home_credit_category_eda/         # planned masked aggregate job
      web/                              # upload receiver and job UI
  docs/
    HOME_CREDIT_HE_PLAN.md
    HOME_CREDIT_COMPLETE_EDA_HE_MAPPING.md
    HOME_CREDIT_IMPLEMENTED_CLIENT_SERVER_FLOW.md
    HOME_CREDIT_JOIN_MATCHING_COMMANDS.md
  data/                                 # local only, ignored
  keys/                                 # local only, ignored
  encrypted_payloads/                   # local only, ignored
  server_jobs/                          # local only, ignored
  server_returns/                       # local only, ignored
```

## Client Responsibilities

- Own raw `application_train.csv`.
- Remove invalid rows or map missing values into explicit buckets.
- Normalize numeric columns when required.
- Convert categorical columns into one-hot masks.
- Convert dates and special values into numeric buckets.
- Encrypt prepared vectors and masks.
- Send only encrypted payloads, public/evaluation keys, and manifest metadata.
- Keep the secret key local.

The client must not upload:

```text
raw CSV
plaintext prepared CSV
secret key
decrypted report
row-level plaintext applicant data
```

## Server Responsibilities

- Accept a job bundle over the web receiver.
- Validate manifest, required files, job type, and payload shape.
- Run the matching OpenFHE executable.
- Compute encrypted aggregate results.
- Return encrypted result files and run metadata.
- Never require the client secret key.

## HE Scheme Choice

Use CKKS first for packed approximate aggregates:

```text
scheme: CKKS
security: 128-bit
operation: packed encrypted masks and numeric vectors
typical work: additions, mask * target, mask * amount, rotations/sums
```

Use BFV/BGV later if exact integer counts become more important than approximate
packed throughput.

Use BinFHE/FHEW only for narrow boolean/comparison experiments. It is not the
default for Home Credit aggregate EDA because the first useful reports can be
made from client-prepared masks and CKKS/BFV-style sums.

## Privacy Boundary

Protected from the server:

- raw applicant rows
- exact category membership per row
- target/default per row
- amount values per row
- intermediate masked sums before decryption

Visible or inferable to the server:

- job type
- row count or approximate row count
- selected columns and category names from the manifest
- number of buckets/categories
- ciphertext count and payload size
- timing and requester metadata

The final readable report exists only after the client decrypts the encrypted
server result.

## Evaluation Criteria

Record HE and workflow quality first:

```text
rows
selected_column_count
category_count
bucket_count
ciphertext_count
slots_per_ciphertext
setup_time_ms
encode_time_ms
encrypt_time_ms
upload_size_bytes
he_eval_time_ms
result_size_bytes
decrypt_time_ms
max_abs_error_vs_plain_aggregate
mean_abs_error_vs_plain_aggregate
```

For later scoring work, add:

```text
auc
accuracy
precision
recall
score_error
threshold_decision_mismatch_rate
```

## Milestones

### Milestone 1: Numeric Summary Plumbing

- Build and run `server_numeric_summary`.
- Send encrypted Home Credit numeric columns.
- Return encrypted sums.
- Decrypt client-side and compare against plaintext local sums.

### Milestone 2: Category Default-Rate EDA

- Implement Home Credit client prep for category masks and target mask.
- Implement server masked-sum executable.
- Produce decrypted category count/default-rate report.

### Milestone 3: Bucket EDA

- Add age, EXT_SOURCE, DAYS_EMPLOYED anomaly, and domain-ratio buckets.
- Reuse the masked aggregate pattern.
- Report default rate by bucket.

### Milestone 4: Web Job Flow

- Upload bundle through `code/server/web/he_job_server.py`.
- Validate manifests and required encrypted files.
- Store job state and encrypted results.
- Keep service mode and manual run mode both usable.

### Milestone 5: Optional Linear Scoring

- Define public Home Credit scoring features and weights.
- Implement plaintext score baseline.
- Implement CKKS weighted-sum inference.
- Compare decrypted scores and benchmark latency.

## Recommendation

Homomorphic encryption does make sense for this project if we frame it as
privacy-preserving Home Credit aggregate EDA first.

The strongest active build is:

```text
Home Credit application_train.csv on client
    -> clean, bucket, one-hot, encrypt
    -> server computes encrypted aggregate tables
    -> client decrypts default-rate and numeric-summary reports
```

Linear credit scoring remains a good later CKKS experiment, but the immediate
Home Credit value is encrypted category and bucket EDA.
