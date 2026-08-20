# YouTube Pipeline V19 Update

Apply these files directly on top of the current V18 baseline.

## Updated files

- `youtube_pipeline/core/engine.py`
  - Retry classification: deterministic validation/programming errors fail fast.
  - Provider transient/timeout errors remain retryable.
  - Malformed model JSON gets at most one fresh retry.
  - Stage metrics now persist `attempt_count`, `retry_count`, `attempt_elapsed_seconds`, and `failure_categories`.

- `youtube_pipeline/resource_analysis.py`
  - Keeps deterministic topic pre-ranking so the expensive selector sees only the strongest candidate pool.

- `youtube_pipeline/resource_pipeline.py`
  - Extends the targeted content controller with `insight_density_gap` repair.
  - Keeps repair to one targeted pass.

- `youtube_pipeline/resource_validation.py`
  - Adds a lightweight `insight_density_gap` signal when a long script has a very low insight-marker density.
  - Tightens the first-insight soft trigger from 18% to 15% of script length.

- `youtube_pipeline/resource_prompts.py`
  - V18 prompt contract remains the production source of truth for redundancy, hook compression, information gain, and dynamic visual budgeting.

## Important behavior change

A deterministic stage bug such as `ValueError`/`KeyError`/`TypeError` will no longer burn all three stage retries. This is intentional: the pipeline should spend retries on transient provider failures, not on a bad contract or validation rule.

## Verification

`py_compile` + source-level smoke tests: **5 passed**.
