# Speed Optimization V9

## Included
- Persistent content-addressed LLM cache for deterministic/repeatable calls.
- Explicit cache schema version so prompt/provider policy changes can invalidate old entries.
- Atomic cache writes to avoid partial JSON files when runs overlap.
- Cache hit/miss statistics exported through the resource-pack QA artifact.
- Duplicate executor import removed from the consolidated post-script pipeline.

## Deliberately deferred
Deep prompt compaction is deferred until latency/token traces are benchmarked; this avoids changing prompt semantics without evidence.
