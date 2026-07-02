# Server-Side HE EDA Plan

## Boundary

All exploratory analysis happens on the server, but only over encrypted or
public-safe inputs.

```text
Client/local:
  owns raw LendingClub data
  prepares selected fields and masks
  generates HE keys/context
  encrypts payloads
  sends encrypted payloads to server
  keeps secret key local
  decrypts encrypted server results

Server:
  receives encrypted payloads
  receives crypto context and evaluation material
  runs EDA-style aggregate computations under HE
  returns encrypted results
  never receives raw data
  never receives secret key
```

## Dataset For V1

Use the LendingClub single-table dataset first.

Local raw file location is intentionally ignored by git:

```text
data/lending_club_loan_two.csv
```

Fields to prepare locally for V1:

```text
row_id
loan_amnt
annual_inc
dti
open_acc
total_acc
revol_util
revol_bal
pub_rec
mort_acc
pub_rec_bankruptcies
term
loan_status
```

The `loan_status` field is useful for validation and aggregate EDA, but V1 is
not an ML training project.

## EDA Tasks To Implement

### 1. Missing-Value Counts

Question:

```text
How many missing values exist per selected column?
```

Client prepares encrypted 0/1 null masks:

```text
is_null_annual_inc
is_null_dti
is_null_revol_util
...
```

Server computes encrypted sums.

Important limitation:

```text
The server cannot infer CSV missingness from only encrypted raw values.
Missingness must be encoded before encryption as is_missing/is_valid masks,
or missing values must be dropped/filled before encryption.
```

Suggested scheme:

```text
BFV/BGV for exact counts, or CKKS for approximate packed sums
```

Practical V1 decision:

```text
Do not start with server-side missing detection.
Prepare clean values on the client first, then start server HE EDA with
aggregate sums/means or rule-score summaries.
```

### 2. Policy Threshold Counts

Questions from the notebook:

```text
How many applicants have annual_inc > 250000?
How many applicants have dti > 50?
How many applicants have open_acc > 40?
How many applicants have total_acc > 80?
How many applicants have revol_util > 120?
How many applicants have revol_bal > 250000?
```

V1 approach:

```text
Client creates plaintext threshold masks locally.
Client encrypts each mask.
Server sums encrypted masks.
Client decrypts aggregate counts.
```

Later approach:

```text
Server computes encrypted comparisons with BinFHE or another comparison flow.
```

### 3. Distribution / Bin Counts

Questions:

```text
What is the distribution of DTI?
What is the distribution of annual income?
What is the distribution of revolving utilization?
```

V1 approach:

```text
Client creates bin-membership masks.
Server sums encrypted masks per bin.
```

Example bins:

```text
dti:        [0,10), [10,20), [20,30), [30,40), [40,50), [50,+)
revol_util: [0,20), [20,40), [40,60), [60,80), [80,100), [100,+)
annual_inc: [0,25000), [25000,50000), [50000,100000), [100000,250000), [250000,+)
```

### 4. Aggregate Sums And Means

Questions:

```text
Average loan amount?
Average annual income?
Average DTI?
Average revolving balance?
```

Server computes encrypted sums. Count can be public if row count is not
sensitive, or encrypted if needed.

Suggested scheme:

```text
CKKS for packed approximate real-valued sums
```

### 5. Category Counts

Questions:

```text
How many loans are 36-month vs 60-month?
How many records per home_ownership bucket?
How many records per purpose bucket?
```

V1 approach:

```text
Client normalizes categories and creates one-hot masks.
Server sums encrypted category masks.
```

Start with `term`, because it has only two values:

```text
36 months
60 months
```

### 6. Rule-Based Risk Score Summary

This is not ML. It is a transparent policy score.

Example:

```text
risk_score =
    0.30 * dti_scaled
  + 0.25 * revol_util_scaled
  + 0.15 * revol_bal_scaled
  + 0.10 * pub_rec
  + 0.10 * pub_rec_bankruptcies
  + 0.05 * term_60_month_flag
  - 0.15 * annual_inc_scaled
```

Server computes encrypted score vector or encrypted aggregate score statistics.

Suggested scheme:

```text
CKKS
```

V1 output:

```text
encrypted risk_score per row
encrypted sum risk_score
```

Client decrypts and validates against a plaintext baseline.

## Key And File Handling

Ignored local folders:

```text
keys/
data/
ciphertexts/
encrypted_payloads/
server_returns/
```

The server may receive:

```text
crypto context
public key
evaluation keys
encrypted input payloads
public EDA config
```

The server must not receive:

```text
secret key
raw CSV
decrypted intermediate values
```

## First Implementation Order

```text
1. Prepare clean numeric payload on the client.
2. Define encrypted payload format for prepared values.
3. Implement OpenFHE encrypted sums/means or rule-score summary.
4. Split commands into client encrypt, server eval, client decrypt.
5. Add encrypted missing/valid masks only if missing report is still needed.
```

## Tracked Vs Ignored

Tracked:

```text
code/server/
docs/
README.md
.gitignore
```

Ignored:

```text
code/client/
data/
keys/
results/
ciphertexts/
encrypted_payloads/
server_returns/
```
