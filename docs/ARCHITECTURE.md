# Architecture

## High-Level Architecture

```text
┌─────────────────────┐
│      Web Client     │
│      apps/web       │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│       FastAPI       │
│       Backend       │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────────────────┐
│        Pipeline Engine          │
│                                 │
│  ┌───────────────────────────┐  │
│  │ Resource Analysis         │  │
│  └─────────────┬─────────────┘  │
│                ▼                │
│  ┌───────────────────────────┐  │
│  │ Topic Selection           │  │
│  └─────────────┬─────────────┘  │
│                ▼                │
│  ┌───────────────────────────┐  │
│  │ Content Generation        │  │
│  └─────────────┬─────────────┘  │
│                ▼                │
│  ┌───────────────────────────┐  │
│  │ Content Validation        │  │
│  └─────────────┬─────────────┘  │
│                ▼                │
│  ┌───────────────────────────┐  │
│  │ Targeted Repair           │  │
│  └─────────────┬─────────────┘  │
│                ▼                │
│  ┌───────────────────────────┐  │
│  │ Metrics / Logging         │  │
│  └───────────────────────────┘  │
└───────────────┬─────────────────┘
                │
       ┌────────┼─────────┐
       ▼        ▼         ▼
   Gemini    OpenAI    DeepSeek

                │
                ▼
       ┌──────────────────┐
       │  YouTube Data API │
       │  Google OAuth 2.0 │
       └──────────────────┘
```

## Pipeline Design

The pipeline is organized as sequential processing stages.

Each stage can:

1. Receive structured input from the previous stage.
2. Execute its processing logic.
3. Validate its output.
4. Retry when the failure is transient.
5. Fail fast when the error is deterministic.
6. Record execution metrics.

## Reliability Model

```text
Stage
 │
 ▼
Execute
 │
 ├── Success ───────────────► Next Stage
 │
 ├── Deterministic Error ──► Fail Fast
 │
 ├── Transient Error ──────► Retry
 │
 └── Invalid Model Output ─► Limited Fresh Retry
```

## Content Repair

Content validation can identify localized quality issues.

Instead of regenerating the complete output:

```text
Generated Script
       │
       ▼
    Validate
       │
       ├── Valid ──────► Final
       │
       └── Invalid
              │
              ▼
       Identify Issue
              │
              ▼
       Targeted Repair
              │
              ▼
            Final
```

This approach reduces unnecessary regeneration and keeps the repair process focused on the detected issue.
