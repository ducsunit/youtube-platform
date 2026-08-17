# Backend latency optimization

## Baseline
`youtube-v3 2`

## Changes
- Gemini reasoning tier: high for psychology/review/audit, medium for research/selection.
- Conditional semantic review: `fast` skips reviewer when deterministic pre-QA is clean; `balanced` keeps the reviewer; `max` always keeps full QA.
- Post-script network calls (Vietnamese translation, thumbnail, publish metadata) run concurrently; existing artifact names are preserved.
- Sections remain deterministic and are emitted in the same consolidated stage.
- RunContext caches repeated artifact reads within a stage execution.
- CLI/API/frontend expose `quality=fast|balanced|max`.

## Compatibility
Existing artifact types remain unchanged; the optimization is an execution-layer change.


## v8 speed safeguards
- Cleaned duplicate runtime definitions introduced during earlier optimization passes.
- Quality-aware Gemini thinking tier: `max` keeps high reasoning for all quality-critical calls; `balanced` keeps high only for psychology/review/audit; `fast` uses medium by default.
- Fast/balanced skip semantic review when deterministic pre-QA is clean; the review stage now evaluates deterministic flags only once.
- Consistency repair rounds are now `1` for fast/balanced and `2` for max, reducing unnecessary full-script repair calls.
- These changes keep artifact names and stage dependencies compatible with the current baseline.


## Persistent LLM cache (V8+)
Deterministic research/brief/contract/planning/review/audit/localization/publish calls may reuse
responses by a content-addressed key. Creative stages such as writing, repair, thumbnail and image
prompt generation are deliberately not cached so retries remain genuinely generative. Configure with
`LLM_CACHE_ENABLED` and `LLM_CACHE_DIR`. The cache is local-only and ignored by git.
