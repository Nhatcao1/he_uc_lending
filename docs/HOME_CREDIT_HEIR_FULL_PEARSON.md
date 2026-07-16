# HEIR CKKS Full Pearson Trial

## Purpose

This benchmark tests one full Pearson correlation calculation on encrypted Home
Credit numeric data. The default pair is `AMT_CREDIT` and `AMT_GOODS_PRICE`.
It is deliberately a pair-by-pair experiment, not an attempt to reproduce
`pandas.DataFrame.corr()` across an arbitrary dataframe.

## Why It Cannot Mirror `DataFrame.corr()` Directly

Plain pandas can inspect columns, remove null pairs, discover ranges, choose
all column pairs, divide, and take square roots as one convenience call. A HE
server cannot safely make those data-dependent decisions over ciphertexts.

For each requested pair, the trusted preparation stage therefore:

1. selects two known numeric features;
2. removes rows missing either feature;
3. normalizes each feature to `[0, 1]` using declared bounds;
4. writes fixed-shape numeric tensors and public approximation calibration.

The benchmark must be run and accepted feature pair by feature pair. It does
not claim that an existing Python correlation package is homomorphically
implemented in full.

## Encrypted Flow

HEIR-generated CKKS code provides the packed encrypted dot-product primitive.
It calculates the following encrypted moments for normalized `x` and `y`:

```text
n       = dot(ones, ones)
mean_x  = dot(x, 1/n)
mean_y  = dot(y, 1/n)
mean_xy = dot(x, y/n)
mean_x2 = dot(x, x/n)
mean_y2 = dot(y, y/n)
```

The same CKKS runner then uses OpenFHE ciphertext operations:

```text
covariance = mean_xy - mean_x * mean_y
variance_x = mean_x2 - mean_x^2
variance_y = mean_y2 - mean_y^2
z          = variance_x * variance_y
r          = covariance / sqrt(z)
```

`1 / sqrt(z)` is evaluated on ciphertext with OpenFHE
`EvalChebyshevFunction` over a calibrated interval. The calibration scalar is
public aggregate benchmark metadata. It keeps the approximation input near
`1`, rather than exposing individual values.

## Boundary And Acceptance

- HEIR generates the encrypted dot-product source.
- OpenFHE performs the remaining encrypted arithmetic and Chebyshev
  approximation inside the same benchmark runner.
- The benchmark decrypts only to compare six moments and final `r` with the
  notebook-style pandas reference.
- Moment values use `1e-4` absolute tolerance by default. The final Pearson
  coefficient uses a looser approximation tolerance, initially `0.02`.

The generated `benchmark_report.md` and `heir_accuracy.csv` preserve the
feature pair, normalization bounds, encrypted result, timing, and accuracy
evidence.
