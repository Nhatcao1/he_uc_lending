# Home Credit Core HE EDA Progress

Purpose: track the core HE work for Home Credit EDA from the important feature
notebook. Web/UI is frozen for now; the next work is measurement and improving
the HE pipeline itself.

Source notebook focus:

```text
notebooks/home-credit-complete-eda-feature-importance.ipynb
```

Related notebook context for later feature engineering:

```text
notebooks/introduction-to-manual-feature-engineering.ipynb
notebooks/introduction-to-manual-feature-engineering-p2.ipynb
```

Detailed implementation contract:

```text
docs/HOME_CREDIT_HE_EDA_IMPLEMENTATION_TRACKER.md
```

## Current Direction

We are treating the current work as **benchmark / notebook replication first**.
The immediate goal is not to perfect the client/server data-product boundary;
it is to reproduce each notebook EDA calculation under HE and compare it with
the equivalent Python calculation.

Benchmark flow:

```text
raw Home Credit table in trusted benchmark environment
-> select the notebook EDA case and the needed subset/vector
-> trusted preparation creates numeric vectors and/or 0/1 masks
-> CKKS encrypts packed vectors
-> HE server computes sums/masked sums on ciphertext
-> trusted side decrypts aggregate values and computes final rates/percentages
-> benchmark report compares Python vs HE, with timing and artifact size
```

Scheme rule:

```text
Home Credit EDA scheme: CKKS
All new Home Credit EDA benchmark, report, and implementation work follows CKKS.
Any non-CKKS code path is legacy/toolchain smoke only and must not drive the
Home Credit EDA plan.
```

This means we can test one group at a time, or pass separate prepared vectors
such as `Family`, `Unaccompanied`, `Working`, and `Pensioner`, instead of
requiring the HE server to discover those groups from raw strings. Product
questions such as source metadata, key management, PSI, and category discovery
are outside the active CKKS EDA implementation path.

Do not spend new effort on web UX until this tracker says otherwise.

## Compute-Focused Filter

For the benchmark phase, ignore notebook cells that are only display wrappers
around a single `sns.*` or `plt.*` call. Keep only EDA that exposes a reusable
calculation kernel we can run on ciphertext and compare with Python.

| Priority | Keep? | Notebook pattern | HE benchmark meaning |
| --- | --- | --- | --- |
| High | Yes | conditional default rate by group | `sum(group_mask)`, `sum(group_mask * TARGET)` |
| High | Yes | numeric aggregate / distribution table | encrypted count/sum/bin count/mean support |
| High | Yes | correlation / relationship statistics | `sum(x)`, `sum(y)`, `sum(x*y)`, `sum(x^2)`, `sum(y^2)` |
| High | Yes | previous-table grouped summaries | encrypted counts/sums over larger related tables |
| Medium | Sometimes | plain `value_counts()` | useful as a warm-up or artifact-size benchmark, but not enough alone |
| Low | Usually no | `sns.countplot`, `sns.barplot`, `plt.hist` only | plotting belongs after decrypt; not an HE kernel |
| Low | Usually no | missing-data display only | source must encode null policy, so benchmark value is limited |

The practical target is now:

```text
notebook calculation kernel
-> Python reference
-> encrypt only needed vector/subset
-> run equivalent HE operation
-> decrypt and compare
-> write timing/artifact report
```

## Workload Progress

