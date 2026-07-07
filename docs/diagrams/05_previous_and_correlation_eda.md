# Previous Application And Correlation EDA

![Previous application and correlation EDA flow](05_previous_and_correlation_eda.svg)

```mermaid
flowchart LR
  app["application_train.csv\nTARGET lookup"]
  prev["previous_application.csv"]
  join["Client-side join by SK_ID_CURR\nfor target-conditioned previous EDA"]
  prev_masks["Previous category masks"]
  corr["Selected numeric pair vectors\nvalid mask, x, y"]
  enc["CKKS encrypt"]
  server["server_home_credit_aggregate\nmasked sums"]
  result["Encrypted aggregate tables"]
  decrypt["Client decrypt"]
  report["previous category counts\nprevious target rates\nselected correlation stats"]

  app --> join
  prev --> join --> prev_masks
  app --> corr
  prev_masks --> enc
  corr --> enc
  enc --> server --> result --> decrypt --> report
```

Important boundary:

```text
The server does not do encrypted relational joins. The client joins and masks
before encryption, then the server only computes encrypted sums.
```
