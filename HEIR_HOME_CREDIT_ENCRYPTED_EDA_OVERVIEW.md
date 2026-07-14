# HEIR Compiler for Home Credit Encrypted EDA

## 1. Purpose

This note evaluates whether the Home Credit exploratory data analysis workflow can be reproduced more clearly and practically using the **HEIR compiler** instead of implementing every homomorphic-encryption operation directly with low-level OpenFHE APIs.

The intended goal is not to execute an unchanged pandas notebook over encrypted data.

The practical goal is:

> Reproduce selected Home Credit EDA outputs using client-prepared encrypted tensors and HEIR-compiled homomorphic-encryption kernels.

The focus is aggregate EDA, rule-based calculations, fixed bucket reports, and optional linear scoring. Fully encrypted machine-learning training is outside the initial scope.

---

## 2. Main Conclusion

HEIR can make the encrypted-computation code substantially clearer than handwritten OpenFHE C++.

Instead of manually managing operations such as:

- ciphertext construction;
- packed encoding;
- multiplication;
- rotations;
- relinearization;
- rescaling or modulus switching;
- multiplicative-depth planning;
- serialization;
- backend-specific APIs;

the developer can describe a restricted numeric computation using high-level code and allow the compiler to lower it into a supported homomorphic-encryption backend.

However, HEIR does not provide encrypted pandas.

It does not directly support a workflow such as:

```python
df.groupby("NAME_INCOME_TYPE")["TARGET"].mean()
```

over an encrypted DataFrame.

The original notebook must still be redesigned into three layers:

```text
Client-side preprocessing
    -> encrypted numeric and mask tensors
    -> HEIR-compiled server computation
    -> client-side decryption and reporting
```

The compiler improves the HE kernel implementation. It does not remove the need to redesign the data representation and analytical workflow.

---

## 3. Recommended Privacy-Preserving Architecture

```text
Raw Home Credit data
        |
        | Client-side processing
        | - clean values
        | - handle missing data
        | - derive ratios
        | - create category masks
        | - create fixed bucket masks
        | - normalize numeric values
        | - encrypt prepared tensors
        v
Encrypted payloads
        |
        | HE server
        | - encrypted sums
        | - encrypted masked sums
        | - encrypted weighted arithmetic
        | - optional fixed comparisons or selections
        v
Encrypted aggregate results
        |
        | Client decrypts
        v
Tables, metrics, and charts
```

The HE server should not receive:

- the raw CSV;
- raw applicant rows;
- plaintext category membership;
- plaintext target values;
- the secret decryption key;
- plaintext row-level outputs.

The server may still observe operational metadata such as:

- row count or approximate row count;
- selected feature names;
- category and bucket definitions;
- ciphertext count;
- payload size;
- execution time;
- job type.

---

## 4. What HEIR Improves

| Area | Handwritten OpenFHE | HEIR-based implementation |
|---|---|---|
| Business computation | Mixed with HE library calls | Expressed as arithmetic functions |
| Backend-specific APIs | Written manually | Generated through compiler lowering |
| Relinearization and rescaling | Explicit developer concern | Can be inserted or optimized by compiler passes |
| Packing and layout | Mostly manual | May be assisted by compiler optimization |
| Static loops | Manually implemented | Can be unrolled or lowered |
| Dead computations | Developer must avoid them | Compiler can remove unused operations |
| Testing | Separate plaintext and HE code | Easier to compare original and encrypted execution |
| Backend experimentation | Significant rewrite | Same logical kernel may target another supported pipeline |

Conceptually, a masked operation can be written as a small kernel:

```python
def masked_target(category_mask, target_mask):
    return category_mask * target_mask
```

The implementation is clearer because the code represents the intended computation rather than the mechanics of OpenFHE.

---

## 5. What HEIR Does Not Solve

HEIR does not eliminate the semantic mismatch between pandas and homomorphic encryption.

Pandas operates with:

```text
dynamic DataFrames
strings
indexes
missing-value semantics
dynamic grouping
sorting
variable-sized outputs
arbitrary Python functions
```

Homomorphic encryption works best with:

```text
fixed-size numeric tensors
binary masks
known categories
known bucket boundaries
bounded arithmetic circuits
fixed loop limits
controlled multiplicative depth
data-oblivious operations
```

