"""Tube Atlas style workflow: broad keyword -> web research -> specific content opportunities."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .research import Evidence, MarketResearch, ResearchProvider, SerpApiProvider, GoogleTrendsProvider, _tokenize, _text_records, save_research
from .channel_context import ChannelContext


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SubNiche:
    keyword: str
    source: str
    demand_score: int
    competitor_count: int
    angle: str
    unserved_question: str
    promise: str


@dataclass
class AtlasReport:
    seed_keyword: str
    country: str
    language: str
    sub_niches: list[SubNiche]
    competitor_titles: list[str]
    rising_queries: list[str]
    related_questions: list[str]
    created_at: str = field(default_factory=now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed_keyword": self.seed_keyword,
            "country": self.country,
            "language": self.language,
            "sub_niches": [
                {
                    "keyword": s.keyword,
                    "source": s.source,
                    "demand_score": s.demand_score,
                    "competitor_count": s.competitor_count,
                    "angle": s.angle,
                    "unserved_question": s.unserved_question,
                    "promise": s.promise,
                }
                for s in self.sub_niches
            ],
            "competitor_titles": self.competitor_titles,
            "rising_queries": self.rising_queries,
            "related_questions": self.related_questions,
            "created_at": self.created_at,
        }


def _extract_competitor_titles(evidence: dict[str, Evidence]) -> list[str]:
    titles = _text_records(evidence, "vidiq") or _text_records(evidence, "serpapi")
    return titles[:20]


def _extract_rising_queries(evidence: dict[str, Evidence]) -> list[str]:
    from .research import _records
    records = _records(evidence, "google_trends")
    return [row.get("query") for row in records if row.get("type") == "rising_query" and row.get("query")]


def _extract_related_questions(evidence: dict[str, Evidence]) -> list[str]:
    from .research import _records
    records = _records(evidence, "serpapi")
    return [row.get("question") for row in records if row.get("type") == "related_question" and row.get("question")]


def _analyze_competitor_coverage(competitor_titles: list[str], seed_keyword: str) -> dict[str, int]:
    """Phân tích độ phủ của đối thủ theo sub-topic."""
    seed_tokens = _tokenize(seed_keyword)
    coverage: dict[str, int] = {}
    for title in competitor_titles:
        title_tokens = _tokenize(title)
        overlap = seed_tokens & title_tokens
        for token in overlap:
            coverage[token] = coverage.get(token, 0) + 1
    return coverage


def _generate_angles(sub_niche_keyword: str, competitor_titles: list[str]) -> tuple[str, str, str]:
    """Tạo angle, unserved_question, promise dựa trên sub-niche."""
    angle_map = {
        "cơ chế": ("recognition → mechanism → self-understanding → practical shift",
                   f"Tại sao {sub_niche_keyword} lại xảy ra theo cơ chế tâm lý nào?",
                   f"Hiểu cơ chế đằng sau {sub_niche_keyword} để tự kiểm soát thay vì bị cuốn theo."),
        "tâm lý": ("recognition → mechanism → self-understanding → practical shift",
                   f"Tâm lý nào đang dẫn dắt hành vi {sub_niche_keyword}?",
                   f"Giải mã tâm lý {sub_niche_keyword} để biến nó thành lợi thế."),
        "khoa học": ("recognition → mechanism → self-understanding → practical shift",
                     f"Khoa học giải thích {sub_niche_keyword} như thế nào?",
                     f"Áp dụng khoa học vào {sub_niche_keyword} thay vì tin theo truyền thuyết."),
        "thực hành": ("recognition → mechanism → self-understanding → practical shift",
                      f"Làm thế nào để áp dụng {sub_niche_keyword} vào đời sống hàng ngày?",
                      f"Hướng dẫn thực hành {sub_niche_keyword} từng bước, có bằng chứng."),
        "so sánh": ("recognition → mechanism → self-understanding → practical shift",
                    f"{sub_niche_keyword} khác gì so với các phương pháp phổ biến?",
                    f"So sánh {sub_niche_keyword} với phương pháp truyền thống để chọn cách phù hợp."),
    }

    keyword_lower = sub_niche_keyword.lower()
    if any(w in keyword_lower for w in ["cơ chế", "mechanism", "vận hành", "hoạt động"]):
        return angle_map["cơ chế"]
    if any(w in keyword_lower for w in ["tâm lý", "psychology", "mindset", "tư duy"]):
        return angle_map["tâm lý"]
    if any(w in keyword_lower for w in ["khoa học", "science", "nghiên cứu", "bằng chứng"]):
        return angle_map["khoa học"]
    if any(w in keyword_lower for w in ["cách", "how to", "hướng dẫn", "thực hành", "bài tập", "làm sao"]):
        return angle_map["thực hành"]
    if any(w in keyword_lower for w in ["so sánh", "vs", "khác biệt", "đâu tốt", "tốt hơn"]):
        return angle_map["so sánh"]

    return angle_map["cơ chế"]


def _calculate_demand_score(source: str, competitor_count: int, has_rising: bool, has_question: bool) -> int:
    base = 30
    if source == "rising_query":
        base += 25
    elif source == "related_question":
        base += 20
    elif source == "organic_title":
        base += 10

    if competitor_count > 0:
        base += min(20, competitor_count * 3)
    if has_rising:
        base += 15
    if has_question:
        base += 10

    return min(100, base)


def build_atlas_report(
    seed_keyword: str,
    country: str,
    language: str,
    channel: ChannelContext,
    providers: list[ResearchProvider] | None = None,
) -> AtlasReport:
    if providers is None:
        providers = [SerpApiProvider(), GoogleTrendsProvider()]

    evidence: dict[str, Evidence] = {}
    for provider in providers:
        try:
            evidence[provider.name] = provider.collect(seed_keyword, country, language)
        except Exception as e:
            evidence[provider.name] = Evidence(provider.name, "error", seed_keyword, error=str(e))

    competitor_titles = _extract_competitor_titles(evidence)
    rising_queries = _extract_rising_queries(evidence)
    related_questions = _extract_related_questions(evidence)

    competitor_coverage = _analyze_competitor_coverage(competitor_titles, seed_keyword)

    candidate_keywords: list[tuple[str, str]] = []
    for q in related_questions:
        candidate_keywords.append((q, "related_question"))
    for r in rising_queries:
        candidate_keywords.append((r, "rising_query"))
    for title in competitor_titles[:10]:
        candidate_keywords.append((title, "organic_title"))

    seen = set()
    sub_niches: list[SubNiche] = []

    for keyword, source in candidate_keywords:
        kw_lower = keyword.lower().strip()
        if not kw_lower or kw_lower in seen or len(kw_lower) < 3:
            continue
        seen.add(kw_lower)

        competitor_count = sum(1 for t in competitor_titles if kw_lower in t.lower())
        has_rising = any(kw_lower in r.lower() for r in rising_queries)
        has_question = any(kw_lower in q.lower() for q in related_questions)

        demand_score = _calculate_demand_score(source, competitor_count, has_rising, has_question)
        angle, unserved_question, promise = _generate_angles(keyword, competitor_titles)

        sub_niches.append(SubNiche(
            keyword=keyword,
            source=source,
            demand_score=demand_score,
            competitor_count=competitor_count,
            angle=angle,
            unserved_question=unserved_question,
            promise=promise,
        ))

    sub_niches.sort(key=lambda x: x.demand_score, reverse=True)

    return AtlasReport(
        seed_keyword=seed_keyword,
        country=country,
        language=language,
        sub_niches=sub_niches[:15],
        competitor_titles=competitor_titles,
        rising_queries=rising_queries,
        related_questions=related_questions,
    )


def atlas_report_to_market_research(report: AtlasReport, channel: ChannelContext, user_id: str) -> MarketResearch:
    evidence = {
        "serpapi": Evidence("serpapi", "ok", report.seed_keyword, [
            {"title": t} for t in report.competitor_titles
        ] + [
            {"question": q, "type": "related_question"} for q in report.related_questions
        ]),
        "google_trends": Evidence("google_trends", "ok", report.seed_keyword, [
            {"query": r, "type": "rising_query"} for r in report.rising_queries
        ]),
    }

    opportunities = []
    for i, sub in enumerate(report.sub_niches[:5]):
        opp_id = "opp-" + hashlib.sha1(f"{report.country}:{report.language}:{sub.keyword}".encode()).hexdigest()[:10]
        opportunities.append({
            "opportunity_id": opp_id,
            "keyword": sub.keyword,
            "country": report.country,
            "language": report.language,
            "gap_statement": f"Đối thủ bao phủ '{report.seed_keyword}' ở mức tổng quát; sub-niche '{sub.keyword}' có nhu cầu cụ thể nhưng chưa được giải quyết sâu theo cơ chế tâm lý.",
            "audience_moment": f"Người xem tại {report.country} đang tìm: {sub.unserved_question}",
            "unserved_question": sub.unserved_question,
            "editorial_angle": sub.angle,
            "promise": sub.promise,
            "competitor_coverage": "observed" if sub.competitor_count > 0 else "low",
            "specific_moment_coverage": "evidence_backed",
            "evidence_sources": ["serpapi", "google_trends"],
            "evidence_count": len(report.competitor_titles) + len(report.rising_queries) + len(report.related_questions),
            "evidence_summary": {
                "competitors": {"observed_items": sub.competitor_count, "keyword_aligned_items": sub.competitor_count},
                "trends": {"rising_queries": report.rising_queries[:5], "timeline_points": 52},
                "questions": report.related_questions[:5],
            },
            "channel_fit": "high",
            "opportunity_score": sub.demand_score,
            "score_breakdown": {"demand": sub.demand_score, "evidence_quality": 25, "competitor_coverage": 15, "channel_fit": 20},
            "risk_flags": [] if sub.demand_score > 60 else ["needs_validation"],
            "coverage_terms": [sub.keyword],
        })

    return MarketResearch(
        research_run_id=f"atlas-{hashlib.sha1(report.seed_keyword.encode()).hexdigest()[:12]}",
        user_id=user_id,
        channel_id=channel.channel_id,
        youtube_channel_id=channel.youtube_channel_id,
        keyword=report.seed_keyword,
        country=report.country,
        language=report.language,
        created_at=report.created_at,
        evidence=evidence,
        normalized={"atlas_report": report.to_dict()},
        opportunities=opportunities,
    )