# HE Use Cases And Notebook Code Context

Purpose: keep the useful notebook context in Markdown so future work does not
need to re-read the `.ipynb` files.

Scope for this note: put ML aside. Focus on credit/lending operations that can
be tried with homomorphic encryption as analytics, rules, lookup, thresholding,
or simple arithmetic.

## Source Notebooks

```text
uc_credit_rating/lending-club-loan-defaulters-prediction.ipynb
uc_credit_rating/home-credit-complete-eda-feature-importance.ipynb
```

## Best HE Use-Case Candidates

| Priority | Use case | Notebook context | Sensitive input | HE operation | Scheme to try | Why it is worth trying | First POC shape |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Encrypted missing-value audit | Home Credit cells 29, 31, 33, 35, 37, 39, 41; LendingClub cell 106 | Per-column null flags | Sum encrypted `is_null` flags per column | BFV/BGV for exact count, or CKKS for approximate count | Simple and useful for privacy-preserving data quality reporting | Client encrypts 0/1 null indicators, server sums, client decrypts counts |
| 2 | Encrypted outlier/exposure counts | LendingClub cells 33, 34, 35, 55, 57, 58, 59, 61, 62, 64, 138 | Income, DTI, account count, revolving balance | Count records above policy thresholds | BinFHE for encrypted comparison, or plaintext threshold mask + CKKS/BFV sum | Lending policy often needs counts like `annual_inc > 250000` or `dti >= 50` | Start with plaintext-generated masks, then try encrypted threshold later |
| 3 | Encrypted portfolio distribution | LendingClub cells 8, 14, 31; Home Credit cells 44, 46, 48, 52 | Loan status, amount, income, credit amount | Count, sum, mean, histogram bins | BFV/BGV for counts; CKKS for amounts/means | Common reporting use case: dataset owner reveals aggregates, not row-level data | Encrypt bin membership or numeric amount columns and aggregate |
| 4 | Encrypted category-by-outcome counts | Home Credit cells 80, 82, 84, 86, 88, 90, 92 | Category membership and target/default flag | Conditional sums / group counts | BFV/BGV if one-hot flags are encrypted; CKKS if approximate counts are acceptable | Captures “risk by income type/family status/occupation” without raw rows | Encode each category as a binary mask and sum default/non-default masks |
| 5 | Encrypted binary risk flags | LendingClub cells 71, 72 | `pub_rec`, `mort_acc`, `pub_rec_bankruptcies` | Map numeric value to 0/1 flag | BinFHE LUT/comparison; or plaintext flag then encrypted downstream | Small rule functions are natural HE experiments | First build with plaintext flag creation, encrypt flags for aggregate scoring |
| 6 | Encrypted small-domain lookup | LendingClub cells 27, 113, 117, 120, 122; Home Credit cell 137 | Home ownership, term, purpose, zip bucket, categorical code | Lookup category/code -> risk code | BinFHE LUT for small domains | Good fit for exact small-domain categorical risk rules | Start with `term` or `home_ownership`; avoid huge zip/purpose LUT first |
| 7 | Encrypted rule-based lending score | LendingClub cells 31, 55, 57, 58, 59, 62, 71, 72, 113 | Numeric credit features and binary flags | Weighted sum, ratios, additions | CKKS | Not ML: a policy score such as debt burden + utilization + public-record flags | `score = a*dti + b*revol_util + c*pub_rec + d*term + bias` |
| 8 | Encrypted income/loan ratio | LendingClub cells 14, 31, 33; Home Credit cells 44, 46, 48 | Income, loan amount, credit amount | Multiply by reciprocal, add/subtract, compare later | CKKS | Lending rules often use affordability ratios | Compute `loan_amnt / annual_inc` approximately via plaintext reciprocal or precomputed normalized features |
| 9 | Encrypted imputation support aggregate | LendingClub cells 98, 100, 102, 103, 104 | `mort_acc`, `total_acc` | Group average/count | CKKS/BFV depending on exactness need | The notebook imputes `mort_acc` using grouped averages; HE can support privacy-preserving aggregate stats | Start with encrypted sums/counts by plaintext `total_acc` bucket |
| 10 | Encrypted date/year bucket analytics | LendingClub cells 44, 125, 127 | `issue_d`, `earliest_cr_line` year | Bucket count / age calculation | BFV/BGV for counts, CKKS for years as numeric | Simple temporal risk analytics | Convert year to plaintext bucket locally, then encrypted bucket counts |

## Recommendation For First Non-ML POC

