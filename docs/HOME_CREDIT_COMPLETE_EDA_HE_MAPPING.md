# Home Credit Complete EDA HE Mapping

Source notebook:

```text
home-credit-complete-eda-feature-importance.ipynb
```

Goal: map every EDA section in the notebook to a practical homomorphic
encryption approach. The server means the HE compute server. The server receives
encrypted numeric vectors, encrypted masks, public/evaluation keys, and
manifests. It does not receive raw CSV rows, strings, dates, secret keys, or
decrypted reports.

This project is an HE prototype, not a visualization product. Notebook graphs
are replaced by decrypted numeric tables for now. The HE success criterion is
that the encrypted server computed the aggregate values correctly.

## Boundary

Client does:

- read raw Home Credit CSV files
- inspect schema and choose columns
- define null, category, bucket, top-K, and join policies
- transform dates/numbers/categories into numeric vectors and 0/1 masks
- encrypt vectors and masks
- upload encrypted criterion bags
- download encrypted result bundles
- decrypt final numeric tables/rates

HE server does:

- validate uploaded encrypted artifact layout
- run encrypted sums
- run encrypted masked sums such as `sum(mask * target)` and
  `sum(mask * amount)`
- package encrypted results

HE server cannot practically do in this prototype:

- parse raw CSV
- discover column types
- detect nulls directly from raw strings
- normalize strings or dates
- choose top categories
- perform pandas joins across raw Home Credit tables
- sort, rank, top-K, or value-count raw categories by itself
- draw plots
- decrypt final numbers
- train RandomForest or run tree-based feature importance

## Prototype Output Rule

The notebook is graph-heavy, but the current output should be table-first.

| Notebook graph style | HE prototype output |
| --- | --- |
| Pie chart | Table with `label`, `count`, `percent` |
| Bar chart | Table with `group`, `label`, `count`, `percent` |
| Stacked target bar | Table with `label`, `count`, `default_count`, `repaid_count`, `default_rate` |
| Distribution plot | Table with `column`, `count`, `sum`, `mean`, and optional histogram `bin`, `bin_count`, `bin_percent` |
| Heatmap | Table with selected `feature_x`, `feature_y`, pairwise stats, and client-computed correlation |
| Feature importance plot | Non-HE table from trusted/client ML only; do not claim HE server result |

The server/client flow already built should be reused:

```text
client prepare -> client encrypt/package -> server queue/run HE -> client download -> client decrypt table
```

The web UI can show job status and result bundles. The client-side dashboard can
pull encrypted results. Final readable numbers are produced only after client
decryption.

## Implemented Criterion Names

The user-facing names now follow notebook EDA criteria. The C++ binary names are
implementation details.

| Criterion id | UI label | Server HE operation |
| --- | --- | --- |
| `home_credit_missing_data` | Missing Data Counts | `sum(is_null_mask)` |
| `home_credit_target_balance` | Target Balance | `sum(target_default)`, `sum(target_repaid)` |
| `home_credit_application_numeric_summary` | Application Numeric Summary | `EvalSum(numeric_vector)` |
| `home_credit_application_category_counts` | Application Category Counts | `sum(category_mask)` |
| `home_credit_application_default_rates` | Application Category Default Rates | `sum(mask)`, `sum(mask * TARGET)`, `sum(mask * amount)` |
| `home_credit_application_numeric_histograms` | Application Numeric Histograms | `sum(bin_mask)`, `sum(bin_mask * TARGET)` |
| `home_credit_previous_application_category_counts` | Previous Application Category Counts | `sum(previous_category_mask)` |
| `home_credit_previous_application_target_rates` | Previous Application Target-Conditioned EDA | `sum(joined_mask)`, `sum(joined_mask * TARGET)` |
| `home_credit_selected_correlation_stats` | Selected Numeric Correlation Stats | selected encrypted pairwise sums |
| `home_credit_linear_score_demo` | Linear Score Demo | optional CKKS weighted sum; not RandomForest |

