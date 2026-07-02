# Home Credit HE Data Preparation Limits

HE does not remove the need for client-side data preparation. For Home Credit,
the useful encrypted work is aggregate EDA after the client has encoded the raw
table into numeric masks/vectors.

## Must Happen On Client

- Read `application_train.csv`.
- Normalize missing tokens.
- Decide whether to drop null rows or map nulls into explicit buckets.
- Convert string categories into one-hot mask columns.
- Convert `TARGET` into a 0/1 mask.
- Convert `DAYS_BIRTH` into age years/buckets.
- Convert `DAYS_EMPLOYED == 365243` into an anomaly mask.
- Compute domain ratios before encryption.
- Pack/encrypt masks and numeric vectors.

## Can Happen On Server Under HE

- Sum encrypted numeric columns.
- Sum encrypted category/bucket masks.
- Sum encrypted `mask * TARGET`.
- Sum encrypted `mask * amount_column`.
- Return encrypted aggregate tables.

## Should Not Be Server HE Work

- Parsing CSV rows.
- Detecting null strings.
- Interpreting raw category names.
- Performing row-level joins.
- Removing rows from a dataset.
- Producing plaintext default rates.

The server should produce encrypted aggregate numerators and denominators. The
client decrypts and computes the final readable report.
