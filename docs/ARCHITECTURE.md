# Architecture

## Monorepo boundary

The repository is one application. YouTube data acquisition is part of
`youtube_pipeline.analysis`; it is not a second project or a subprocess dependency.
The API may spawn the external data puller as a job, but the pipeline, API, and
web app remain one repository boundary.

```text
youtube-v4/
├── youtube_pipeline/
│   ├── analysis/             # YouTube Data/Analytics/Reporting collector
│   ├── api/                  # FastAPI routes + isolated job runners
│   ├── core/                 # resumable stage engine, state, artifacts
│   ├── domain/               # domain models and consistency rules
│   ├── infrastructure/      # logging and model tracing
│   ├── resource_pack/       # research → psychology → script → packaging
│   └── video/                # timeline/build/Veo
├── apps/web/                 # React/Vite dashboard
├── data/channels/            # legacy/global channel input/output JSON
├── config/channels/          # legacy/global channel configuration templates
├── users/                    # canonical user/channel-scoped data and runs
├── runs/                     # legacy/global resumable runs
├── runtime/                  # platform index and legacy/global job logs
├── assets/                   # legacy/global production assets
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

## Identity and scope

A channel-scoped request is identified by the pair `(user_id, channel_id)`.
`youtube_channel_id` is the corresponding YouTube identity and is checked against
the channel registry; it is not a replacement for the local `channel_id`.
`ChannelContext` carries all three identifiers plus the channel root into pipeline
code. Scope IDs are validated before they are used in filesystem paths.

The registry is SQLite at `runtime/platform.sqlite3`. Its `channels` table maps
`(user_id, channel_id)` to one `youtube_channel_id`, title, profile, and active
state. A YouTube channel may not be registered twice for the same user under two
local channel IDs. Deactivation hides it from normal selection without deleting
its files.

## Filesystem namespaces

The canonical channel root is:

```text
users/<user_id>/channels/<channel_id>/
├── data/                       # snapshots, youtube_data.json, pull output
├── content/                   # topic history and content state
├── config/                    # channel configuration
├── assets/                    # channel assets
├── runs/<run_id>/              # run_state.json and stage artifacts
└── runtime/
    ├── logs/                  # channel job logs and pid files
    └── oauth/token.json       # this channel's OAuth token
```

The platform database is shared at `runtime/platform.sqlite3`; it is an index and
telemetry store, while `run_state.json` and artifact files remain the portable
source of truth. Legacy unscoped data remains under `data/channels/`, `runs/`,
`assets/`, and `runtime/logs/`.

## Resource-pack pipeline

The production resource flow is canonical under `youtube_pipeline.resource_pack`.
The old top-level `resource_*` modules are compatibility shims only.

The current stage order is defined by `resource_pack.pipeline.resource_pack_stages()`
and remains resumable through `runs/<run-id>/run_state.json` (or the corresponding
channel-scoped run path). A run ID is unique within its namespace; the same run ID
may safely exist for different users/channels.

## API scope and job isolation

- `user_id` and `channel_id` must be supplied together. A request that supplies
  only one is rejected; channel-scoped run/data operations also require the
  registered `youtube_channel_id` where applicable.
- Channel list/detail/mutation endpoints take `user_id` as a query parameter or
  body field. Run and job status/log/event/cancel endpoints take the scope in the
  query or body as documented by their route. Omitting both selects the legacy
  global namespace, not a user's channel.
- New pipeline runs write only to the canonical namespace selected by the server;
  a caller-provided `output_dir` must resolve to that exact run directory. Data
  output files are constrained to the selected channel's data directory.
- Each pipeline and data job is a detached subprocess (`start_new_session`) with
  its own log and pid file. Busy state is keyed by `(user_id, channel_id)`, so
  independent channels can run concurrently while a namespace still permits only
  one active job. After an API restart, live pid files are rediscovered and exposed
  as orphaned jobs; they can be cancelled through the same scoped path.

## OAuth boundary

OAuth credentials belong to the external puller selected by `YT_DATA_PULL_DIR`.
For a registered channel, the API sets `TOKEN_FILE` to:

```text
users/<user_id>/channels/<channel_id>/runtime/oauth/token.json
```

An unscoped legacy connect continues to use `<puller>/token.json`. The puller must
have both scopes `youtube.force-ssl` and `yt-analytics.readonly`. OAuth client
configuration stays with the puller; the API only selects the token location and
runs the connect/pull/reporting subprocess.

## Legacy compatibility and migration

Legacy callers that omit scope retain the original global paths and process guard.
Existing legacy runs and datasets are not moved automatically. The platform index
can be rebuilt from portable files with `POST /api/platform/reindex`; this does not
turn an unscoped legacy run into an authenticated channel-owned run. Use the
channel registration and scoped output paths for all new work. See
`docs/MIGRATION_QUICK_START.md` for the migration sequence and request examples.

## Security limitation in development mode

This development API accepts `user_id` from the client (and defaults it to
`dev-user` on several channel-management/run routes). That value is a namespace
selector, not proof of identity. There is no production authentication or
authorization boundary implemented here; callers must not expose this server as a
multi-tenant service. A production deployment must derive the user identity from a
trusted authenticated session/token and enforce ownership before honoring any
user/channel scope. The current registry and path validation reduce accidental
cross-scope mistakes but do not solve that security requirement.

Secrets (`.env`, OAuth client files, and `token.json`) are local-only and must never
be committed.

## Runtime data summary

- Canonical channel data: `users/<user_id>/channels/<channel_id>/data/`
- Canonical pipeline artifacts: `users/<user_id>/channels/<channel_id>/runs/<run_id>/`
- Shared registry/index: `runtime/platform.sqlite3`
- Legacy data/artifacts: `data/channels/`, `runs/`, `assets/`, `runtime/logs/`
