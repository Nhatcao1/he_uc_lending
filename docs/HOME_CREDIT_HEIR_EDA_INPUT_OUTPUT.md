# Home Credit HEIR EDA Input and Output Contract

This note describes the minimal data needed by each HEIR/CKKS EDA workload and
the small business-facing table returned after trusted decryption. It does not
require sending an entire CSV row when a workload uses only one or two columns.

## General Shape

```text
source column(s)
-> numeric category masks and numeric weights
-> CKKS encryption
-> HEIR-generated encrypted calculation
-> trusted decryption
-> compact analysis table
```

HEIR directly encrypts fixed-shape numeric vectors. It does not parse CSV files
or understand category strings. A source-side adapter maps category values to
numeric masks before encryption. Category labels can remain public analysis
metadata; the row-level category values are not sent to the HE server.

## 5.15 Example: Previous Contract Status

### Minimal Source Input

Notebook section `5.15.4` needs only one `previous_application` column:

| Required field | Purpose |
| --- | --- |
| `NAME_CONTRACT_STATUS` | Previous-loan category to count, such as `Approved`, `Canceled`, or `Refused` |

All other previous-loan fields are outside this workload.

### Normal Python Calculation and Output

```python
previous_application["NAME_CONTRACT_STATUS"].value_counts()
previous_application["NAME_CONTRACT_STATUS"].value_counts(normalize=True) * 100
```

The normal Python result is a small table:

| Contract status | Count | Percent |
| --- | ---: | ---: |
| Approved | 120,000 | 56.23% |
| Canceled | 60,000 | 28.12% |
| Refused | 33,500 | 15.65% |

### Encrypted Numeric Input

The source adapter constructs one numeric mask per requested label plus two
numeric weight vectors. For `N` valid category rows:

```text
Approved mask: [1, 0, 0, 1, ...]
Canceled mask: [0, 1, 0, 0, ...]
Refused mask:  [0, 0, 1, 0, ...]

count weight:   [1, 1, 1, 1, ...]
percent weight: [100/N, 100/N, 100/N, 100/N, ...]
```

All vectors above are CKKS-encrypted before the HEIR-generated runner receives
them. The server calculation for each category `g` is:

```text
encrypted_count[g]   = dot_product(encrypted_mask[g], encrypted_count_weight)
encrypted_percent[g] = dot_product(encrypted_mask[g], encrypted_percent_weight)
```

The percentage is therefore computed as an encrypted CKKS result; it is not
calculated after decryption.

### Decrypted HE Output

Trusted decryption returns the same business table, with CKKS approximation:

| Contract status | Decrypted count | Decrypted percent |
| --- | ---: | ---: |
| Approved | 120000.00001 | 56.23000% |
| Canceled | 60000.00000 | 28.12000% |
| Refused | 33499.99998 | 15.65000% |

The benchmark compares every decrypted value against the normal Python value.
The acceptance rule is absolute error less than or equal to `1e-4`.

## 5.14 Difference: Applicant Category by Default

For a `5.14.x` workload, the minimal source input has one applicant category
column plus `TARGET`:

| Required field | Purpose |
| --- | --- |
| Example category: `NAME_EDUCATION_TYPE` | Applicant group |
| `TARGET` | `1` for default and `0` for non-default |

The numeric preparation contains a group mask and a target mask. HEIR/CKKS
calculates:

```text
encrypted_count[g]         = dot_product(encrypted_group_mask[g], encrypted_ones)
encrypted_default_count[g] = dot_product(encrypted_group_mask[g], encrypted_target_mask)
```

After trusted decryption, the analysis table is:

| Education group | Count | Default count | Default rate |
| --- | ---: | ---: | ---: |
| Higher education | 74,863 | 4,009 | 5.3551% |
| Secondary / secondary special | 218,391 | 19,524 | 8.9399% |

## Benchmark Artifacts

Every completed HEIR benchmark writes these compact outputs in its run
directory:

| Artifact | Purpose |
| --- | --- |
| `benchmark_report.md` | Case description, timings, generated-source proof, result and accuracy tables |
| `heir_result.json` | Raw decrypted HE runner values used by the benchmark |
| `heir_accuracy.csv` | Python value, CKKS value, absolute error, and pass/fail for every label |
| `pandas_reference.csv` | Normal Python reference table |

