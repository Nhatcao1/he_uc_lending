# Notebook EDA Criteria Map

![Notebook EDA criteria map](02_notebook_eda_criteria.svg)

```mermaid
flowchart LR
  notebook["Notebook criteria\n4.x, 5.1-5.15, 6, 7"]
  client["Trusted client prep\nraw CSV, null policy,\none-hot, joins, scaling"]
  package["Small upload bag\none notebook criterion"]
  server["HE server\nOpenFHE C++ kernels"]
  result["Client-decrypted table\ncounts, means, rates, scores"]

  notebook --> client --> package --> server --> result

  subgraph app["Application_train criteria"]
    n51["5.1 AMT_CREDIT"]
    n52["5.2 AMT_INCOME_TOTAL"]
    n53["5.3 AMT_GOODS_PRICE"]
    n54["5.4 Suite type"]
    n55["5.5 Target balance"]
    n56["5.6 Loan type"]
    n57["5.7 Own car / realty"]
    n58["5.8-5.13 Other categories"]
    n514["5.14 Category by target"]
  end

  subgraph prev["Previous_application criteria"]
    n515["5.15.1-5.15.16\nprevious categorical counts"]
  end

  subgraph advanced["Advanced notebook sections"]
    n6["6 Pearson correlation support"]
    n7["7 Linear score demo\nRandomForest replacement"]
  end
```

Implemented web jobs:

```text
39 visible jobs:
1 missing-data job
3 numeric distribution jobs
9 application category-count jobs
1 target-balance job
7 target-conditioned category jobs
16 previous_application category jobs
1 correlation-support job
1 linear-score demo
```
