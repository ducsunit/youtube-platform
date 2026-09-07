"""Channel-scoped market research API: keyword -> evidence -> opportunity."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..channel_context import ChannelContext
from ..research import build_research, editorial_brief, save_research
from . import paths
from .routes import _require_registered_channel


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _research_log_path(user_id: str, channel_id: str, research_run_id: str) -> Path:
    if not re.fullmatch(paths.RUN_ID_PATTERN, research_run_id):
        raise ValueError("research_run_id không hợp lệ")
    return paths.channel_root(user_id, channel_id) / "research" / "logs" / (research_run_id + ".jsonl")


def _write_log_event(path: Path, event: str, fields: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    secret_keys = {"api_key", "key", "token", "password", "authorization"}
    safe = {key: ("[REDACTED]" if key.casefold() in secret_keys else value) for key, value in fields.items()}
    safe["timestamp"] = _utc_now()
    safe["event"] = event
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(safe, ensure_ascii=False) + "\n")


def _keyword_hash(keyword: str) -> str:
    return hashlib.sha256(keyword.encode("utf-8")).hexdigest()[:12]

router = APIRouter(prefix="/api/research")


def _channel(user_id: str, channel_id: str) -> tuple[dict, ChannelContext]:
    row = _require_registered_channel(user_id, channel_id)
    context = ChannelContext(
        user_id=user_id,
        channel_id=channel_id,
        youtube_channel_id=row["youtube_channel_id"],
        root_dir=paths.channel_root(user_id, channel_id),
        flow_profile=row.get("flow_profile") or "resource_pack",
    )
    return row, context


def _research_path(user_id: str, channel_id: str, research_run_id: str) -> Path:
    return paths.channel_root(user_id, channel_id) / "research" / (research_run_id + ".json")


@router.post("/runs", status_code=202)
def start_research(body: dict) -> dict:
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Payload research phải là object")
    user_id = str(body.get("user_id") or "dev-user")
    channel_id = str(body.get("channel_id") or "")
    keyword = str(body.get("keyword") or "")
    country = str(body.get("country") or "").upper()
    log_path: Path | None = None
    try:
        _row, channel = _channel(user_id, channel_id)
        research_run_id = str(body.get("research_run_id") or f"research-{uuid.uuid4().hex[:12]}")
        log_path = _research_log_path(user_id, channel_id, research_run_id)
        _write_log_event(log_path, "request_received", {
            "research_run_id": research_run_id, "user_id": user_id, "channel_id": channel_id,
            "country": country, "language": str(body.get("language") or "").lower(),
            "keyword_hash": _keyword_hash(keyword),
        })
        research = build_research(
            user_id=user_id,
            channel=channel,
            keyword=keyword,
            country=country,
            language=str(body.get("language") or ""),
            research_run_id=research_run_id,
            log_event=lambda event, fields: _write_log_event(log_path, event, {
                **fields, "research_run_id": research_run_id, "keyword_hash": _keyword_hash(keyword),
            }),
        )
        path = save_research(channel.root_dir, research)
        _write_log_event(log_path, "artifact_saved", {"research_run_id": research_run_id, "path": str(path.relative_to(channel.root_dir))})
    except (ValueError, OSError) as exc:
        if log_path:
            _write_log_event(log_path, "research_failed", {"error_category": "request_or_validation_error", "error": str(exc)})
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        **research.to_dict(),
        "status": "complete",
        "path": str(path.relative_to(channel.root_dir)),
        "log_path": str(log_path.relative_to(channel.root_dir)) if log_path else None,
    }


@router.get("/runs/{research_run_id}/log")
def get_research_log(research_run_id: str, user_id: str = Query(...), channel_id: str = Query(...)) -> dict:
    _channel(user_id, channel_id)
    path = _research_log_path(user_id, channel_id, research_run_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Không tìm thấy research log")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        events = [json.loads(line) for line in lines if line.strip()]
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="Research log không hợp lệ") from exc
    return {"research_run_id": research_run_id, "path": str(path.relative_to(paths.channel_root(user_id, channel_id))), "events": events}


@router.get("/runs/{research_run_id}/status")
def get_research_status(research_run_id: str, user_id: str = Query(...), channel_id: str = Query(...)) -> dict:
    _channel(user_id, channel_id)
    artifact = _research_path(user_id, channel_id, research_run_id)
    log_path = _research_log_path(user_id, channel_id, research_run_id)
    if not artifact.is_file() and not log_path.is_file():
        raise HTTPException(status_code=404, detail="Không tìm thấy research run")
    events = []
    if log_path.is_file():
        events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    terminal = next((event for event in reversed(events) if event.get("event") in {"research_completed", "research_failed"}), None)
    return {"research_run_id": research_run_id, "status": "complete" if artifact.is_file() else "running", "terminal_event": terminal, "event_count": len(events), "log_path": str(log_path.relative_to(paths.channel_root(user_id, channel_id)))}


@router.post("/suggest")
def suggest_keywords(body: dict) -> dict:
    """Gợi ý từ khóa cụ thể từ từ khóa rộng (related questions + rising queries)."""
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Payload phải là object")
    keyword = str(body.get("keyword") or "").strip()
    country = str(body.get("country") or "VN").upper()
    language = str(body.get("language") or "vi").lower()
    if not keyword:
        raise HTTPException(status_code=400, detail="keyword không được rỗng")

    from ..research import SerpApiProvider
    provider = SerpApiProvider()
    evidence = provider.collect(keyword, country, language)

    suggestions: list[dict[str, Any]] = []
    if evidence.status == "ok":
        for row in evidence.records:
            if row.get("type") == "related_question" and row.get("question"):
                suggestions.append({
                    "keyword": row["question"],
                    "source": "related_question",
                    "snippet": row.get("snippet", "")
                })
            elif row.get("type") == "rising_query" and row.get("query"):
                suggestions.append({
                    "keyword": row["query"],
                    "source": "rising_query",
                    "value": row.get("value")
                })
            elif row.get("title"):
                suggestions.append({
                    "keyword": row["title"],
                    "source": "organic_title",
                    "snippet": row.get("snippet", "")
                })

    # Dedupe theo keyword
    seen = set()
    unique = []
    for s in suggestions:
        k = s["keyword"].lower().strip()
        if k and k not in seen:
            seen.add(k)
            unique.append(s)

    return {
        "seed_keyword": keyword,
        "country": country,
        "language": language,
        "suggestions": unique[:30],
        "total_found": len(unique)
    }


@router.post("/atlas")
def run_tube_atlas(body: dict) -> dict:
    """Tube Atlas: từ khóa rộng -> web research -> sub-niches cụ thể -> opportunities."""
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Payload phải là object")
    user_id = str(body.get("user_id") or "dev-user")
    channel_id = str(body.get("channel_id") or "")
    seed_keyword = str(body.get("keyword") or "").strip()
    country = str(body.get("country") or "VN").upper()
    language = str(body.get("language") or "vi").lower()

    if not seed_keyword:
        raise HTTPException(status_code=400, detail="keyword không được rỗng")

    _row, channel = _channel(user_id, channel_id)

    from ..tube_atlas import build_atlas_report, atlas_report_to_market_research, save_research
    report = build_atlas_report(seed_keyword, country, language, channel)
    research = atlas_report_to_market_research(report, channel, user_id)

    path = save_research(channel.root_dir, research)

    return {
        "research_run_id": research.research_run_id,
        "seed_keyword": seed_keyword,
        "country": country,
        "language": language,
        "sub_niches_count": len(report.sub_niches),
        "opportunities_count": len(research.opportunities),
        "top_sub_niches": [
            {
                "keyword": s.keyword,
                "source": s.source,
                "demand_score": s.demand_score,
                "competitor_count": s.competitor_count,
                "angle": s.angle,
                "unserved_question": s.unserved_question,
                "promise": s.promise,
            }
            for s in report.sub_niches[:10]
        ],
        "competitor_titles": report.competitor_titles[:10],
        "rising_queries": report.rising_queries[:10],
        "related_questions": report.related_questions[:10],
        "research_path": str(path.relative_to(channel.root_dir)),
    }


@router.get("/runs/{research_run_id}")
def get_research(
    research_run_id: str,
    user_id: str = Query(...),
    channel_id: str = Query(...),
) -> dict:
    _channel(user_id, channel_id)
    path = _research_path(user_id, channel_id, research_run_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Không tìm thấy research run")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="Research artifact không hợp lệ") from exc


@router.post("/runs/{research_run_id}/approve")
def approve_research(
    research_run_id: str,
    body: dict,
    user_id: str = Query(...),
    channel_id: str = Query(...),
) -> dict:
    _row, channel = _channel(user_id, channel_id)
    try:
        log_path = _research_log_path(user_id, channel_id, research_run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    path = _research_path(user_id, channel_id, research_run_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Không tìm thấy research run")
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
        options = report.get("opportunities") or []
        opportunity_id = str((body or {}).get("opportunity_id") or "")
        opportunity = next((item for item in options if item.get("opportunity_id") == opportunity_id), None)
        if opportunity is None:
            raise ValueError("opportunity_id không thuộc research run")
        if opportunity.get("risk_flags"):
            _write_log_event(log_path, "approval_blocked", {
                "research_run_id": research_run_id,
                "opportunity_id": opportunity_id,
                "blocking_risk_flags": opportunity["risk_flags"],
            })
            raise ValueError(
                "Không thể approve opportunity khi evidence chưa đủ: "
                + ", ".join(str(flag) for flag in opportunity["risk_flags"])
            )
        from ..research import MarketResearch, Evidence
        evidence = {key: Evidence(**value) for key, value in (report.get("evidence") or {}).items()}
        research = MarketResearch(
            research_run_id=report["research_run_id"], user_id=report["user_id"], channel_id=report["channel_id"],
            youtube_channel_id=report["youtube_channel_id"], keyword=report["keyword"], country=report["country"],
            language=report["language"], created_at=report["created_at"], evidence=evidence,
            normalized=report.get("normalized", {}), opportunities=options,
            selected_opportunity_id=opportunity_id,
        )
        brief = editorial_brief(research, opportunity, channel)
        brief_path = path.parent / f"{research_run_id}.editorial-brief.json"
        _write_log_event(log_path, "approval_requested", {"research_run_id": research_run_id, "opportunity_id": opportunity_id})
        brief_path.write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
        report["selected_opportunity_id"] = opportunity_id
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        _write_log_event(log_path, "approval_completed", {"research_run_id": research_run_id, "opportunity_id": opportunity_id, "brief_path": str(brief_path.relative_to(channel.root_dir))})
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "approved", "research_run_id": research_run_id, "opportunity_id": opportunity_id, "brief_path": str(brief_path.relative_to(channel.root_dir)), "brief": brief}