Client package names:

```text
missing_data
target_balance
application_numeric_summary
application_category_counts
application_default_rates
application_numeric_histograms
previous_application_category_counts
previous_application_target_rates
selected_correlation_stats
linear_score_demo
```

Legacy package names (`numeric_summary`, `category_eda`, `bucket_eda`,
`domain_ratio_eda`, `linear_score`) are accepted as aliases only.

## Data Loading And Glimpse

Notebook cells:

```text
7, 8, 10-26
```

Original EDA:

- load `application_train`, `application_test`, `bureau`, `bureau_balance`,
  `previous_application`, `POS_CASH_balance`, `installments_payments`,
  `credit_card_balance`
- print shapes
- show `head()`
- list columns

HE mapping:

| Notebook action | Client preparation | HE server execution | HE feasibility |
| --- | --- | --- | --- |
| Load CSV files | Client loads raw CSV locally | None | Not server HE work |
| Print shapes | Client may include row counts in manifest | Optional encrypted row count if privacy requires it | Usually plaintext manifest is enough |
| Show head rows | Client only | None | Do not send raw rows |
| List columns | Client can send selected column names in manifest | Server validates expected artifact names | Column names are metadata, not HE |

Numeric output instead of graph:

```text
table_name,row_count,column_count,selected_columns
application_train,307511,122,"AMT_CREDIT;AMT_INCOME_TOTAL;TARGET"
```

Note: schema metadata may leak what analysis is being run. That is acceptable for
this prototype.

## Missing Data Checks

Notebook cells:

```text
29, 31, 33, 35, 37, 39, 41
```

Original code pattern:

```python
total = table.isnull().sum().sort_values(ascending=False)
percent = table.isnull().sum() / table.isnull().count() * 100
```

Tables:

```text
application_train
POS_CASH_balance
bureau_balance
previous_application
installments_payments
credit_card_balance
bureau
```

HE mapping:

| Result wanted | Client preparation | HE server execution | What cannot be HE-server-side |
| --- | --- | --- | --- |
| Missing count per column | For each selected column, create 0/1 `is_null_<column>` mask | `sum(is_null_<column>)` | Server cannot inspect raw nulls from encrypted CSV |
| Missing percent per column | Include plaintext row count, or encrypt all-ones row mask | Sum null mask; optionally sum row mask | Division and percent formatting happen after client decrypt |
| Top missing columns | Client can sort after decrypt | None | Sorting/ranking under HE is not practical here |

Numeric output instead of graph:

```text
table,column,total_rows,missing_count,missing_percent
application_train,EXT_SOURCE_1,307511,173378,56.38
```

Implementation decision:

- Use current server/client flow with one encrypted mask per selected column.
- Start with selected important columns, not every column in every table.
- Client still records null policy in the manifest because server cannot infer
  it from ciphertext.

## Numeric Distributions

Notebook cells:

```text
44, 46, 48
```

Original plots:

```text
Distribution of AMT_CREDIT
Distribution of AMT_INCOME_TOTAL
Distribution of AMT_GOODS_PRICE
```

HE mapping:

| Notebook result | Client preparation | HE server execution | Client final report |
| --- | --- | --- | --- |
| Mean/sum support | Clean numeric column; encrypt packed values | Sum encrypted vector slots | Decrypt sum; divide by row count |
| Histogram plot | Choose bins client-side; create one 0/1 mask per bin | Sum each bin mask | Decrypt count table |
| Outlier-aware distribution | Client chooses clipping/winsorization/bins | Sum masks or sums | Decrypt count/sum table |

Numeric output instead of graph:

```text
column,total_rows,sum,mean
AMT_CREDIT,1000,599026500.0,599026.5

column,bin,count,percent
AMT_CREDIT,0_100000,42,4.2
AMT_CREDIT,100000_300000,181,18.1
```

