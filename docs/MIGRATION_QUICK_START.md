# Scoped migration quick start

This guide moves new work from the legacy global namespace to the user/channel
namespace without requiring a rewrite of existing runs.

## 1. Start the API and web app

From the repository root:

```bash
./start-all.sh
```

The API uses the repository root by default. Set `YT_API_BACKEND_ROOT` when the
backend data must live at another mounted root. For YouTube data jobs, set
`YT_DATA_PULL_DIR` to the directory containing the external `youtube_pull.py`.

## 2. Register the channel

Register each local channel once. `youtube_channel_id` is the real YouTube channel
ID; `channel_id` is a stable, local slug.

```bash
curl -X POST http://127.0.0.1:8787/api/channels \
  -H 'Content-Type: application/json' \
  -d '{
    "user_id": "dev-user",
    "channel_id": "main",
    "youtube_channel_id": "UCxxxxxxxxxxxxxxxxxxxxxx",
    "title": "Main channel",
    "flow_profile": "resource_pack"
  }'
```

List the channels for that user:

```bash
curl 'http://127.0.0.1:8787/api/channels?user_id=dev-user'
```

Registration creates the database mapping in `runtime/platform.sqlite3`; it does
not create an OAuth token or copy legacy files.

## 3. Connect OAuth for that channel

Use the registered scope in the request body:

```bash
curl -X POST http://127.0.0.1:8787/api/data/connect \
  -H 'Content-Type: application/json' \
  -d '{
    "user_id": "dev-user",
    "channel_id": "main",
    "youtube_channel_id": "UCxxxxxxxxxxxxxxxxxxxxxx"
  }'
```

The connect job stores the token at:

```text
users/dev-user/channels/main/runtime/oauth/token.json
```

The external puller still owns OAuth client configuration and must request both
`https://www.googleapis.com/auth/youtube.force-ssl` and
`https://www.googleapis.com/auth/yt-analytics.readonly`. Keep client secrets and
tokens out of version control.

## 4. Pull data into the scoped namespace

For example, pull a date range:

```bash
curl -X POST http://127.0.0.1:8787/api/data/pull \
  -H 'Content-Type: application/json' \
  -d '{
    "user_id": "dev-user",
    "channel_id": "main",
    "youtube_channel_id": "UCxxxxxxxxxxxxxxxxxxxxxx",
    "mode": "range",
    "start_date": "2026-08-01",
    "end_date": "2026-08-31"
  }'
```

The default output is `users/dev-user/channels/main/data/youtube_data.json`.
Relative custom output names remain inside that channel's `data/` directory.

## 5. Start and monitor a scoped run

Production runs must select a dataset, or explicitly use
`channel_data_mode: "none"` with a manual topic. The server chooses the output
path; if `output_dir` is supplied, it must exactly match that path.

```bash
curl -X POST http://127.0.0.1:8787/api/runs \
  -H 'Content-Type: application/json' \
  -d '{
    "user_id": "dev-user",
    "channel_id": "main",
    "youtube_channel_id": "UCxxxxxxxxxxxxxxxxxxxxxx",
    "mode": "production",
    "channel_data_mode": "snapshot",
    "input_file": "users/dev-user/channels/main/data/youtube_data.json",
    "run_id": "august-001"
  }'

curl 'http://127.0.0.1:8787/api/runs/august-001/status?user_id=dev-user&channel_id=main'
```

Artifacts and resumable state are written to:

```text
users/dev-user/channels/main/runs/august-001/
```

Pipeline and data jobs are detached subprocesses. Each scope has its own logs and
pid files and allows one active job at a time; different channel scopes may run in
parallel. After an API restart, live pid files are rediscovered as orphaned jobs.
Pass the same `user_id` and `channel_id` to status, logs, events, resume, and cancel
requests so a run cannot be selected from the wrong namespace.

## Legacy compatibility and migration rules

- Existing global datasets remain under `data/channels/`; existing runs remain
  under `runs/`. They continue to work when scope is omitted.
- An unscoped request uses the legacy global namespace. Supplying only
  `user_id` or only `channel_id` is invalid for scoped operations.
- Legacy OAuth remains `<puller>/token.json`; channel OAuth uses the scoped path
  above. Tokens are not migrated automatically.
- To adopt an existing dataset, copy or regenerate it into the registered
  channel's `data/` directory, then pass that scoped path as `input_file`. Do not
  point a scoped run at an arbitrary path.
- To index old and new portable run files after a migration, call:

  ```bash
  curl -X POST http://127.0.0.1:8787/api/platform/reindex
  ```

  Reindexing rebuilds metadata only. It does not establish ownership or convert an
  unscoped legacy run into a channel-owned run.

## API authentication and production limitations

Local development remains unauthenticated by default. For a deployment, enable
an explicit token-to-user mapping; never expose the API with a token that has no
principal mapping:

```bash
export YT_API_ENV=production
export YT_API_TOKENS='replace-with-a-long-random-token=alice,another-long-token=bob'
export YT_API_CORS_ORIGINS='https://studio.example'
```

Alternatively use `YT_API_AUTH_TOKEN` together with `YT_API_AUTH_USER`. Clients
send `Authorization: Bearer <token>`. The server derives `user_id` from the
mapping and rejects a different client-supplied user (`403`); it also requires a
`user_id` plus `channel_id` scope for config, runs, data, build, SRT, image, and
Veo operations. Channel ownership is then checked against the registry before
scoped data, filesystem, or job access. Health is public. The unscoped legacy
platform reindex route is disabled in production.

A reverse proxy may be used instead with `YT_API_TRUSTED_USER_HEADER`, but only
if that proxy strips/replaces the header and is the sole network path to the API.
Query-token authentication (`YT_API_ALLOW_QUERY_TOKEN=true`) is disabled by
default and should only be enabled for HTTPS SSE clients, since URLs can be
logged. This is a lightweight bearer boundary, not an identity provider: token
rotation, revocation, TLS, rate limiting, CSRF policy, audit logging, and proxy
hardening remain deployment responsibilities. Do not use the trusted-header
mode or query tokens on an internet-facing endpoint.

In development mode, `user_id` is client-supplied and some routes default it to
`dev-user`; it is only a namespace label until production authentication is
enabled.