Therefore, the difficult part remains the transformation of notebook operations into HE-compatible representations.

The following work still has to be designed manually:

- which columns are processed;
- which categories are supported;
- how strings are encoded;
- how missing values are represented;
- which histogram bins are fixed in advance;
- which operations execute before encryption;
- which results are decrypted;
- how much metadata is visible to the server;
- which HE scheme is appropriate for each workload.

---

## 6. Home Credit Operations That Fit Well

### 6.1 Target Counts

Original analytical intent:

```python
application_train["TARGET"].value_counts()
```

HE representation:

```text
TARGET as an encrypted 0/1 vector
```

Encrypted computation:

```text
default_count = sum(TARGET)
non_default_count = public_row_count - default_count
```

This is simple, useful, and suitable for an initial proof of concept.

---

### 6.2 Missing-Value Audit

Original analytical intent:

```python
application_train.isnull().sum()
```

Recommended HE design:

1. The client creates one `is_null` binary vector per selected column.
2. The client encrypts the vectors.
3. The server sums each encrypted vector.
4. The client decrypts the missing counts.
5. Missing percentages are calculated after decryption using the public row count.

The HE server does not detect `NaN` directly. The client supplies the numerical missing-value masks.

---

### 6.3 Category Counts and Default Rates

This is the strongest Home Credit aggregate EDA use case.

For a category such as `NAME_INCOME_TYPE`, the client creates one-hot masks:

```text
Working
Commercial associate
Pensioner
State servant
Other
```

The client also creates the target mask.

The server calculates:

```text
category_count
    = sum(category_mask)

category_default_count
    = sum(category_mask * target_mask)
```

After decryption, the client calculates:

```text
default_rate
    = category_default_count / category_count
```

The same structure can be used for:

- `NAME_INCOME_TYPE`;
- `NAME_EDUCATION_TYPE`;
- `NAME_FAMILY_STATUS`;
- `NAME_HOUSING_TYPE`;
- `OCCUPATION_TYPE`;
- selected `ORGANIZATION_TYPE` values;
- `NAME_TYPE_SUITE`.

Large-cardinality features should be limited to selected categories or grouped into an `OTHER` category.

---

### 6.4 Numeric Sums and Averages

Suitable columns include:

```text
AMT_CREDIT
AMT_INCOME_TOTAL
AMT_ANNUITY
AMT_GOODS_PRICE
EXT_SOURCE_1
EXT_SOURCE_2
EXT_SOURCE_3
```

The server can calculate encrypted sums.

The client decrypts the totals and calculates averages using a public or decrypted count:

```text
average = decrypted_sum / count
```

For category-specific averages:

```text
masked_credit_sum
    = sum(category_mask * AMT_CREDIT)

average_credit
    = masked_credit_sum / category_count
```

The same pattern applies to income, annuity, goods price, and selected numeric features.

---

### 6.5 Fixed-Bucket Reports

The client converts difficult numeric or date-derived values into predefined bucket masks before encryption.

Recommended examples:

```text
Age buckets derived from DAYS_BIRTH
DAYS_EMPLOYED normal/anomaly buckets
EXT_SOURCE score buckets
Credit-to-income ratio buckets
Annuity-to-income ratio buckets
Employment-duration ratio buckets
```

For every bucket, the server calculates:

```text
bucket_count
bucket_default_count
optional masked numeric sums
```

The client decrypts the aggregates and reports trends such as:

```text
default rate by age bucket
default rate by EXT_SOURCE bucket
default rate by credit-to-income bucket
```

Fixed bucket reports are much more practical than asking the HE server to discover histogram boundaries or quantiles.

---

### 6.6 Linear Rule or Risk Score

CKKS is suitable for a public weighted sum such as:

```text
score =
    bias
  + w1 * normalized_credit
  + w2 * normalized_income
  + w3 * normalized_annuity
  + w4 * normalized_age
  + w5 * EXT_SOURCE_2
  + w6 * credit_income_ratio
```

This is low-depth arithmetic and maps naturally to HE.

The score should be treated as one of the following:

- a documented public policy formula;
- a separately trained plaintext linear model;
- an experimental rule-based score.