Start with three small experiments:

```text
1. Encrypted missing-value counts
2. Encrypted policy-threshold counts with plaintext masks
3. CKKS rule-based lending score
```

Reason:

- They use notebook logic directly.
- They avoid expensive encrypted training and tree inference.
- They map cleanly to OpenFHE primitives already explored elsewhere in this repo.
- They give quick yes/no results on correctness, latency, and ciphertext size.

## HE Mapping Notes

### CKKS

Use for approximate real-valued arithmetic:

```text
annual_inc
dti
revol_util
revol_bal
loan_amnt
installment
weighted policy score
mean / average
ratio after scaling
```

### BFV/BGV

Use for exact-ish integer arithmetic over encoded values:

```text
0/1 masks
counts
small integer flags
categorical one-hot sums
```

### BinFHE

Use later for exact Boolean/small-domain operations:

```text
encrypted threshold checks
encrypted binary flags
small lookup tables
```

Do not start by mixing CKKS and BinFHE in one pipeline. Build each primitive
separately first.

## LendingClub Notebook Context

### Data Load

Source: `lending-club-loan-defaulters-prediction.ipynb`, cell 3.

```python
data = pd.read_csv("/kaggle/input/lending-club-dataset/lending_club_loan_two.csv")
data.head()
```

### Loan Status Counts

Source: cell 8.

HE idea: encrypted count of records per status, or count of a binary flag.

```python
data['loan_status'].value_counts().hvplot.bar(
    title="Loan Status Counts", xlabel='Loan Status', ylabel='Count',
    width=500, height=350
)
```

### Loan Amount By Status

Source: cell 14.

HE idea: encrypted count, sum, min/max approximation, or mean loan amount by
status. Start with count and sum.

```python
data.groupby(by='loan_status')['loan_amnt'].describe()
```

### Home Ownership Cleanup

Source: cell 27.

HE idea: small-domain category normalization before encrypted category counts or
small-domain lookup.

```python
data.loc[(data.home_ownership == 'ANY') | (data.home_ownership == 'NONE'), 'home_ownership'] = 'OTHER'
data.home_ownership.value_counts()
```

### Interest Rate And Annual Income Distributions

Source: cell 31.

HE idea: encrypted histogram/bin counts for `int_rate` and `annual_inc`; CKKS
sum/mean for numeric columns.

```python
int_rate = data.hvplot.hist(
    y='int_rate', by='loan_status', alpha=0.3, width=350, height=400,
    title="Loan Status by Interest Rate", xlabel='Interest Rate', ylabel='Loans Counts',
    legend='top'
)

annual_inc = data.hvplot.hist(
    y='annual_inc', by='loan_status', bins=50, alpha=0.3, width=350, height=400,
    title="Loan Status by Annual Income", xlabel='Annual Income', ylabel='Loans Counts',
    legend='top'
).opts(xrotation=45)

int_rate + annual_inc
```

### Income Threshold Counts

Sources: cells 33, 34, 35.

HE idea: policy threshold count. Easiest first version uses plaintext-generated
0/1 masks and encrypted summation. Later version uses encrypted comparison.

```python
print((data[data.annual_inc >= 250000].shape[0] / data.shape[0]) * 100)
print((data[data.annual_inc >= 1000000].shape[0] / data.shape[0]) * 100)
```

```python
data.loc[data.annual_inc >= 1000000, 'loan_status'].value_counts()
```

```python
data.loc[data.annual_inc >= 250000, 'loan_status'].value_counts()
```

### Date Conversion

Source: cell 44.

HE idea: convert dates to local plaintext year/bucket first, then encrypt bucket
masks or numeric year.

```python
data['issue_d'] = pd.to_datetime(data['issue_d'])
data['earliest_cr_line'] = pd.to_datetime(data['earliest_cr_line'])
```

### DTI And Account Thresholds

Sources: cells 52, 55, 57, 58, 59, 61, 62, 64.

HE idea: policy threshold counts for debt-to-income, open accounts, total
accounts, revolving utilization, and revolving balance.

```python
data.dti.value_counts()
```

```python
data.loc[data['dti']>=50, 'loan_status'].value_counts()
```

```python
print(data.shape)
print(data[data.open_acc > 40].shape)
```

```python
print(data.shape)
print(data[data.total_acc > 80].shape)
```

```python
print(data.shape)
print(data[data.revol_util > 120].shape)
```

```python
data[data.revol_util > 200]
```

```python
print(data.shape)
print(data[data.revol_bal > 250000].shape)
```

