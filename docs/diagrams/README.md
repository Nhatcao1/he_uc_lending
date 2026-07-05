# Home Credit HE Diagrams

Diagram set for the implemented Home Credit HE prototype. Each use case has:

- a Markdown page with a Mermaid diagram
- an SVG picture file that can be opened directly

## Diagram Index

| Use case | Markdown | Picture |
| --- | --- | --- |
| Overall client/server flow | [01 Overall Flow](01_overall_home_credit_he_flow.md) | [SVG](01_overall_home_credit_he_flow.svg) |
| Numeric summary | [02 Numeric Summary](02_numeric_summary.md) | [SVG](02_numeric_summary.svg) |
| Category default-rate EDA | [03 Category EDA](03_category_default_rate_eda.md) | [SVG](03_category_default_rate_eda.svg) |
| Age / EXT_SOURCE bucket EDA | [04 Bucket EDA](04_bucket_eda.md) | [SVG](04_bucket_eda.svg) |
| Domain ratio EDA | [05 Domain Ratio EDA](05_domain_ratio_eda.md) | [SVG](05_domain_ratio_eda.svg) |
| Linear ML score | [06 Linear Score](06_linear_score.md) | [SVG](06_linear_score.svg) |
| Async web job architecture | [07 Async Web Job Architecture](07_async_web_job_architecture.md) | [SVG](07_async_web_job_architecture.svg) |

Core boundary:

```text
client owns raw data, secret key, final decrypted report
server owns encrypted execution only
```