It should not be presented as a model learned under HE unless encrypted training has actually been implemented.

---

## 7. Operations That Are Possible but Require Redesign

### 7.1 Threshold Conditions

Example:

```python
application_train["AMT_INCOME_TOTAL"] > 250000
```

Options:

#### Preferred initial approach

The client creates the binary threshold mask and encrypts it.

```text
income_above_250k_mask
```

The server only sums the encrypted mask or combines it with the target mask.

#### Later approach

Perform an encrypted comparison.

This is possible with appropriate Boolean or lookup-oriented HE techniques, but comparison is significantly more expensive than addition and multiplication.

HEIR can make the comparison code look cleaner, but it cannot make the underlying cryptographic operation inexpensive.

---

### 7.2 If/Else Logic

A secret-dependent condition cannot behave like a normal CPU branch because the server must not learn which path was selected.

Conceptually:

```python
if encrypted_condition:
    result = a
else:
    result = b
```

must become an oblivious selection such as:

```text
result = condition * a + (1 - condition) * b
```

Both branches are represented in the encrypted computation.

Simple fixed selections are possible. Deep and highly branched decision logic remains costly.

---

### 7.3 Variance

Variance can be computed from encrypted aggregate terms:

```text
sum(x)
sum(x²)
count
```

After decryption:

```text
mean = sum(x) / count
variance = sum(x²) / count - mean²
```

This is feasible for selected numeric columns.

It should not be applied indiscriminately to every column because it increases ciphertext operations and multiplicative depth.

---

### 7.4 Correlation

For two selected variables, correlation can be derived from:

```text
sum(x)
sum(y)
sum(x²)
sum(y²)
sum(xy)
count
```

This is technically possible.

A full notebook-wide correlation matrix is not a good first implementation because the number of feature pairs grows quadratically.

Use a small, documented set of relevant feature pairs instead.

---

### 7.5 Ratios and Division

Direct encrypted division is not a simple primitive in most HE workflows.

Preferred options are:

1. calculate the ratio before encryption;
2. normalize with a public scale;
3. multiply by a prepared reciprocal;
4. use a bounded polynomial approximation where necessary.

For Home Credit EDA, client-side ratio creation is usually the cleanest design.

Recommended ratios include:

```text
CREDIT_INCOME_PERCENT
ANNUITY_INCOME_PERCENT
CREDIT_TERM
DAYS_EMPLOYED_PERCENT
```

---

### 7.6 Missing-Value Imputation

Encrypted aggregate statistics can support imputation decisions.

For example, the server may calculate an encrypted group sum and count.

However, replacing individual encrypted missing values with group-specific values requires:

- missing-value masks;
- group masks;
- encrypted selection;
- known fixed groups;
- additional multiplications.

For the first version, perform imputation on the client and use HE to report missingness or aggregate imputation statistics.

---

## 8. Poor Candidates for the Initial HE Notebook

### 8.1 Dynamic GroupBy

A pandas `groupby()` discovers groups and constructs variable-size outputs dynamically.

An HE implementation normally requires categories to be known in advance and represented by fixed masks.

Use explicit category masks rather than dynamic encrypted grouping.

---

### 8.2 Sorting

Sorting encrypted data requires many encrypted comparisons and swaps.

It is much more expensive than arithmetic aggregation.

Avoid encrypted sorting in the first proof of concept.

---

### 8.3 Median, Quantiles, and Automatic Outlier Discovery

Median and quantiles normally require sorting, selection, or specialized approximate algorithms.

For practical encrypted EDA, use:

- public fixed thresholds;
- client-created threshold masks;
- predefined buckets;
- encrypted counts per bucket.

---

### 8.4 Returning Filtered Rows

A normal filter:

```python
df[df["DAYS_EMPLOYED"] > threshold]
```

returns a variable number of rows.

Under HE, the server cannot easily compact matching encrypted rows without revealing information or using costly oblivious data movement.

Prefer returning:

```text
encrypted matching count
encrypted matching sum
encrypted bucket statistics
```

rather than filtered applicant records.

---

### 8.5 Arbitrary Pandas Apply