What cannot be HE-server-side:

- automatic bin discovery
- KDE/distplot curve fitting
- percentile-based binning without heavy comparison circuits
- plotting

Current coverage:

- `home_credit_application_numeric_summary` supports encrypted sums for selected
  numeric columns.
- `home_credit_application_numeric_histograms` uses encrypted client-created bin
  masks for AMT, age, `EXT_SOURCE_*`, and ratio buckets.

## Simple Categorical Value Counts

Notebook cells:

```text
50, 56, 59, 61, 64, 67, 70, 73, 76
```

Original EDA:

| Section | Column |
| --- | --- |
| 5.4 Who accompanied client | `NAME_TYPE_SUITE` |
| 5.6 Types of loan | `NAME_CONTRACT_TYPE` |
| 5.7 Purpose/ownership proxy | `FLAG_OWN_CAR`, `FLAG_OWN_REALTY` |
| 5.8 Income sources | `NAME_INCOME_TYPE` |
| 5.9 Family status | `NAME_FAMILY_STATUS` |
| 5.10 Occupation | `OCCUPATION_TYPE` |
| 5.11 Education | `NAME_EDUCATION_TYPE` |
| 5.12 Housing type | `NAME_HOUSING_TYPE` |
| 5.13 Organization type | `ORGANIZATION_TYPE` |

HE mapping:

| Result wanted | Client preparation | HE server execution | Client final report |
| --- | --- | --- | --- |
| Count per category | Normalize string values; apply missing bucket; apply top-K/other policy; create one-hot masks | `sum(category_mask)` | Decrypt counts and percentages |
| Binary flag counts | Convert Y/N flags to 0/1 masks | Sum each mask | Decrypt counts and percentages |

Numeric output instead of graph:

```text
column,label,count,percent
NAME_INCOME_TYPE,Working,158774,51.6
NAME_INCOME_TYPE,Commercial associate,71617,23.3
```

What cannot be HE-server-side:

- reading strings
- grouping raw categorical values
- selecting top-K categories
- merging rare categories into `OTHER`
- formatting pie/bar charts

Recommended category policy:

- keep all values for low-cardinality columns:
  `NAME_TYPE_SUITE`, `NAME_CONTRACT_TYPE`, `FLAG_OWN_CAR`,
  `FLAG_OWN_REALTY`, `NAME_INCOME_TYPE`, `NAME_FAMILY_STATUS`,
  `NAME_EDUCATION_TYPE`, `NAME_HOUSING_TYPE`
- use top-K plus `__OTHER__` for high-cardinality columns:
  `OCCUPATION_TYPE`, `ORGANIZATION_TYPE`

Current coverage:

- `home_credit_application_category_counts` follows this pattern for selected
  application columns.
- `home_credit_application_default_rates` adds target-conditioned and amount-sum
  operations over the same encrypted masks.

## Target Balance

Notebook cells:

```text
52, 53
```

Original EDA:

```python
application_train["TARGET"].value_counts()
```

HE mapping:

| Result wanted | Client preparation | HE server execution | Client final report |
| --- | --- | --- | --- |
| Default count | Convert `TARGET` to encrypted 0/1 default mask | `sum(target_mask)` | Decrypt default count |
| Non-default count | Include row count or encrypted all-ones mask | `row_count - default_count` after decrypt, or encrypted sum row mask | Compute ratio locally |

Numeric output instead of graph:

```text
target_label,count,percent
repaid,282686,91.93
default,24825,8.07
```

What cannot be HE-server-side:

- interpret what `TARGET` means
- decide whether missing target rows exist
- draw imbalance chart

Recommended implementation:

- Include target default count as a standard aggregate in every
  target-conditioned criterion.

## Category By Target EDA

Notebook cells:

```text
80, 82, 84, 86, 88, 90, 92
```

Original pattern:

```python
for val in application_train[column].value_counts().index:
    default_count = sum(TARGET[column == val] == 1)
    repaid_count = sum(TARGET[column == val] == 0)
```