| Notebook area | Current HE approach | Client/trusted preparation | HE server calculation | Status |
| --- | --- | --- | --- | --- |
| Missing-value checks | encrypted missing masks | map null/blank values to 0/1 masks | `sum(mask)` | Implemented, needs timing |
| Numeric distributions | encrypted numeric sums | clean numeric column, pack vector | `sum(x)` | Implemented, needs timing |
| Category counts | encrypted one-hot category masks | normalize category, top-K policy, one-hot masks | `sum(category_mask)` | Implemented, demo-ready |
| Target balance | encrypted target masks | encode `TARGET=1` and `TARGET=0` masks | `sum(target_mask)` | Implemented, needs timing |
| Target by category | encrypted conditional count | category masks plus `TARGET=1` mask | `sum(mask)`, `sum(mask * target)` | Implemented, demo-ready |
| Previous application EDA | encrypted previous-table masks | prepare previous_application category masks | `sum(previous_mask)` | Implemented, size/perf needs work |
| Correlation support | encrypted sufficient statistics | select numeric pairs, create pair-valid vectors, zero-fill invalid pairs | `sum(x)`, `sum(y)`, `sum(xy)`, `sum(x^2)`, `sum(y^2)` | Clean benchmark wrapper added |
| Feature importance notebook ML | HE-friendly replacement only | trusted feature prep/model export | linear weighted sum only | Partial; tree model not HE target |
| Merge-aware features | tokenized grouped aggregate | token/mask prep near data source | masked encrypted sums by token/match mask | Experimental |

## Important Feature Notebook EDA Inventory

This is the compact review of the EDA sections in
`home-credit-complete-eda-feature-importance.ipynb`.

| Notebook section | Original EDA action | HE translation | Performance priority |
| --- | --- | --- | --- |
| 4.x missing data | `isnull().sum()` across Home Credit CSVs | client creates null masks; HE computes `sum(mask)` | Medium; broad table coverage later |
| 5.1 `AMT_CREDIT` distribution | numeric distribution plot | encrypted `sum(x)` now; histogram masks later | High |
| 5.2 `AMT_INCOME_TOTAL` distribution | numeric distribution plot | encrypted `sum(x)` now; histogram masks later | High |
| 5.3 `AMT_GOODS_PRICE` distribution | numeric distribution plot | encrypted `sum(x)` now; histogram masks later | High |
| 5.4 suite/accompanied client | `NAME_TYPE_SUITE.value_counts()` | one-hot masks, `sum(mask)` | Medium |
| 5.5 target balance | `TARGET.value_counts()` | target masks, `sum(target_mask)` | High |
| 5.6 loan type | `NAME_CONTRACT_TYPE.value_counts()` | one-hot masks, `sum(mask)` | Medium |
| 5.7 own car / own realty | `FLAG_OWN_CAR`, `FLAG_OWN_REALTY` counts | one-hot masks, `sum(mask)` | Medium |
| 5.8 income type | `NAME_INCOME_TYPE.value_counts()` | one-hot masks, `sum(mask)` | High |
| 5.9 family status | `NAME_FAMILY_STATUS.value_counts()` | one-hot masks, `sum(mask)` | Medium |
| 5.10 occupation | `OCCUPATION_TYPE.value_counts()` | top-K one-hot masks, `sum(mask)` | High; high cardinality |
| 5.11 education | `NAME_EDUCATION_TYPE.value_counts()` | one-hot masks, `sum(mask)` | High; demo-ready |
| 5.12 housing type | `NAME_HOUSING_TYPE.value_counts()` | one-hot masks, `sum(mask)` | Medium |
| 5.13 organization type | `ORGANIZATION_TYPE.value_counts()` | top-K one-hot masks, `sum(mask)` | Medium; high cardinality |
| 5.14.1 target by income | category split by `TARGET` | `sum(mask)`, `sum(mask * TARGET)` | High |
| 5.14.2 target by family | category split by `TARGET` | `sum(mask)`, `sum(mask * TARGET)` | Medium |
| 5.14.3 target by occupation | category split by `TARGET` | `sum(mask)`, `sum(mask * TARGET)` | High; high cardinality |
| 5.14.4 target by education | category split by `TARGET` | `sum(mask)`, `sum(mask * TARGET)` | High; demo-ready |
| 5.14.5 target by housing | category split by `TARGET` | `sum(mask)`, `sum(mask * TARGET)` | Medium |
| 5.14.6 target by organization | category split by `TARGET` | `sum(mask)`, `sum(mask * TARGET)` | Medium; high cardinality |
| 5.14.7 target by suite | category split by `TARGET` | `sum(mask)`, `sum(mask * TARGET)` | Medium |
| 5.15.1 previous contract type | previous_application value counts | previous-table masks, `sum(mask)` | Medium; size-sensitive |
| 5.15.2 previous weekday | previous_application value counts | previous-table masks, `sum(mask)` | Low |
| 5.15.3 previous cash loan purpose | previous_application value counts | top-K previous masks, `sum(mask)` | Medium; high cardinality |
| 5.15.4 previous contract status | previous_application value counts | previous masks, `sum(mask)` | High; join/matching candidate |
| 5.15.5 previous payment type | previous_application value counts | previous masks, `sum(mask)` | Low |
| 5.15.6 previous reject reason | previous_application value counts | previous masks, `sum(mask)` | Medium |
| 5.15.7 previous suite type | previous_application value counts | previous masks, `sum(mask)` | Low |
| 5.15.8 previous client type | previous_application value counts | previous masks, `sum(mask)` | Medium |
| 5.15.9 previous goods category | previous_application value counts | top-K previous masks, `sum(mask)` | Medium; high cardinality |
| 5.15.10 previous portfolio | previous_application value counts | previous masks, `sum(mask)` | Medium |
| 5.15.11 previous product type | previous_application value counts | previous masks, `sum(mask)` | Medium |
| 5.15.12 previous channel type | previous_application value counts | previous masks, `sum(mask)` | Medium |
| 5.15.13 previous seller industry | previous_application value counts | top-K previous masks, `sum(mask)` | Low; high cardinality |
| 5.15.14 previous yield group | previous_application value counts | previous masks, `sum(mask)` | Medium |
| 5.15.15 previous product combination | previous_application value counts | top-K previous masks, `sum(mask)` | Medium; high cardinality |
| 5.15.16 previous insured on approval | previous_application value counts | previous masks, `sum(mask)` | Low |
| 6 Pearson correlation | full dataframe correlation heatmap | selected sufficient stats only: sums of `x`, `y`, `xy`, `x^2`, `y^2` | High for HE depth testing |
| 7 RandomForest feature importance | train RF and plot importances | not direct HE; use trusted training + optional linear HE scoring | Separate ML track |