Functions passed to `.apply()` may contain dynamic Python behavior, type checks, missing-value logic, or irregular control flow.

Such functions cannot generally be compiled directly as HE kernels.

Rewrite each useful rule as a small fixed arithmetic or Boolean function.

---

### 8.6 Raw Strings and Dates

HEIR does not make raw strings or date parsing naturally homomorphic.

Before encryption, the client should convert them into:

```text
numeric codes
one-hot category masks
year values
age values
fixed date buckets
binary flags
```

---

### 8.7 Full Multi-Table Home Credit Joins

The complete Home Credit dataset contains multiple related tables.

Encrypted joins by `SK_ID_CURR` would require expensive private equality matching and data movement.

The initial implementation should remain focused on:

```text
application_train.csv
```

Historical bureau, POS, installment, and card-table feature engineering should initially remain client-side.

---

### 8.8 Tree-Based Training and Fully Encrypted Training

Random forests, gradient-boosted trees, and neural-network training involve:

- repeated iterations;
- comparisons;
- branching;
- nonlinear functions;
- gradient updates;
- data-dependent control flow.

Fully encrypted training is not a sensible starting point for this project.

A later encrypted inference experiment using a linear or polynomial model is much more realistic.

---

## 9. Recommended HE Scheme Split

### 9.1 BGV or BFV

Use for:

```text
0/1 masks
target flags
category masks
missing-value masks
exact counts
small integer features
```

These schemes are appropriate when exact integer semantics matter.

---

### 9.2 CKKS

Use for:

```text
AMT_CREDIT
AMT_INCOME_TOTAL
AMT_ANNUITY
AMT_GOODS_PRICE
EXT_SOURCE values
numeric sums
averages
variance terms
linear scores
approximate ratios
```

CKKS supports approximate real-valued arithmetic and packed computation.

Small numerical error must be measured against plaintext results.

---

### 9.3 Boolean or TFHE-Style Backend

Use later for narrow workloads involving:

```text
encrypted comparisons
exact threshold decisions
small lookup tables
Boolean rule circuits
```

Do not combine several schemes in the first notebook.

Build and benchmark each primitive separately before designing any hybrid pipeline.

---

## 10. Recommended Notebook Structure

The notebook should demonstrate a hybrid workflow rather than pretend that the complete pandas notebook executes under HE.

### Section 1 — Configuration and Data Loading

```text
Load application_train.csv
Select a documented subset of rows and columns
Define categories and bucket boundaries
Set reproducible configuration
```

---

### Section 2 — Client-Side Data Preparation

Create:

```text
target mask
category masks
missing-value masks
bucket masks
scaled numeric vectors
optional precomputed ratios
```

Validate shapes, types, ranges, and missing-value handling before encryption.

---

### Section 3 — Plaintext Baseline

Calculate the expected outputs locally:

```text
target counts
missing counts
category counts
category default counts
numeric sums
masked numeric sums
bucket counts
bucket default counts
optional linear scores
```

These values form the correctness reference.

---

### Section 4 — Small HEIR Kernels

Keep each compiled function focused.

Recommended kernels:

```text
elementwise mask * target
elementwise mask * numeric value
packed sum reduction
sum of squares
selected pair product
linear weighted sum
optional fixed select
```

Avoid one large function that attempts to reproduce the entire notebook.

---

### Section 5 — Encryption, Evaluation, and Decryption

Log the phases separately:

```text
setup and key generation
encoding
encryption
server-side HE evaluation
result serialization
decryption
decoding
```

For the final architecture, ensure the secret key remains on the client.

---

### Section 6 — Accuracy Validation

Compare plaintext and decrypted HE results.

Record:

```text
plaintext value
decrypted HE value
absolute error
relative error
maximum absolute error
mean absolute error
count mismatch
decision mismatch where applicable
```

For BFV/BGV counts, verify exact equality.

For CKKS values, define acceptable numerical-error thresholds.

---

### Section 7 — Performance Evaluation

Record at minimum:

```text
rows
selected column count
category count
bucket count
ciphertext count
slots per ciphertext
setup time
encode time
encrypt time
HE evaluation time
decrypt time
decode time
payload size
result size
peak memory where available
```

Performance should be reported separately for each workload and scheme.