Columns:

```text
NAME_INCOME_TYPE
NAME_FAMILY_STATUS
OCCUPATION_TYPE
NAME_EDUCATION_TYPE
NAME_HOUSING_TYPE
ORGANIZATION_TYPE
NAME_TYPE_SUITE
```

HE mapping:

| Result wanted | Client preparation | HE server execution | Client final report |
| --- | --- | --- | --- |
| Category count | One-hot category mask | `sum(mask)` | Decrypt count |
| Default count per category | Category mask and target mask | `sum(mask * target)` | Decrypt default count |
| Repaid count per category | Category count and default count | None extra, or `sum(mask * (1-target))` | `repaid = count - default_count` |
| Default rate | Counts above | None | `default_count / count` after decrypt |
| Amount average by category | Category mask and encrypted amount vectors | `sum(mask * AMT_CREDIT)` etc. | `amount_sum / count` after decrypt |

Numeric output instead of graph:

```text
column,label,count,default_count,repaid_count,default_rate,amt_credit_sum,amt_credit_mean
NAME_INCOME_TYPE,Working,158774,15224,143550,0.0959,95000000000,598333.12
```

What cannot be HE-server-side:

- discover category list
- map raw strings to masks
- sort categories by risk
- calculate final plaintext percentages unless client decrypts

This is the strongest HE fit in the notebook.

## Previous Application Categorical Exploration

Notebook cells:

```text
95, 98, 101, 104, 107, 110, 112, 115, 118, 120, 122, 124, 127, 129, 131, 133
```

Original EDA columns:

| Section | `previous_application` column |
| --- | --- |
| Contract product type | `NAME_CONTRACT_TYPE` |
| Weekday applied | `WEEKDAY_APPR_PROCESS_START` |
| Cash loan purpose | `NAME_CASH_LOAN_PURPOSE` |
| Contract approved/refused | `NAME_CONTRACT_STATUS` |
| Payment method | `NAME_PAYMENT_TYPE` |
| Reject reason | `CODE_REJECT_REASON` |
| Accompanying person | `NAME_TYPE_SUITE` |
| Old/new client | `NAME_CLIENT_TYPE` |
| Goods category | `NAME_GOODS_CATEGORY` |
| Portfolio | `NAME_PORTFOLIO` |
| Product type | `NAME_PRODUCT_TYPE` |
| Channel type | `CHANNEL_TYPE` |
| Seller industry | `NAME_SELLER_INDUSTRY` |
| Yield group | `NAME_YIELD_GROUP` |
| Product combination | `PRODUCT_COMBINATION` |
| Requested insurance | `NFLAG_INSURED_ON_APPROVAL` |

HE mapping:

| Result wanted | Client preparation | HE server execution | Client final report |
| --- | --- | --- | --- |
| Distribution per previous-application category | Normalize category; top-K/other for high-cardinality columns; create one-hot masks over previous application rows | `sum(mask)` | Decrypt counts and percentages |
| Per-current-client historical count | Client joins/aggregates by `SK_ID_CURR` before encryption | Sum encrypted pre-aggregated features, or later score them | Decrypt/report locally |
| Previous status vs current target | Client joins `previous_application` to `application_train` by `SK_ID_CURR`, creates masks at desired grain | `sum(mask)`, `sum(mask * target)` | Decrypt default rates |

Numeric output instead of graph:

```text
table,column,label,count,percent
previous_application,NAME_CONTRACT_STATUS,Approved,1036781,62.1
previous_application,NAME_CONTRACT_STATUS,Refused,290678,17.4

joined_feature,label,current_app_count,current_default_count,current_default_rate
prev_contract_status,Refused,12033,1460,0.1213
```

What cannot be HE-server-side:

- raw table join by `SK_ID_CURR`
- per-client grouping over raw relational tables
- top-K category discovery
- string category processing

