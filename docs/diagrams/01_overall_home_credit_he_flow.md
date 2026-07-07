# Overall Home Credit HE Flow

![Overall Home Credit HE flow](01_overall_home_credit_he_flow.svg)

```mermaid
flowchart LR
  raw["Raw application_train.csv"]
  prev["Optional previous_application.csv"]
  prep["Client prep\nnull policy, one-hot, bins, joins"]
  plain["Prepared vectors\nlocal plaintext only"]
  enc["CKKS encrypt\nkeep secret_key.bin local"]
  upload["Criterion upload bag\ncontext, eval keys, manifests, ciphertexts"]
  web["Async server\nFastAPI + RQ"]
  jobs["OpenFHE C++ criteria\nsums, masked sums, score demo"]
  returns["Encrypted result bundle"]
  dec["Client decrypt"]
  report["Readable EDA tables"]

  raw --> prep
  prev --> prep
  prep --> plain --> enc --> upload --> web --> jobs --> returns --> dec --> report
```

Purpose:

```text
Run Home Credit notebook EDA criteria on encrypted client data without sending
raw applicant rows, plaintext prepared vectors, or secret keys to the server.
```