Near-term benchmark order:

1. `app_target_by_education_type`
2. `app_target_by_income_type`
3. `app_target_by_occupation_type`
4. numeric amount summaries and selected histograms
5. selected correlation sufficient statistics with `home_credit_correlation_benchmark.py`
6. previous contract status, after package-size optimization

## OpenFHE API Surface

Client/trusted encryption phase:

| Step | OpenFHE API / operation | Notes |
| --- | --- | --- |
| CKKS context/key setup | `GenCryptoContext`, `KeyGen` | Current helper owns scheme setup |
| Packed plaintext | `MakeCKKSPackedPlaintext(values)` | Packs one vector chunk into CKKS slots |
| Encrypt vector chunk | `Encrypt(publicKey, plaintext)` | Produces ciphertext chunks |
| Eval keys | `EvalSumKeyGen(secretKey)`, `EvalMultKeyGen(secretKey)` | Required for server sums/masked sums |
| Serialize artifacts | `Serialize*`, `SerializeEvalSumKey`, `SerializeEvalMultKey` | Server receives context, public/eval keys, ciphertexts |

HE server calculation phase:

| EDA operation | OpenFHE API / operation | Meaning |
| --- | --- | --- |
| Count/sum | `EvalSum(ciphertext, slots)` | Sum packed vector slots |
| Conditional count | `EvalMultAndRelinearize(mask, target)`, then `EvalSum` | Count rows satisfying both masks |
| Masked numeric sum | `EvalMultAndRelinearize(mask, value)`, then `EvalSum` | Sum numeric values inside a group |
| Plaintext mask join path | `MakeCKKSPackedPlaintext(mask)`, `EvalMult(ciphertext, plaintext)`, then `EvalSum` | Used for token/PSI-style match mask |
| Result output | serialize result ciphertext + manifest | Client decrypts later |

