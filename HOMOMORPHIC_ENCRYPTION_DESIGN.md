# Homomorphic Encryption Design For Credit Rating

## Objective

Evaluate whether homomorphic encryption makes practical sense for the credit
rating notebooks in this folder, then define a small proof of concept that can
be coded without turning the whole ML workflow into an FHE research project.

The current notebooks are:

- `home-credit-complete-eda-feature-importance.ipynb`
- `lending-club-loan-defaulters-prediction.ipynb`

Both are Kaggle-style pipelines: load borrower/loan data, explore features,
clean/encode data, train plaintext models, and evaluate default risk. That shape
is important: FHE is a better fit for private inference than for the whole EDA
or training process.

## Recommended Use Case

Use homomorphic encryption for privacy-preserving credit score inference.

```text
Borrower/client owns sensitive features
        |
        | encode + encrypt selected numeric features
        v
Lender/scoring service evaluates a public or lender-owned model
        |
        | encrypted linear/logistic score
        v
Borrower/client decrypts score/result
```

This protects raw borrower inputs from the scoring service during inference. It
does not hide the model unless we add a separate model-protection design.

## What Makes Sense

### 1. CKKS Linear Credit Score

Best first version.

```text
score =
    w0
  + w1 * loan_amnt_scaled
  + w2 * int_rate_scaled
  + w3 * installment_scaled
  + w4 * annual_inc_scaled
  + w5 * dti_scaled
  + w6 * revol_util_scaled
  + ...
```

Why it fits:

- CKKS supports approximate real-valued arithmetic.
- Linear scoring uses ciphertext-plaintext multiplication plus addition.
- Multiplicative depth is low, usually depth 1 for public model weights.
- Existing `utility_bench` docs already cover linear score and dense layer
  benchmark patterns.

### 2. CKKS Tiny Neural/Dense Layer

Reasonable second version if we want to reuse the notebook's neural-network
theme, but only if the model is shallow.

```text
encrypted features -> dense layer -> encrypted logits
```

Start with no activation or a low-degree polynomial activation. Standard
sigmoid/ReLU are not native FHE operations.

### 3. Encrypted Partner-Side Scoring

Useful business story:

```text
Partner or telco has customer features
Bank has scoring model
Partner encrypts features
Bank computes encrypted risk score
Partner decrypts result or sends result to authorized party
```

This is a credible lending use case when raw customer data cannot be shared.

## What Does Not Make Sense For V1

### Full Encrypted EDA

The notebooks use correlations, plots, missing-value analysis, group-by counts,
and feature inspection. Doing all of that under FHE is expensive and often
awkward. EDA should remain plaintext on approved training data.

### FHE Training

Training RandomForest, XGBoost, or neural networks fully under FHE is not a good
starting point. Training requires many iterations, comparisons, branching, and
nonlinear functions. Use plaintext training, then export a small inference model.

### Tree-Based Model Inference First

RandomForest and XGBoost depend on comparisons:

```text
if dti <= threshold:
    go left
else:
    go right
```

Encrypted comparisons are possible but much more expensive than linear CKKS
arithmetic. Keep tree models as plaintext baselines, not the first FHE target.

## Proposed V1 Architecture

```text
uc_credit_rating/
  data/
    sample_credit_features.csv          # small derived fixture, no raw Kaggle dependency
  models/
    linear_credit_model.json            # feature list, scaling params, weights, bias
  src/
    prepare_credit_features.py          # creates V1 fixture/model from notebook logic
    plain_linear_score.py               # correctness baseline
  he/
    ckks_credit_score.cpp               # OpenFHE encrypted inference
  results/
    ckks_credit_score_results.csv       # timing + accuracy report
```

For the first commit, the Python path can be built before the C++ HE path:

```text
1. Select features
2. Train/export a simple logistic-regression-style linear model
3. Run plaintext scoring
4. Match the same formula in OpenFHE CKKS
5. Compare decrypted HE score against plaintext score
```

## Feature Set For First POC

Use LendingClub first because the notebook already has a compact binary target:

```text
loan_status: Fully Paid = 1, Charged Off = 0
```

Recommended numeric features:

```text
loan_amnt
int_rate
installment
annual_inc
dti
open_acc
pub_rec
revol_bal
revol_util
total_acc
mort_acc
pub_rec_bankruptcies
```

Categorical features can wait, or be represented with a few one-hot values after
plaintext preprocessing.

## HE Scheme Choice

Use CKKS for V1.

```text
scheme: CKKS
security: 128-bit
operation: encrypted feature vector, plaintext model weights
depth: 1 for linear score
first_mod_size: 60
scaling_mod_size: 50
ring_dimension: let OpenFHE choose first
batch_size: max slots / auto first
```

Use BinFHE later only for small exact lookup or threshold experiments, such as:

```text
employment_length_bucket -> risk_code
purpose_code -> risk_code
encrypted score > threshold
```

Do not mix CKKS and BinFHE in V1.

## Privacy Boundary

V1 protects:

- borrower numeric input features during inference
- intermediate score contributions
- final score until the client decrypts it

V1 does not protect:

- training data used to fit the model
- model weights, if weights are plaintext
- feature names and approximate schema
- metadata such as request timing, row count, and model version

If the model must also be hidden, evaluate encrypted weights in a later version.
That changes performance and depth assumptions.

## Evaluation Criteria

Record both ML and HE quality.

ML metrics:

```text
roc_auc
accuracy
precision
recall
confusion matrix
```

HE metrics:

```text
rows
feature_count
ciphertext_count
slots_per_ciphertext
setup_time_ms
encode_time_ms
encrypt_time_ms
he_eval_time_ms
decrypt_time_ms
decode_time_ms
total_he_time_ms
plain_time_ms
slowdown_vs_plain
max_abs_error
mean_abs_error
```

## Milestones

### Milestone 1: Plain POC

- Create a script that extracts/creates a small cleaned LendingClub fixture.
- Train or hard-code a simple linear/logistic model.
- Save `linear_credit_model.json`.
- Produce plaintext score and probability outputs.

### Milestone 2: HE Formula Match

- Implement the same weighted-sum formula in OpenFHE CKKS.
- Keep model weights plaintext.
- Decrypt only final score vectors for accuracy comparison.

### Milestone 3: Benchmark

- Run small, medium, and larger row counts.
- Compare CKKS score error against plaintext.
- Decide whether latency is acceptable for batch scoring.

### Milestone 4: Optional Extensions

- Add one-hot categorical features.
- Add a tiny dense layer.
- Add BinFHE threshold or small lookup as a separate experiment.
- Investigate model privacy with encrypted weights.

## Recommendation

Homomorphic encryption does make sense for this use case if we frame it as
private credit-risk inference, not as encrypted training or full encrypted EDA.

The strongest first build is:

```text
LendingClub numeric features
    -> plaintext logistic/linear baseline
    -> OpenFHE CKKS encrypted weighted score
    -> accuracy and timing report
```

This gives a real lending story, a technically feasible HE workload, and a
clear benchmark that can decide whether to continue.