```python
data.loc[data.revol_bal > 250000, 'loan_status'].value_counts()
```

### Binary Risk Flag Functions

Sources: cells 71, 72.

HE idea: exact binary flag creation is a good BinFHE/LUT candidate. For a first
pipeline, create the flags locally and encrypt the resulting 0/1 values.

```python
def pub_rec(number):
    if number == 0.0:
        return 0
    else:
        return 1

def mort_acc(number):
    if number == 0.0:
        return 0
    elif number >= 1.0:
        return 1
    else:
        return number

def pub_rec_bankruptcies(number):
    if number == 0.0:
        return 0
    elif number >= 1.0:
        return 1
    else:
        return number
```

```python
data['pub_rec'] = data.pub_rec.apply(pub_rec)
data['mort_acc'] = data.mort_acc.apply(mort_acc)
data['pub_rec_bankruptcies'] = data.pub_rec_bankruptcies.apply(pub_rec_bankruptcies)
```

### Target Mapping

Source: cell 75.

Use only as context for analytics. This note is not using ML training.

```python
data['loan_status'] = data.loan_status.map({'Fully Paid':1, 'Charged Off':0})
```

### Missing Values

Sources: cells 98, 100, 102, 103, 104, 106, 107.

HE idea: encrypted missing-value counts; encrypted grouped sums/counts to support
private imputation statistics.

```python
data.mort_acc.value_counts()
```

```python
data.corr()['mort_acc'].drop('mort_acc').sort_values().hvplot.barh()
```

```python
total_acc_avg = data.groupby(by='total_acc').mean().mort_acc
```

```python
def fill_mort_acc(total_acc, mort_acc):
    if np.isnan(mort_acc):
        return total_acc_avg[total_acc].round()
    else:
        return mort_acc
```

```python
data['mort_acc'] = data.apply(lambda x: fill_mort_acc(x['total_acc'], x['mort_acc']), axis=1)
```

```python
for column in data.columns:
    if data[column].isna().sum() != 0:
        missing = data[column].isna().sum()
        portion = (missing / data.shape[0]) * 100
        print(f"'{column}': number of missing values '{missing}' ==> '{portion:.3f}%'")
```

```python
data.dropna(inplace=True)
```

### Term Mapping And Category Encoding

Sources: cells 112, 113, 116, 117, 120, 122, 123.

HE idea: small-domain lookup or one-hot encrypted category counts. `term` is a
good first lookup because it has only two values.

```python
data.term.unique()
```

```python
term_values = {' 36 months': 36, ' 60 months': 60}
data['term'] = data.term.map(term_values)
```

```python
data.drop('grade', axis=1, inplace=True)
```

```python
dummies = ['sub_grade', 'verification_status', 'purpose', 'initial_list_status',
           'application_type', 'home_ownership']
data = pd.get_dummies(data, columns=dummies, drop_first=True)
```

```python
data['zip_code'] = data.address.apply(lambda x: x[-5:])
```

```python
data = pd.get_dummies(data, columns=['zip_code'], drop_first=True)
```

```python
data.drop('address', axis=1, inplace=True)
```

### Date Feature Cleanup

Sources: cells 125, 127.

HE idea: encrypted year-bucket counts after local date parsing.

```python
data.drop('issue_d', axis=1, inplace=True)
```

```python
data['earliest_cr_line'] = data.earliest_cr_line.dt.year
```

### Policy Filters Used Before Training

Source: cell 138.

HE idea: these are exactly the thresholds to turn into encrypted policy-count
experiments.

```python
print(train.shape)
train = train[train['annual_inc'] <= 250000]
train = train[train['dti'] <= 50]
train = train[train['open_acc'] <= 40]
train = train[train['total_acc'] <= 80]
train = train[train['revol_util'] <= 120]
train = train[train['revol_bal'] <= 250000]
print(train.shape)
```

### Scaling Context

Source: cell 142.

HE idea: CKKS works better with scaled/normalized values. Scaling can be done
before encryption by the data owner.

```python
scaler = MinMaxScaler()
X_train = scaler.fit_transform(X_train)
X_test = scaler.transform(X_test)
```

## Home Credit Notebook Context

### Data Load

Source: `home-credit-complete-eda-feature-importance.ipynb`, cell 7.