Client/trusted result phase:

| Step | Operation | Notes |
| --- | --- | --- |
| Decrypt aggregate | `Decrypt(secretKey, ciphertext)` | Only trusted side has secret key |
| Final rate/percent | normal arithmetic | `default_rate = default_count / group_count` |

## Performance Metrics To Track

Measure with the same dataset slice and workload name each time.

| Metric | Owner | What to record |
| --- | --- | --- |
| Data prepare latency | client/trusted prep | CSV read, cleaning, mask/vector creation |
| Encoding latency | client/trusted prep | category normalization, one-hot/mask generation, numeric vector build |
| Encryption latency | client/trusted HE | CKKS context/keygen, packing, encryption, serialization |
| Ciphertext count | client/trusted HE | number of vector chunks/ciphertexts |
| Upload package size | client/trusted package | zip size and number of files |
| HE compute latency | HE server | binary runtime excluding browser/UI time where possible |
| Result bundle size | HE server | encrypted output bytes |
| Decryption latency | trusted result side | result decrypt and report formatting |

Initial observed demo point:

| Date | Workload | Rows | Input bytes | HE runtime | Result |
| --- | --- | ---:| ---:| ---:| --- |
| 2026-07-10 | `app_target_by_education_type` | 2,000 `application_train` rows | ~65 MB upload | ~4s server runtime | Count/default-rate table decrypted successfully |

Encoding/encryption timings are not yet measured cleanly; add instrumentation
before making performance claims.

## Next Engineering Steps

1. Run the local benchmark harness for a small all-in-one correctness/timing
   path:

   ```bash
   python3 code/benchmarks/home_credit_core_eda_benchmark.py \
     --input data/home_credit/application_train.csv \
     --workload app_target_by_education_type \
     --row-limit 2000 \
     --build-dir build \
     --slots 4096
   ```

   Use `--row-limit 0` for all `application_train` rows after the small run
   passes.

2. Add timing logs around client preparation:
   - CSV scan
   - category discovery
   - mask/vector build
   - manifest writing
3. Use the C++ timing lines now emitted by encryption/decrypt/server binaries:
   - CKKS context/key generation
   - eval-key generation
   - vector packing
   - encryption per vector/chunk
   - serialization
4. Run the client preparation/encryption tools on the stronger server machine
   for benchmark-only runs.
5. Benchmark small, medium, and larger slices:
   - 2k application rows
   - 10k application rows
   - previous_application slices separately
6. Prioritize EDA workloads that are both business-readable and HE-friendly:
   - education/default rate
   - income/default rate
   - occupation/default rate
   - numeric amount summaries
   - selected correlation sufficient statistics
7. Do not optimize web until core timings are understood.

Benchmark harness output:

```text
benchmark_runs/home_credit_core_eda/<run-name>/benchmark_summary.json
benchmark_runs/home_credit_core_eda/<run-name>/plaintext_reference.csv
benchmark_runs/home_credit_core_eda/<run-name>/decrypted.csv
```

Correctness rule:

```text
Python plaintext reference count/default_count
must match decrypted HE count/default_count within CKKS tolerance.
```

## Notes And Constraints

- HE server does not perform SQL-style `GROUP BY` on raw categories. Client
  prepares group masks; HE server sums encrypted masks.
- HE server does not parse raw CSV, normalize strings, choose top-K categories,
  or handle null logic from raw values.
- CKKS is the only active Home Credit EDA scheme. Counts are approximate under
  CKKS but acceptable for prototype reporting when checked against tolerance.
- Non-CKKS paths are paused unless explicitly reopened as separate experiments.
- Previous application EDA is the first place package size becomes painful.
  Treat it as a separate performance track from application_train-only EDA.
- The current web flow can still submit and view jobs, but it is not the focus
  for the next phase.