Recommended implementation:

- V1: treat previous application as a separate table and only do encrypted
  category counts.
- V2: client pre-aggregates previous-application features per `SK_ID_CURR`,
  joins locally to current application, then encrypts joined masks/features.
- Avoid server-side encrypted joins for this prototype.

## Pearson Correlation Heatmap

Notebook cell:

```text
135
```

Original EDA:

```python
application_train.corr()
```

HE mapping:

| Correlation piece | Client preparation | HE server execution | Practicality |
| --- | --- | --- | --- |
| Sum `x` and `y` | Clean numeric vectors | Encrypted sums | Practical |
| Sum `x*y` | Encrypt numeric pairs | Encrypted multiplication and sum | Possible but expensive |
| Variance/stddev | Need sums of squares | Encrypted multiplication and sums | Possible but heavier |
| Final correlation | Needs division/sqrt | Client after decrypt | Client-side final math |
| Full heatmap across many columns | Many pairwise products | Many encrypted multiplications | Not a good first target |

Numeric output instead of graph:

```text
feature_x,feature_y,n,sum_x,sum_y,sum_xy,sum_x2,sum_y2,correlation
AMT_CREDIT,AMT_INCOME_TOTAL,1000,599026500,171300000,123456789,456789000,789123000,0.34
```

What cannot be HE-server-side in this prototype:

- automatically select numeric columns from raw dataframe
- render heatmap
- efficiently compute all-pairs correlation for many columns

Recommendation:

- Defer full correlation heatmap.
- If needed, implement a small selected-pair correlation report for a few
  columns such as `AMT_CREDIT`, `AMT_INCOME_TOTAL`, `AMT_ANNUITY`,
  `EXT_SOURCE_2`, `EXT_SOURCE_3`.

## Label Encoding And Fillna

Notebook cells:

```text
137, 138
```

Original code:

```python
LabelEncoder()
application_train.fillna(-999, inplace=True)
```

HE mapping:

| Notebook action | Client preparation | HE server execution | HE note |
| --- | --- | --- | --- |
| Label encode categorical columns | Prefer one-hot masks for group EDA; label IDs only for ML/inference features | None | Server cannot safely interpret raw category IDs |
| Fill missing numeric with `-999` | Use explicit missing masks/buckets, or impute locally with documented policy | None | `-999` can distort encrypted sums if not tracked |
| Fill missing categorical | Use `__MISSING__` category | Sum missing bucket masks | Practical |

Numeric output instead of graph:

```text
column,policy,missing_bucket,imputation_value,affected_rows
EXT_SOURCE_1,missing_bucket,__MISSING__,,173378
AMT_ANNUITY,client_impute,,median,12
```

Recommendation:

- Do not use raw `LabelEncoder` output for categorical EDA.
- Use one-hot masks for categories and explicit missing buckets.
- Use model-specific numeric imputation only for ML/scoring workflows.

## RandomForest Feature Importance

Notebook cells:

```text
139, 140
```

Original EDA:

```python
RandomForestClassifier(...)
rf.fit(...)
rf.feature_importances_
```

HE mapping:

| Action | Client preparation | HE server execution | Practicality |
| --- | --- | --- | --- |
| Train RandomForest | Client only, plaintext or trusted training environment | None | Not practical under current HE path |
| Compute feature importance | Client/trusted analytics only | None | Not practical under HE server |
| Run tree inference under HE | Would need comparison/branching circuits | Not implemented | Poor first target |
| Run linear model inference | Scale numeric features and encrypt vectors | `sum(feature * plaintext_weight) + bias` | Practical; already demoed |

Numeric output instead of graph:

```text
feature,importance
EXT_SOURCE_2,0.108
EXT_SOURCE_3,0.095
```

This feature-importance table is not an HE server result unless we replace
RandomForest with a deliberately simple encrypted scoring experiment.

Recommendation:

