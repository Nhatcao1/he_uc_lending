# Client Code

Client code runs where the raw Home Credit data and secret key live.

Tracked here:

- Home Credit data preparation scripts
- CKKS keygen/encrypt/decrypt wrappers
- optional plaintext linear-model export helper

Ignored by git:

- raw data under `data/`
- generated prepared CSVs under `encrypted_payloads/`
- secret keys under `keys/`
- returned encrypted results under `server_returns/`

## Home Credit Notebook EDA Payload

The active target is the Home Credit Default Risk Kaggle data. At minimum the
client needs:

```text
data/home_credit/application_train.csv
```

For previous-application notebook criteria, also pass:

```text
data/home_credit/previous_application.csv
```

The client prepares all raw-data-dependent context before encryption:

- missing-value masks
- target default/repaid masks
- application category one-hot masks
- numeric summary vectors
- histogram/bin masks
- previous_application category masks
- client-side joined previous_application/TARGET masks
- tokenized previous_application/application_train join masks for HMAC and PSI-ready timing tests
- selected correlation pair helper vectors
- optional linear-score demo vectors

These outputs are local artifacts and are ignored by git.

## Implemented Tools

```text
home_credit/prepare_home_credit_basic_eda.py
home_credit/train_home_credit_linear_model.py
home_credit/package_home_credit_upload_bag.py
home_credit/download_job_bundle.py
home_credit/result_client_dashboard.py
ckks_tools/encrypt_home_credit_payload.cpp
ckks_tools/decrypt_ckks_results.cpp
```

Full client/server command flow:

```text
docs/HOME_CREDIT_IMPLEMENTED_CLIENT_SERVER_FLOW.md
```

## Small Criterion Upload Bags

After preparing and encrypting the payload, create one zip per notebook EDA
criterion for the web submit page. The packager reads the encrypted output
folder and copies only the ciphertexts/manifests needed by that criterion.

```bash
python3 code/client/home_credit/package_home_credit_upload_bag.py \
  --encrypted-dir encrypted_payloads/home_credit_basic \
  --workload app_target_by_income_type \
  --output-dir client_runs/home_credit_basic/server_uploads \
  --client-key-dir keys/home_credit_basic
```

Upload this zip at:

```text
/jobs/new
```

Useful criterion names follow the notebook:

```text
missing_data
app_dist_amt_credit
app_dist_amt_income_total
app_dist_amt_goods_price
app_suite_type
app_target_balance
app_loan_type
app_own_car_realty
app_income_type
app_family_status
app_occupation_type
app_education_type
app_housing_type
app_organization_type
app_target_by_income_type
app_target_by_family_status
app_target_by_occupation_type
app_target_by_education_type
app_target_by_housing_type
app_target_by_organization_type
app_target_by_suite_type
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
app_selected_correlation_stats
join_hmac_prev_contract_status
join_psi_prev_contract_status
linear_score_demo
all
```

The join workloads compare matching approaches over the same encrypted
`previous_application.NAME_CONTRACT_STATUS` masks:

```text
join_hmac_prev_contract_status  # matched by local HMAC-SHA256 SK_ID_CURR tokens
join_psi_prev_contract_status   # same HE job, matched-token set can come from PSI output
```

The zip contains server-safe encrypted artifacts and manifests only. It blocks
raw Home Credit CSV names and secret/private key-looking paths. Use `all` only
when you deliberately want the bigger bundle for every criterion.

Legacy names such as `numeric_summary`, `category_eda`, `bucket_eda`,
`domain_ratio_eda`, and `linear_score` are accepted as aliases, but new bags are
named with the notebook criterion.

Clean local layout after packaging:

```text
client_runs/home_credit_basic/server_uploads/*.upload.zip  # upload this
client_runs/home_credit_basic/client_private/<client_material_id>/secret_key.bin # never upload
client_runs/home_credit_basic/client_private/<client_material_id>/crypto_context.bin
```

Each upload bag records its `client_material_id`. Returned result bundles include
that id, so `download_job_bundle.py` can print a decrypt command using the
matching key material instead of a stale key from a later encryption run.

## Local Result Dashboard

Run a local client-only result dashboard:

```bash
python3 code/client/home_credit/result_client_dashboard.py \
  --server http://100.84.97.118:8080 \
  --port 8090
```

Open:

```text
http://127.0.0.1:8090
```

The page reads only the server result index and shows the newest completed job
for each EDA criterion. `View result` downloads the encrypted bundle, decrypts
it locally with the matching client key material, and renders the decrypted CSV
table in the browser. `Pull bundle` is still available when you only want the
encrypted bundle and command-line decrypt command.

Local outputs go into:

```text
client_runs/home_credit_basic/server_returns/<job_id>/
```
