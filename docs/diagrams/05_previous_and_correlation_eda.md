# Previous Application And Correlation EDA

![Previous application and correlation EDA flow](05_previous_and_correlation_eda.svg)

```mermaid
flowchart LR
  app["application_train.csv\nTARGET lookup"]
  prev["previous_application.csv"]
  prep["Client prep\none-hot each previous column\nselect correlation pairs"]
  prevjobs["5.15.1-5.15.16\n16 previous_application jobs"]
  corr["6 Pearson correlation support\nselected pairwise sums"]
  server["server_home_credit_aggregate\nencrypted sums"]
  report["Client-decrypted tables"]

  app --> prep
  prev --> prep
  prep --> prevjobs --> server
  prep --> corr --> server
  server --> report
```

Previous-application jobs:

```text
prev_contract_type
prev_weekday_process_start
prev_cash_loan_purpose
prev_contract_status
prev_payment_type
prev_reject_reason
prev_suite_type
prev_client_type
prev_goods_category
prev_portfolio
prev_product_type
prev_channel_type
prev_seller_industry
prev_yield_group
prev_product_combination
prev_insured_on_approval
```

Important boundary:

```text
The server does not do encrypted relational joins. The client joins and masks
before encryption when target-conditioned previous EDA is needed.
```
