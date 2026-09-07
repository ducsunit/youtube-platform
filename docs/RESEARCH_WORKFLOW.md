# Market research → resource-pack workflow

This feature turns a scoped market investigation into a production-ready resource-pack run. It deliberately stops before image generation, narration, Veo, subtitle generation, and video rendering.

## Operator workflow

Open **Research** in the web app, select the current channel, market country, content language, and a search keyword. Run the research. Review the provider status and the evidence-backed opportunity. Only opportunities without blocking risk flags can be approved. Approval writes an editorial brief inside that channel’s research namespace and immediately starts a production resource-pack run.

The resource pack receives the approved opportunity as a locked editorial input. It fixes the topic, audience moment, angle, promise, source directions, and market metadata. The normal pack flow then produces the source lock, psychology brief, script, thumbnail contract, image prompts, publish draft, and resource-pack manifest. The user then continues manually with images, audio, and video build.

## Provider configuration

Each run also writes a redacted JSONL audit log at `research/logs/<research-run-id>.jsonl`. The log records request receipt, provider start/completion/unavailable/error, scoring, artifact save, and approval decisions. It stores a short keyword hash rather than the raw keyword and never writes API keys. The Research page exposes this log through “View run log”; it is the first place to inspect when a provider is blocked by configuration or network access.

The status endpoint is `GET /api/research/runs/{research_run_id}/status`, and the full event stream is available at `GET /api/research/runs/{research_run_id}/log?user_id=...&channel_id=...`.


SerpAPI là transport chính cho tìm kiếm và Google Trends. Set `SERPAPI_KEY`. Code gọi SerpAPI engine `google` cho search results và `google_trends` cho trend timelines + rising queries.

**vidIQ (tùy chọn):** Chỉ dùng khi có export JSON từ vidIQ desktop. Set `VIDIQ_RESEARCH_JSON=/đường/dẫn/file.json` nếu muốn competitor title analysis. Backend **không** dùng OAuth/MCP của vidIQ. Nếu không có export, provider vidIQ trả về `unavailable` — pipeline vẫn chạy bình thường với SerpAPI + Google Trends.

`GOOGLE_TRENDS_JSON` cũng được hỗ trợ cho trend export offline/reproducible khi không có SerpAPI key.

A result may be viewed even if providers are missing. It cannot be approved unless it has no blocking risk flags: two independent successful sources, observed competitor coverage, and at least one specific demand signal from a related question or rising query.

## Artifact ownership

All research artifacts are channel-scoped:

```text
users/<user_id>/channels/<channel_id>/research/
  research-<id>.json
  research-<id>.editorial-brief.json
```

The run endpoint accepts only a `research_run_id` whose approved brief lives in the same registered channel namespace. It rejects unapproved, malformed, or cross-channel briefs.

## Deliberate boundary

The system does not state that an opportunity is a proven white space. It records the evidence collected, score inputs, coverage terms, provider availability, and risk flags. The operator remains responsible for interpreting the market evidence before approval.
