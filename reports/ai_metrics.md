# AI Evaluation Metrics

Generated: 2026-10-24T14:19:39.562687+00:00
Task-generation evaluation mode: deterministic mocked provider

## Secret scanner

Fixture: `repositories/tests/fixtures/secrets_dataset.json` (49 labeled samples)

| Metric | Value |
|---|---:|
| True positives | 24 |
| False positives | 0 |
| True negatives | 25 |
| False negatives | 0 |
| Precision | 1.000 |
| Recall | 1.000 |
| F1 | 1.000 |

## Task generation

| Metric | Value |
|---|---:|
| AI jobs recorded | 0 |
| Proposed tasks | 0 |
| Accepted tasks | 0 |
| Acceptance rate | 0.000 |
| Job latency p50 | n/a |
| Job latency p95 | n/a |
| AI usage latency p50 | 0 ms |
| AI usage latency p95 | 0 ms |
| Provider sample | Mocked provider returned 1 valid task suggestion(s). |

The default run uses a fixed mocked provider response. Use `--live` to contact the configured provider.
