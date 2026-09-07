"""Keyword -> market intelligence -> channel-specific resource brief.

The module deliberately keeps provider payloads separate from the normalized
opportunity model. Providers are optional: when credentials are absent the run
still produces an auditable report with explicit ``unavailable`` evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .channel_context import ChannelContext, validate_scope_id


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request_json(url: str, headers: dict[str, str] | None = None, timeout: int = 20) -> Any:
    request = urllib.request.Request(url, headers=headers or {"User-Agent": "youtube-pipeline-research/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return slug[:80] or "research"


def _redact_text(value: str | None) -> str | None:
    if value is None:
        return None
    return re.sub(r"([?&](?:api_key|key|token|password)=)[^&\s]+", r"\1[REDACTED]", value, flags=re.IGNORECASE)


def _error_category(error: str | None) -> str | None:
    if not error:
        return None
    text = error.casefold()
    error = _redact_text(error)

    if "403" in text or "tunnel" in text or "proxy" in text:
        return "network_tunnel_blocked"
    if "not configured" in text or "chưa được cấu hình" in text or "cần " in text:
        return "configuration_missing"
    if "json" in text or "decode" in text:
        return "malformed_provider_response"
    return "provider_error"


@dataclass
class Evidence:
    source: str
    status: str
    query: str
    records: list[dict[str, Any]] = field(default_factory=list)
    retrieved_at: str = field(default_factory=now)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MarketResearch:
    research_run_id: str
    user_id: str
    channel_id: str
    youtube_channel_id: str
    keyword: str
    country: str
    language: str
    created_at: str
    evidence: dict[str, Evidence]
    normalized: dict[str, Any]
    opportunities: list[dict[str, Any]]
    selected_opportunity_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["evidence"] = {key: item.to_dict() for key, item in self.evidence.items()}
        return value


class ResearchProvider:
    name = "provider"

    def collect(self, keyword: str, country: str, language: str) -> Evidence:
        raise NotImplementedError


class SerpApiProvider(ResearchProvider):
    name = "serpapi"

    def collect(self, keyword: str, country: str, language: str) -> Evidence:
        key = os.getenv("SERPAPI_KEY") or os.getenv("SERPAPI_KEY")
        query = keyword
        if not key:
            return Evidence(self.name, "unavailable", query, error="SERPAPI_KEY chưa được cấu hình")
        params = urllib.parse.urlencode({"engine": "google", "q": keyword, "gl": country.lower(), "hl": language, "api_key": key})
        try:
            raw = _request_json("https://serpapi.com/search.json?" + params)
            records = []
            for row in raw.get("organic_results", [])[:20]:
                records.append({"title": row.get("title"), "link": row.get("link"), "snippet": row.get("snippet")})
            for row in raw.get("related_questions", [])[:10]:
                records.append({"question": row.get("question"), "snippet": row.get("snippet"), "type": "related_question"})
            return Evidence(self.name, "ok", query, records)
        except Exception as exc:  # network/provider errors belong in the report
            return Evidence(self.name, "error", query, error=str(exc))


class GoogleTrendsProvider(ResearchProvider):
    name = "google_trends"

    def collect(self, keyword: str, country: str, language: str) -> Evidence:
        # Prefer SerpApi's documented google_trends engine when the same API key
        # is available. A JSON export remains supported for offline/reproducible
        # runs and for accounts that use a separate Trends connector.
        key = os.getenv("SERPAPI_KEY") or os.getenv("SERPAPI_KEY")
        if key:
            params = urllib.parse.urlencode({
                "engine": "google_trends",
                "q": keyword,
                "geo": country,
                "hl": language,
                "date": "today 12-m",
                "data_type": "TIMESERIES",
                "api_key": key,
            })
            try:
                raw = _request_json("https://serpapi.com/search.json?" + params)
                records: list[dict[str, Any]] = []
                for row in raw.get("interest_over_time", {}).get("timeline_data", [])[-52:]:
                    records.append({"date": row.get("date"), "values": row.get("values", [])})
                for row in raw.get("related_queries", {}).get("rising", [])[:20]:
                    records.append({"query": row.get("query"), "value": row.get("value"), "type": "rising_query"})
                if records:
                    return Evidence(self.name, "ok", keyword, records)
                return Evidence(self.name, "error", keyword, error="Google Trends trả về không có timeline/related queries")
            except Exception as exc:
                return Evidence(self.name, "error", keyword, error=str(exc))
        path = os.getenv("GOOGLE_TRENDS_JSON")
        if not path:
            return Evidence(self.name, "unavailable", keyword, error="Cần SERPAPI_KEY hoặc GOOGLE_TRENDS_JSON")
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
            records = raw if isinstance(raw, list) else [{"country": country, "language": language, "payload": raw}]
            return Evidence(self.name, "ok", keyword, records)
        except Exception as exc:
            return Evidence(self.name, "error", keyword, error=str(exc))


class VidiqProvider(ResearchProvider):
    name = "vidiq"

    def collect(self, keyword: str, country: str, language: str) -> Evidence:
        # vidIQ research is intentionally supplied as an export because the
        # desktop OAuth/MCP connection is not available inside this backend.
        # Never turn a missing export into zero demand or fake competitor data.
        path = os.getenv("VIDIQ_RESEARCH_JSON")
        if not path:
            return Evidence(self.name, "unavailable", keyword, error="vidIQ tùy chọn: set VIDIQ_RESEARCH_JSON nếu có export")
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
            records = raw if isinstance(raw, list) else [raw]
            return Evidence(self.name, "ok", keyword, records)
        except Exception as exc:
            return Evidence(self.name, "error", keyword, error=str(exc))


def _text_records(evidence: dict[str, Evidence], source: str) -> list[str]:
    values: list[str] = []
    for row in _records(evidence, source):
        for key in ("title", "query", "question", "keyword", "name"):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                values.append(value.strip())
                break
    return values


def _tokenize(value: str) -> set[str]:
    return {token.casefold() for token in re.findall(r"[A-Za-z0-9À-ỹぁ-んァ-ン一-龯]{2,}", value)}


def _competitor_summary(evidence: dict[str, Evidence], keyword: str) -> dict[str, Any]:
    titles = _text_records(evidence, "vidiq") or _text_records(evidence, "serpapi")
    keyword_tokens = _tokenize(keyword)
    covered = [title for title in titles if keyword_tokens and keyword_tokens & _tokenize(title)]
    return {
        "observed_items": len(titles),
        "keyword_aligned_items": len(covered),
        "sample_titles": titles[:10],
        "coverage_ratio": round(len(covered) / len(titles), 3) if titles else None,
    }


def _trends_summary(evidence: dict[str, Evidence]) -> dict[str, Any]:
    records = _records(evidence, "google_trends")
    rising = [row.get("query") for row in records if row.get("type") == "rising_query" and row.get("query")]
    points = [row for row in records if row.get("values")]
    return {"rising_queries": rising[:10], "timeline_points": len(points)}


def _records(evidence: dict[str, Evidence], source: str) -> list[dict[str, Any]]:
    return evidence.get(source, Evidence(source, "unavailable", "")).records


def _coverage_terms(keyword: str, evidence: dict[str, Evidence]) -> list[str]:
    terms = [keyword]
    for row in _records(evidence, "serpapi"):
        value = row.get("question") or row.get("title")
        if value and isinstance(value, str):
            terms.append(value[:160])
    return terms[:12]


def score_opportunities(keyword: str, country: str, language: str, evidence: dict[str, Evidence], channel: ChannelContext) -> list[dict[str, Any]]:
    source_names = [key for key, item in evidence.items() if item.status == "ok"]
    source_count = len(source_names)
    total_records = sum(len(item.records) for item in evidence.values())
    competitor = _competitor_summary(evidence, keyword)
    trends = _trends_summary(evidence)
    questions = [row.get("question") for row in _records(evidence, "serpapi") if row.get("question")]
    rising = trends["rising_queries"]
    demand_score = min(30, total_records // 2 + min(12, len(rising) * 2))
    evidence_score = min(30, source_count * 10)
    competitor_score = min(20, competitor["observed_items"] * 2)
    channel_score = 20 if channel.flow_profile in {"resource_pack", "psychology_jp"} else 12
    score = min(100, demand_score + evidence_score + competitor_score + channel_score)
    risk_flags: list[str] = []
    if source_count < 2:
        risk_flags.append("insufficient_independent_sources")
    if not competitor["observed_items"]:
        risk_flags.append("no_competitor_coverage")
    if not questions and not rising:
        risk_flags.append("no_specific_demand_signal")
    moment_seed = questions[0] if questions else (rising[0] if rising else keyword)
    gap = (
        f"Đối thủ đang bao phủ '{keyword}' ở mức chủ đề; chưa có bằng chứng đủ mạnh rằng họ giải quyết "
        f"khoảnh khắc/câu hỏi cụ thể '{moment_seed}' theo cấu trúc cơ chế tâm lý trước giải pháp."
    )
    return [{
        "opportunity_id": "opp-" + hashlib.sha1(f"{country}:{language}:{keyword}".encode()).hexdigest()[:10],
        "keyword": keyword,
        "country": country,
        "language": language,
        "gap_statement": gap,
        "audience_moment": f"Người xem tại {country} đang tìm câu trả lời cho: {moment_seed}",
        "unserved_question": str(moment_seed),
        "editorial_angle": "recognition → mechanism → self-understanding → practical shift",
        "promise": f"Hiểu chính xác điều đang xảy ra phía sau '{keyword}' mà không biến nó thành lời khuyên sáo rỗng.",
        "competitor_coverage": "observed" if competitor["observed_items"] else "unknown",
        "specific_moment_coverage": "evidence_backed" if questions or rising else "needs_validation",
        "evidence_sources": source_names,
        "evidence_count": total_records,
        "evidence_summary": {"competitors": competitor, "trends": trends, "questions": questions[:10]},
        "channel_fit": "high" if channel.flow_profile in {"resource_pack", "psychology_jp"} else "review",
        "opportunity_score": score,
        "score_breakdown": {"demand": demand_score, "evidence_quality": evidence_score, "competitor_coverage": competitor_score, "channel_fit": channel_score},
        "risk_flags": risk_flags,
        "coverage_terms": _coverage_terms(keyword, evidence),
    }]


def _provider_status(evidence: dict[str, Evidence]) -> dict[str, dict[str, Any]]:
    return {
        key: {"status": item.status, "record_count": len(item.records), "error": item.error}
        for key, item in evidence.items()
    }


def research_readiness(research: MarketResearch) -> dict[str, Any]:
    successful = [name for name, item in research.evidence.items() if item.status == "ok"]
    blocking = [flag for row in research.opportunities for flag in row.get("risk_flags", [])]
    return {
        "can_approve": bool(research.opportunities) and not blocking,
        "successful_sources": successful,
        "blocking_risk_flags": sorted(set(blocking)),
    }


def build_research(
    user_id: str,
    channel: ChannelContext,
    keyword: str,
    country: str,
    language: str,
    research_run_id: str | None = None,
    log_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> MarketResearch:
    """Collect research evidence while emitting redacted, structured lifecycle events."""
    validate_scope_id(user_id, "user_id")
    keyword = str(keyword or "").strip()
    country = str(country or "").strip().upper()
    language = str(language or "").strip().lower()
    if not keyword:
        raise ValueError("keyword không được để trống")
    if not re.fullmatch(r"[A-Z]{2}", country):
        raise ValueError("country phải là mã ISO 2 ký tự, ví dụ JP")
    if not re.fullmatch(r"[a-z]{2}(?:-[A-Z]{2})?", language):
        raise ValueError("language không hợp lệ")

    rid = research_run_id or f"research-{uuid.uuid4().hex[:12]}"
    emit = log_event or (lambda _event, _fields: None)
    emit("research_started", {"research_run_id": rid, "country": country, "language": language})
    evidence: dict[str, Evidence] = {}
    for provider in (SerpApiProvider(), GoogleTrendsProvider(), VidiqProvider()):
        emit("provider_started", {"provider": provider.name})
        item = provider.collect(keyword, country, language)
        evidence[provider.name] = item
        event = "provider_completed" if item.status == "ok" else f"provider_{item.status}"
        emit(event, {
            "provider": provider.name,
            "record_count": len(item.records),
            "error_category": _error_category(item.error),
            "error": _redact_text(item.error),
        })
    normalized = {
        "keyword": keyword,
        "country": country,
        "language": language,
        "demand_signals": {key: len(item.records) for key, item in evidence.items()},
        "source_status": {key: item.status for key, item in evidence.items()},
        "provider_summary": _provider_status(evidence),
    }
    opportunities = score_opportunities(keyword, country, language, evidence, channel)
    readiness = research_readiness(MarketResearch(
        rid, user_id, channel.channel_id, channel.youtube_channel_id, keyword, country, language,
        now(), evidence, normalized, opportunities,
    ))
    emit("opportunities_scored", {
        "opportunity_count": len(opportunities),
        "successful_source_count": len(readiness["successful_sources"]),
        "can_approve": readiness["can_approve"],
        "blocking_risk_flags": readiness["blocking_risk_flags"],
    })
    emit("research_completed", {"research_run_id": rid, "can_approve": readiness["can_approve"]})
    return MarketResearch(rid, user_id, channel.channel_id, channel.youtube_channel_id, keyword, country, language, now(), evidence, normalized, opportunities)


def editorial_brief(research: MarketResearch, opportunity: dict[str, Any], channel: ChannelContext) -> dict[str, Any]:
    if opportunity.get("opportunity_id") not in {row.get("opportunity_id") for row in research.opportunities}:
        raise ValueError("opportunity không thuộc research run")
    return {
        "schema_version": 1,
        "research_run_id": research.research_run_id,
        "user_id": research.user_id,
        "channel_id": channel.channel_id,
        "youtube_channel_id": channel.youtube_channel_id,
        "market": {"country": research.country, "language": research.language, "keyword": research.keyword},
        "opportunity": opportunity,
        "channel_profile": {"flow_profile": channel.flow_profile, "resource_flow": "resource_pack", "stop_before_media_generation": True},
        "production_flow": ["research_locked", "source_lock", "psychology_brief", "script_contract", "planning", "script", "review", "thumbnail", "image_strategy", "image_prompts", "publish_draft", "resource_pack"],
        "manual_next_step": "Review this brief and resource pack, then generate images/audio and build video manually.",
    }


def save_research(root: Path, research: MarketResearch) -> Path:
    directory = root / "research"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{_safe_slug(research.research_run_id)}.json"
    path.write_text(json.dumps(research.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path
