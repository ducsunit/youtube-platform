# YouTube AI Content Platform

An AI-powered platform for researching, generating, validating, and refining YouTube content through a stateful multi-stage pipeline.

The system integrates multiple AI providers and the YouTube Data API to automate parts of the content production workflow while maintaining validation, retry handling, execution metrics, and pipeline state.

## Overview

Creating long-form YouTube content involves multiple repetitive stages:

- Researching existing channels and content
- Selecting relevant topics
- Generating scripts
- Reviewing and validating generated content
- Detecting quality issues
- Refining content through targeted repair
- Handling unreliable AI provider responses
- Tracking pipeline execution and failures

This project focuses on building a reliable backend pipeline for these workflows rather than treating LLM calls as isolated API requests.

## Key Features

- YouTube channel and content analysis
- Deterministic topic pre-ranking
- AI-assisted script generation
- Multi-stage content validation
- Targeted content repair
- Retry and failure classification
- Pipeline execution metrics
- LLM request/response logging
- Deterministic LLM caching
- Multiple AI provider integration
- YouTube Data API integration
- Google OAuth 2.0 integration
- FastAPI backend
- Optional subtitle processing with Whisper-based tooling

## Architecture

```text
                         ┌──────────────────────┐
                         │      Web Client      │
                         │      apps/web        │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │      FastAPI         │
                         │      Backend         │
                         └──────────┬───────────┘
                                    │
                                    ▼
                    ┌──────────────────────────────┐
                    │      Pipeline Engine         │
                    ├──────────────────────────────┤
                    │  Resource Analysis           │
                    │  Topic Selection             │
                    │  Content Generation           │
                    │  Content Validation           │
                    │  Targeted Repair              │
                    │  Execution Metrics            │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────┼───────────────┐
                    ▼              ▼               ▼
              ┌──────────┐  ┌──────────┐   ┌─────────────┐
              │  Gemini  │  │ OpenAI   │   │  DeepSeek   │
              └──────────┘  └──────────┘   └─────────────┘

                                   │
                                   ▼
                         ┌──────────────────────┐
                         │   YouTube Data API   │
                         │   Google OAuth 2.0   │
                         └──────────────────────┘
```

## Content Pipeline

The main workflow is organized as a multi-stage pipeline:

```text
YouTube / Channel Data
          │
          ▼
   Resource Analysis
          │
          ▼
   Topic Pre-ranking
          │
          ▼
    Topic Selection
          │
          ▼
   Script Generation
          │
          ▼
   Content Validation
          │
       ┌──┴──┐
       │     │
     Valid  Invalid
       │     │
       │     ▼
       │  Targeted Repair
       │     │
       │     ▼
       └─────┘
          │
          ▼
     Final Content
          │
          ▼
    Pipeline Metrics
```

## Reliability

One of the main engineering goals of the project is to avoid treating every pipeline failure as a retryable error.

The pipeline classifies failures into different categories.

### Deterministic failures

Examples:

- Validation errors
- Programming errors
- Invalid contracts
- Unexpected data structures

These failures fail fast instead of consuming all retry attempts.

### Transient failures

Examples:

- Provider timeouts
- Temporary API failures
- Recoverable external service errors

These failures remain retryable.

### Malformed model output

Malformed structured model output receives a limited fresh retry rather than repeatedly executing the same failed operation.

This prevents deterministic problems from unnecessarily consuming retry budgets while still allowing temporary provider failures to recover.

## Pipeline Metrics

Pipeline stages record execution information such as:

```text
attempt_count
retry_count
attempt_elapsed_seconds
failure_categories
```

This makes individual stage failures easier to diagnose and provides visibility into pipeline execution behavior.

## Content Validation and Repair

Generated scripts are validated before being considered complete.

The validation layer checks content quality signals and can identify issues such as insufficient insight density.

Instead of regenerating the entire script, the pipeline can perform a targeted repair pass for specific detected issues.

This keeps the repair process focused and limits unnecessary model calls.

## AI Providers

The project supports multiple AI providers:

- Google Gemini
- OpenAI
- DeepSeek

Provider-specific configuration is handled through environment variables, allowing models to be changed without modifying the core pipeline implementation.

## External Integrations

### YouTube Data API

Used for retrieving and working with YouTube-related channel/content data.

### Google OAuth 2.0

Used for authenticated Google/YouTube interactions.

### AI APIs

The system integrates multiple LLM providers for different analysis, generation, review, and auditing tasks.

## Tech Stack

| Category                   | Technology                      |
| -------------------------- | ------------------------------- |
| Language                   | Python                          |
| Backend                    | FastAPI                         |
| AI                         | Google Gemini, OpenAI, DeepSeek |
| Video Platform             | YouTube Data API                |
| Authentication             | Google OAuth 2.0                |
| Runtime                    | Uvicorn                         |
| Configuration              | python-dotenv                   |
| Testing                    | Python smoke tests / validation |
| Optional Speech Processing | faster-whisper                  |
| Package Management         | pyproject.toml                  |

## Project Structure

```text
.
├── apps/
│   └── web/                 # Web interface
│
├── config/
│   └── channels/            # Channel configuration
│
├── data/                    # Application data
├── docs/                    # Documentation
├── runtime/                 # Runtime logs and pipeline artifacts
├── scripts/                 # Utility scripts
├── skills/                  # Project-specific skills
├── tests/                   # Tests and smoke tests
│
├── youtube_pipeline/        # Core pipeline implementation
│
├── .env.example             # Environment configuration template
├── pyproject.toml            # Python project configuration
├── start-all.sh             # Start frontend and backend
├── start-backend.sh         # Start backend
└── start-frontend.sh        # Start frontend
```

## Configuration

Copy the environment template:

```bash
cp .env.example .env
```

Configure the required API credentials and runtime settings in `.env`.

Example:

```env
GEMINI_API_KEY=your-key
OPENAI_API_KEY=your-key
DEEPSEEK_API_KEY=your-key
```

Do not commit real API keys or OAuth credentials.

## Running Locally

### Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
```

```bash
pip install -e .
```

For optional subtitle processing:

```bash
pip install -e ".[srt]"
```

### Start backend

```bash
./start-backend.sh
```

### Start frontend

```bash
./start-frontend.sh
```

Or start both:

```bash
./start-all.sh
```

## Engineering Decisions

### Why classify retryable failures?

Not every failure is temporary.

Retrying a programming or validation error repeatedly wastes API calls and increases pipeline latency. The pipeline therefore separates deterministic failures from transient provider failures.

### Why use targeted repair?

When generated content contains a localized quality issue, regenerating the entire script can be unnecessarily expensive.

Targeted repair allows the pipeline to focus on the detected problem while preserving already-valid content.

### Why support multiple AI providers?

Different providers can have different strengths, costs, latency characteristics, and model capabilities.

Keeping provider configuration separate from pipeline logic makes it easier to experiment with different models without rewriting the pipeline architecture.

## Verification

The project includes source-level verification and smoke tests.

Current verification includes:

```text
Python compilation
Source-level smoke tests
```

Latest verified result:

```text
5 tests passed
```

## Project Status

This project is an actively developed personal engineering project focused on AI-assisted content production, backend pipeline design, external API integration, and reliability engineering.

## License

For educational and portfolio purposes.