- Treat RandomForest feature importance as non-HE exploratory modeling.
- If we implement it, implement it as a client/trusted baseline that exports a
  plain `feature,importance` table for comparison with HE aggregate reports.
- If we need encrypted inference, keep linear/logistic scoring under CKKS.
- Do not claim RandomForest training or feature importance is server-side HE.

## Implementation Order By Notebook Section

The dynamic server/client flow is reused for each row:

```text
client package criterion -> server job queue -> client result dashboard/download -> client decrypt table
```

| Priority | Notebook section | HE criterion | Numeric output table | Use current flow? |
| --- | --- | --- | --- | --- |
| 1 | 5.5 Target balance | `target_balance` | `target_label,count,percent` | Yes |
| 2 | 5.1-5.3 Numeric distributions | `application_numeric_summary` | `column,total_rows,sum,mean` | Yes |
| 3 | 5.4-5.13 Application category counts | `application_category_counts` | `column,label,count,percent` | Yes |
| 4 | 5.14 Category by target | `application_default_rates` | `column,label,count,default_count,default_rate` | Yes |
| 5 | 5.1-5.3 Histograms | `application_numeric_histograms` | `column,bin,count,percent` | Yes |
| 6 | 5.15 Previous application counts | `previous_application_category_counts` | `table,column,label,count,percent` | Yes, if `previous_application.csv` is provided |
| 7 | 5.15 Previous application vs target | `previous_application_target_rates` | `joined_feature,label,count,default_count,default_rate` | Yes, after client-side join |
| 8 | 6 Correlation heatmap | `selected_correlation_stats` | `feature_x,feature_y,n,sum_x,sum_y,sum_xy,...` | Yes, selected pairs only |
| 9 | 7 RandomForest importance | Non-HE modeling | `feature,importance` | No HE server; client/trusted only |

## Brief Per Notebook Output

| Notebook section | What we show instead of graph | HE calculation on server | Client preparation |
| --- | --- | --- | --- |
| Missing data | Missing count/percent table | Sum encrypted null masks | Create null masks per selected column |
| AMT distributions | Sum/mean table; optional bin count table | Sum numeric vectors; sum bin masks | Clean values; choose bins |
| Accompanied by suite | Category count/percent table | Sum category masks | One-hot `NAME_TYPE_SUITE` |
| Loan type | Category count/percent table | Sum category masks | One-hot `NAME_CONTRACT_TYPE` |
| Own car/realty | Flag count/percent table | Sum binary masks | Convert Y/N flags |
| Income source | Category count and default-rate table | Sum masks; sum mask*target | One-hot `NAME_INCOME_TYPE`; target mask |
| Family status | Category count and default-rate table | Sum masks; sum mask*target | One-hot `NAME_FAMILY_STATUS`; target mask |
| Occupation | Top-K category count/default-rate table | Sum masks; sum mask*target | Top-K + `__OTHER__` masks |
| Education | Category count/default-rate table | Sum masks; sum mask*target | One-hot `NAME_EDUCATION_TYPE`; target mask |
| Housing type | Category count/default-rate table | Sum masks; sum mask*target | One-hot `NAME_HOUSING_TYPE`; target mask |
| Organization type | Top-K category count/default-rate table | Sum masks; sum mask*target | Top-K + `__OTHER__` masks |
| Target balance | Repaid/default count table | Sum target mask | Encode `TARGET` |
| Previous application categories | Previous category count/percent tables | Sum category masks | One-hot previous table columns |
| Previous vs current target | Joined default-rate tables | Sum masks; sum mask*target | Client joins by `SK_ID_CURR` first |
| Correlation | Selected pairwise stats table | Sum x/y/products for selected pairs | Select/clean numeric pairs |
| Feature importance | Plain feature importance table | None | Client/trusted ML only |

## Naming Recommendation

Avoid vague names such as only `bucket_eda` or `category_eda` in user-facing
text. Keep C++ binary names only as implementation details.
