# HE EDA Data Preparation Limits

## Main Finding

Python does not remove the core limitation.

`openfhe-python` or another Python HE wrapper can help call encryption APIs from
Python, but it does not let the server inspect CSV concepts such as:

```text
empty cell
missing field
NaN string
null marker
blank string
invalid numeric value
```

Once data is encrypted, the server sees ciphertexts. The server can add,
multiply, rotate, and evaluate supported encrypted arithmetic, but it cannot
parse CSV structure or decide whether a raw cell was blank unless that fact was
encoded before encryption.

## Required Client-Side Preparation

The client should still be simple, but it cannot be zero-logic. It must perform
data encoding before encryption.

Minimum client-side preparation:

```text
1. Read raw CSV.
2. Select agreed columns.
3. Normalize missing tokens: "", "NA", "NaN", "null", etc.
4. Convert fields to numeric values or categorical codes.
5. Either drop rows with required missing values or fill them.
6. Normalize numeric values for CKKS if approximate arithmetic is used.
7. Write an encryption-ready payload.
8. Encrypt payload.
```

This is not server-side EDA. It is input encoding.

## Missing Values Are Not A Good First Server-Only EDA

If the client sends only:

```text
Enc(raw_value)
```

then the server cannot cleanly compute:

```text
count_missing(column)
```

because missingness is not available as an encrypted numeric signal.

To compute missing counts, the encrypted payload must include one of:

```text
Enc(is_missing)
Enc(is_valid)
Enc(sentinel_encoded_value)
```

The first two are practical. The sentinel approach requires encrypted equality
or comparison and is much more expensive.

## Practical Decision

For V1, do not spend time building server-side missing-value detection from
encrypted raw values.

Use this rule:

```text
Client prepares clean numeric/categorical payload.
Server performs HE EDA only on prepared encrypted values.
```

Missing-value handling should happen before encryption:

```text
drop row
fill with median/zero/domain value
or send encrypted is_missing/is_valid mask
```

## Better First HE EDA

After preparation, the server can realistically compute:

```text
encrypted sum annual_inc
encrypted sum loan_amnt
encrypted sum dti
encrypted sum revol_util
encrypted average via decrypted sum / row_count
encrypted rule-based risk score
encrypted sum of already-prepared policy masks
```

These are more practical than trying to detect missing values inside encrypted
raw CSV data.

## Recommended V1 Path

### Client

Prepare these columns:

```text
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
term_60_month
loan_status
```

Apply:

```text
drop rows missing required numeric fields
map term to term_60_month: 36 -> 0, 60 -> 1
map loan_status: Fully Paid -> 1, Charged Off -> 0
normalize numeric columns to 0..1 for CKKS
```

Output:

```text
prepared_lending_values.csv
prepared_lending_manifest.json
```

Then encryption can run on the prepared values.

### Server

Run HE EDA over encrypted prepared columns:

```text
sum columns
compute rule score
sum rule score
return encrypted aggregate report
```

The server should not be responsible for:

```text
CSV parsing
missing-token interpretation
string category cleanup
normalization parameter fitting
raw-data validation
```

## If Missing Report Is Still Needed

Use an encrypted validity mask:

```text
Enc(is_valid_annual_inc)
Enc(is_valid_dti)
Enc(is_valid_revol_util)
...
```

Server computes:

```text
valid_count = sum Enc(is_valid)
missing_count = public_row_count - valid_count
```

This keeps the server from seeing row-level missingness, but it admits that
missingness must be encoded by the client before encryption.

