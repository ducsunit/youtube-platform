# Changelog

## V19

### Reliability

- Added failure classification for deterministic and transient errors.
- Deterministic validation/programming errors fail fast.
- Provider transient and timeout errors remain retryable.
- Malformed model JSON receives at most one fresh retry.

### Pipeline Metrics

Pipeline stages now persist:

- `attempt_count`
- `retry_count`
- `attempt_elapsed_seconds`
- `failure_categories`

### Content Analysis

- Added deterministic topic pre-ranking.
- Extended targeted content repair with `insight_density_gap`.
- Added a lightweight insight-density validation signal.
- Kept targeted repair limited to one pass.

### Prompt Contract

The V18 prompt contract remains the production source of truth for:

- Redundancy control
- Hook compression
- Information gain
- Dynamic visual budgeting

### Verification

```text
Python compilation
Source-level smoke tests: 5 passed
```
