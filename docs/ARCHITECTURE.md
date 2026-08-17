# Architecture

## Monorepo boundary

The repository is one application. YouTube data acquisition is part of
`youtube_pipeline.analysis`; it is not a second project or a subprocess dependency.

```text
youtube-v3/
├── youtube_pipeline/
│   ├── analysis/             # YouTube Data/Analytics/Reporting collector
│   ├── api/                  # FastAPI routes + job runners
│   ├── core/                 # resumable stage engine, state, artifacts
│   ├── domain/               # domain models and consistency rules
│   ├── infrastructure/      # logging and model tracing
│   ├── resource_pack/       # research → psychology → script → packaging
│   └── video/                # timeline/build/Veo
├── apps/web/                 # React/Vite dashboard
├── data/channels/            # channel input/output JSON
├── config/channels/          # channel configuration templates
├── runs/                     # resumable per-video artifacts
├── runtime/logs/             # process logs and job pid files
├── assets/                   # production assets
├── docs/                     # documentation and editorial specs
├── skills/                   # AI production skills
└── tests/
```

## Dependency direction

```text
apps/web
    │ HTTP
    ▼
youtube_pipeline.api
    │
    ├── analysis
    ├── resource_pack
    ├── video
    └── core/domain/infrastructure
```

`youtube_pipeline.api` owns process/job orchestration. The analysis collector is
a normal package module and can also be executed through:

```bash
python -m youtube_pipeline.analysis.youtube_pull
```

`YT_DATA_PULL_DIR` remains an explicit compatibility override for users who still
maintain an external collector.

## Resource-pack pipeline

The production resource flow is canonical under `youtube_pipeline.resource_pack`.
The old top-level `resource_*` modules are compatibility shims only.

The current stage order is defined by `resource_pack.pipeline.resource_pack_stages()`
and remains resumable through `runs/<run-id>/run_state.json`.

## Runtime data

- Channel JSON: `data/channels/`
- Pipeline artifacts: `runs/<run-id>/`
- API job logs: `runtime/logs/`
- Thumbnail assets: `assets/thumbnails/`

Secrets (`.env`, OAuth client files and `token.json`) are local-only and must never
be committed.
