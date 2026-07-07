# Application EDA Criteria

![Application EDA criteria flow](04_application_eda_criteria.svg)

```mermaid
flowchart LR
  raw["application_train.csv"]
  prep["Client prep\nclean numeric values\none-hot categories\nTARGET mask"]
  numeric["5.1 AMT_CREDIT\n5.2 AMT_INCOME_TOTAL\n5.3 AMT_GOODS_PRICE"]
  category["5.4, 5.6-5.13\n9 category-count jobs"]
  target["5.5 Target balance"]
  bytarget["5.14.1-5.14.7\ncategory by target"]
  server["OpenFHE server\nEvalSum / mask sums"]
  report["Client-decrypted tables\nmeans, counts, rates"]

  raw --> prep
  prep --> numeric --> server
  prep --> category --> server
  prep --> target --> server
  prep --> bytarget --> server
  server --> report
```

Representative HE operations:

```text
numeric_sum = EvalSum(numeric_vector)
count = sum(category_mask)
target_default_count = sum(target_default_mask)
default_count_by_category = sum(category_mask * TARGET)
```
