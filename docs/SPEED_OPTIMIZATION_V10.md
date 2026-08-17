# Speed Optimization V10

## Baseline
V10 is based on `youtube-v3-refactored-speed-optimized-v9`.

## Changes

### 1. Unified deterministic script pre-QA
`script_quality_gate_report()` aggregates the existing anti-story, hook, source-boundary, generic-self-help and format checks into one structured report.

The semantic reviewer remains authoritative for nuanced psychological quality; this gate exists to avoid duplicated pre-QA logic and to decide whether an expensive semantic review is necessary.

### 2. Minimal repair policy
Repair prompts now require targeted edits only:
- preserve already-correct sections;
- remove/compress only affected text;
- do not regenerate the whole script for a local defect;
- return the full final artifact for compatibility.

### 3. LLM observability
Every provider call emits a compact `LLM_METRICS` log record containing:
- provider/model;
- latency;
- cache hit/miss;
- token counts when the SDK exposes usage metadata;
- retry count.

### 4. Fingerprint-safe stage versions
Review, consistency and psychology-format-check stage versions are bumped so old artifacts are not silently reused after the QA changes.

## Deliberately not changed
Deep prompt compaction is not forced in V10. The current prompt builders contain critical source/psychology context and aggressively truncating them without benchmark data would risk quality regressions. V10 therefore focuses on safe latency/cost wins first.