---

### Section 8 — Decrypted Reports and Charts

Produce charts only after decryption.

Recommended outputs:

```text
target distribution
missing percentage by selected column
default rate by income type
default rate by education type
default rate by age bucket
default rate by EXT_SOURCE bucket
average credit by category
average income by category
```

The final plot may resemble the original notebook output even though the server only processed encrypted aggregates.

---

## 11. Realistic Replication Scope

| Notebook layer | Realistic level |
|---|---|
| Data loading | Fully supported on client |
| Cleaning | Fully supported on client |
| Missing-value transformation | Fully supported on client |
| Categorical encoding | Fully supported on client |
| Numeric aggregate EDA | Strong HE candidate |
| Category/default tables | Strong HE candidate |
| Fixed-bin distributions | Strong HE candidate |
| Selected variance | Feasible |
| Selected correlation pairs | Feasible but more expensive |
| Threshold rules | Feasible, preferably with client masks |
| Dynamic filtering | Poor fit |
| Quantile discovery | Poor fit |
| Sorting | Poor fit |
| Multi-table encrypted joins | Poor fit for V1 |
| Plotting | Fully supported after decryption |
| Fully encrypted ML training | Not realistic for V1 |
| Linear encrypted inference | Strong later candidate |

The useful objective is not to reproduce the same source code.

The useful objective is to reproduce selected analytical outputs while preserving the privacy of row-level applicant data from the HE server.

---

## 12. Recommended First Implementation

The first HEIR-based Home Credit notebook should contain:

1. Encrypted target counts.
2. Encrypted missing-value counts.
3. Encrypted category counts.
4. Encrypted category default counts.
5. Encrypted category-specific numeric sums.
6. Fixed bucket default-rate reports.
7. One CKKS linear-score demonstration.
8. Plaintext-versus-HE correctness comparison.
9. HE-specific performance and payload measurements.

Recommended first feature subset:

```text
TARGET
NAME_INCOME_TYPE
NAME_EDUCATION_TYPE
NAME_FAMILY_STATUS
AMT_CREDIT
AMT_INCOME_TOTAL
AMT_ANNUITY
DAYS_BIRTH
DAYS_EMPLOYED
EXT_SOURCE_2
```

Recommended first derived artifacts:

```text
target mask
selected income-type masks
selected education masks
age bucket masks
employment anomaly mask
EXT_SOURCE_2 bucket masks
normalized credit vector
normalized income vector
normalized annuity vector
```

---

## 13. Suggested Implementation Boundary

### Client responsibilities

```text
Read raw CSV
Validate schema
Clean data
Handle missing values
Parse dates and special values
Create ratios
Normalize numeric columns
Create one-hot and bucket masks
Encrypt prepared tensors
Retain secret key
Decrypt aggregate results
Create final report and charts
```

### Server responsibilities

```text
Validate manifest and payload shape
Load public and evaluation keys
Execute the selected HEIR-generated kernel
Return encrypted aggregate results
Record performance metadata
Never request the client secret key
Never require the raw CSV
```

### Compiler responsibilities

```text
Lower restricted arithmetic kernels
Optimize the intermediate representation
Insert supported ciphertext-management operations
Generate or connect to backend-specific evaluation code
Help separate logical computation from low-level HE API mechanics
```

The compiler is not responsible for automatically converting an arbitrary pandas workflow into an efficient encrypted program.

---

## 14. Final Assessment

HEIR is a worthwhile direction for this project because it improves:

- code clarity;
- maintainability;
- separation of business logic from HE mechanics;
- experimentation with different schemes and backends;
- repeatability of small encrypted kernels;
- the credibility of the compiler-based prototype.

It does not eliminate:

- HE-compatible data modeling;
- client-side preprocessing;
- fixed-shape restrictions;
- comparison costs;
- encrypted control-flow costs;
- the difficulty of sorting, joins, and quantiles;
- the need to benchmark accuracy and performance.

The recommended project statement is:

> The prototype reproduces selected Home Credit aggregate EDA reports using client-prepared encrypted tensors, HEIR-compiled homomorphic-encryption kernels, and client-side decryption and visualization.

This is more realistic and technically defensible than claiming that the complete Home Credit pandas notebook is executed over encrypted data.

