# Notebook EDA Criteria Map

![Notebook EDA criteria map](02_notebook_eda_criteria.svg)

```mermaid
flowchart LR
  notebook["complete-eda-important-feature notebook"]
  client["Client preparation\nraw CSV, null policy, one-hot, bins, joins"]
  sums["CKKS numeric sums\napplication_numeric_summary"]
  masks["CKKS mask sums\nmissing, target, category, histogram"]
  joined["Client-side joined masks\nprevious_application target rates"]
  pairs["Selected pair products\ncorrelation support"]
  score["Optional linear score demo\nnot RandomForest"]
  server["Async HE server\nC++ OpenFHE jobs"]
  result["Client decrypts\nnumeric EDA tables"]

  notebook --> client
  client --> sums
  client --> masks
  client --> joined
  client --> pairs
  client --> score
  sums --> server
  masks --> server
  joined --> server
  pairs --> server
  score --> server
  server --> result
```

Criteria exposed by the web UI:

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
