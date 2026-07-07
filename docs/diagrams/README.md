# Home Credit HE Diagrams

Diagram set for the implemented Home Credit HE prototype. Each diagram maps to
the notebook-facing EDA criteria now exposed by the client packager and async
server UI.

- a Markdown page with a Mermaid diagram
- an SVG picture file that can be opened directly

## Diagram Index

| Area | Markdown | Picture |
| --- | --- | --- |
| Overall client/server flow | [01 Overall Flow](01_overall_home_credit_he_flow.md) | [SVG](01_overall_home_credit_he_flow.svg) |
| Notebook EDA criteria catalog | [02 Criteria Map](02_notebook_eda_criteria.md) | [SVG](02_notebook_eda_criteria.svg) |
| Missing data and target balance | [03 Missing And Target](03_missing_and_target_counts.md) | [SVG](03_missing_and_target_counts.svg) |
| Application notebook criteria | [04 Application EDA](04_application_eda_criteria.md) | [SVG](04_application_eda_criteria.svg) |
| Previous application and correlation criteria | [05 Previous And Correlation](05_previous_and_correlation_eda.md) | [SVG](05_previous_and_correlation_eda.svg) |
| Notebook 7 linear score demo | [06 Linear Score Demo](06_linear_score_demo.md) | [SVG](06_linear_score_demo.svg) |
| Async web job architecture | [07 Async Web Job Architecture](07_async_web_job_architecture.md) | [SVG](07_async_web_job_architecture.svg) |

Core boundary:

```text
client owns raw data, secret key, final decrypted report
server owns encrypted execution only
```