---

## 15. Implementation Plan: HEIR Path First Changes

The first HEIR implementation should not replace the current OpenFHE benchmark
immediately. The safe path is to add a parallel HEIR experiment, prove one small
kernel, then expand.

### 15.1 Proposed Code Layout

```text
code/heir/home_credit/
    README.md
    kernels/
        masked_default_count.*
        masked_sum.*
        sum_vector.*
    scripts/
        compile_kernel.py
        run_kernel_benchmark.py
    generated/
        .gitkeep

code/benchmarks/
    home_credit_heir_eda_benchmark.py
```

The Python files should orchestrate data preparation, HEIR compilation, command
execution, correctness comparison, timing capture, and markdown report creation.
The HEIR kernel files should stay small and represent only the encrypted
arithmetic kernel.

### 15.2 First Kernel to Implement

Start with the same business calculation already tested in the OpenFHE path:

```text
default_count_for_group = sum(group_mask * target_mask)
```

This corresponds to notebook outputs such as:

```python
temp = application_train["NAME_EDUCATION_TYPE"].value_counts()
temp_y1.append(np.sum(application_train["TARGET"][application_train["NAME_EDUCATION_TYPE"] == val] == 1))
```

The HEIR kernel should represent only the fixed-shape arithmetic:

```text
input:
    encrypted group_mask vector
    encrypted target_mask vector

operation:
    elementwise multiply
    packed sum / reduction

output:
    encrypted default count
```

Category discovery, string handling, missing handling, and report formatting
remain outside the HEIR kernel.

### 15.3 First Python Benchmark Wrapper

Create a new benchmark wrapper:

```text
code/benchmarks/home_credit_heir_eda_benchmark.py
```

Its first workload should be:

```text
app_target_by_education_type
```

The wrapper should:

1. Load `application_train.csv`.
2. Run the notebook-style pandas baseline.
3. Prepare one selected group mask and the target mask.
4. Compile or call the HEIR kernel.
5. Execute the encrypted computation.
6. Decrypt or decode results according to the selected backend path.
7. Compare correctness against pandas.
8. Write a markdown benchmark report.

The initial report should use the same measurement categories as the OpenFHE
benchmark:

```text
pandas_reference_seconds
prepare_wall_seconds
heir_compile_seconds
encode_seconds
encrypt_seconds
he_eval_seconds
decrypt_seconds
total_seconds
artifact sizes
absolute error
relative error
```

### 15.4 What Not to Change First

Do not remove the current OpenFHE C++ implementation yet.

Do not rewrite the async web UI yet.

Do not attempt the full Home Credit notebook through HEIR.

Do not start with correlation, joins, random forests, sorting, quantiles, or
dynamic groupby.

Do not combine multiple schemes in the first HEIR benchmark.

### 15.5 Migration Order

Recommended order:

1. **Scaffold HEIR folder and Python wrapper.**
   Keep it separate from existing OpenFHE benchmark code.

2. **Implement one tiny kernel: `sum(mask * target)`.**
   Use the education-by-target case because it is already tested and easy to
   explain.

3. **Add markdown reporting.**
   The report must show the notebook-style pandas reference code and the HEIR
   kernel intent.

4. **Compare three paths.**

   ```text
   pandas notebook reference
   current handwritten OpenFHE benchmark
   HEIR kernel path
   ```

5. **Only after correctness passes, add `sum(mask)` and `sum(mask * amount)`.**
   These unlock category count and category-specific numeric totals.

6. **Then expand to 5.14 categorical target reports.**
   The same kernel pattern applies to income, family, occupation, education,
   housing, organization, and suite type.

7. **Then consider numeric sums and selected variance/correlation.**
   These require more careful CKKS scale/depth planning.

### 15.6 Decision Gate

The HEIR path is worth expanding only if the first benchmark shows at least one
of these benefits:

```text
less handwritten HE code
clearer kernel expression
comparable correctness
reasonable compile/runtime overhead
cleaner generated artifact story
easier backend experimentation
```

If the first HEIR kernel is harder to build and maintain than the current
OpenFHE path, keep HEIR as a research branch and continue the main prototype
with OpenFHE.