```python
application_train = pd.read_csv('../input/application_train.csv')
POS_CASH_balance = pd.read_csv('../input/POS_CASH_balance.csv')
bureau_balance = pd.read_csv('../input/bureau_balance.csv')
previous_application = pd.read_csv('../input/previous_application.csv')
installments_payments = pd.read_csv('../input/installments_payments.csv')
credit_card_balance = pd.read_csv('../input/credit_card_balance.csv')
bureau = pd.read_csv('../input/bureau.csv')
application_test = pd.read_csv('../input/application_test.csv')
```

### Missing-Value Audit Pattern

Sources: cells 29, 31, 33, 35, 37, 39, 41.

HE idea: for each column, encrypt an `is_null` flag vector and sum it.

```python
total = application_train.isnull().sum().sort_values(ascending = False)
percent = (application_train.isnull().sum()/application_train.isnull().count()*100).sort_values(ascending = False)
missing_application_train_data  = pd.concat([total, percent], axis=1, keys=['Total', 'Percent'])
missing_application_train_data.head(20)
```

Same pattern appears for:

```text
POS_CASH_balance
bureau_balance
previous_application
installments_payments
credit_card_balance
bureau
```

### Numeric Distributions

Sources: cells 44, 46, 48.

HE idea: private histograms, sums, averages, or bounded range counts for credit,
income, and goods price.

```python
plt.figure(figsize=(12,5))
plt.title("Distribution of AMT_CREDIT")
ax = sns.distplot(application_train["AMT_CREDIT"])
```

```python
plt.figure(figsize=(12,5))
plt.title("Distribution of AMT_INCOME_TOTAL")
ax = sns.distplot(application_train["AMT_INCOME_TOTAL"].dropna())
```

```python
plt.figure(figsize=(12,5))
plt.title("Distribution of AMT_GOODS_PRICE")
ax = sns.distplot(application_train["AMT_GOODS_PRICE"].dropna())
```

### Target Counts

Source: cell 52.

HE idea: encrypted count of repayment/default flags.

```python
temp = application_train["TARGET"].value_counts()
df = pd.DataFrame({'labels': temp.index,
                   'values': temp.values
                  })
df.iplot(kind='pie',labels='labels',values='values', title='Loan Repayed or not')
```

### Category-By-Target Count Pattern

Sources: cells 80, 82, 84, 86, 88, 90, 92.

HE idea: encrypted conditional counts by category. This pattern can become
encrypted group-by if category masks and target flags are encrypted.

Example from income type:

```python
temp = application_train["NAME_INCOME_TYPE"].value_counts()
temp_y0 = []
temp_y1 = []
for val in temp.index:
    temp_y1.append(np.sum(application_train["TARGET"][application_train["NAME_INCOME_TYPE"]==val] == 1))
    temp_y0.append(np.sum(application_train["TARGET"][application_train["NAME_INCOME_TYPE"]==val] == 0))
```

Same pattern appears for:

```text
NAME_FAMILY_STATUS
OCCUPATION_TYPE
NAME_EDUCATION_TYPE
NAME_HOUSING_TYPE
ORGANIZATION_TYPE
NAME_TYPE_SUITE
```

### Correlation Heatmap

Source: cell 135.

HE note: encrypted correlation is possible but not a good first POC. It needs
sums, means, products, variance, and division. Use simpler aggregates first.

```python
data = [
    go.Heatmap(
        z= application_train.corr().values,
        x=application_train.columns.values,
        y=application_train.columns.values,
        colorscale='Viridis',
        reversescale = False,
        text = True ,
        opacity = 1.0 )
]
```

### Category Encoding And Fillna

Sources: cells 137, 138.

HE idea: categorical encoding should happen before encryption. Encrypted lookup
can be tried later for small domains.

```python
from sklearn import preprocessing
categorical_feats = [
    f for f in application_train.columns if application_train[f].dtype == 'object'
]

for col in categorical_feats:
    lb = preprocessing.LabelEncoder()
    lb.fit(list(application_train[col].values.astype('str')) + list(application_test[col].values.astype('str')))
    application_train[col] = lb.transform(list(application_train[col].values.astype('str')))
    application_test[col] = lb.transform(list(application_test[col].values.astype('str')))
```

```python
application_train.fillna(-999, inplace = True)
```

## Concrete First Files To Code Later

Suggested non-ML POC files:

```text
uc_credit_rating/he_poc/
  data_schema.md
  generate_tiny_lending_fixture.py
  plain_missing_counts.py
  plain_policy_threshold_counts.py
  plain_rule_score.py
  ckks_rule_score.cpp
  bfv_missing_counts.cpp
  results/
```

First fixture columns:

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

First rule score:

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

This is intentionally a rule score, not a trained ML model.
