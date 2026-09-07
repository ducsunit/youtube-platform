from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_pipeline.channel_context import ChannelContext
from youtube_pipeline.research import (
    Evidence,
    MarketResearch,
    editorial_brief,
    score_opportunities,
)
from youtube_pipeline.resource_pack.pipeline import _approved_research_brief
from youtube_pipeline.resource_pack.validation import validate_topic_candidates
from youtube_pipeline.api.runner import build_new_run_command
from youtube_pipeline.api.pipeline_job import _read_approved_brief


def _channel(tmp_path: Path) -> ChannelContext:
    return ChannelContext(
        user_id="dev-user",
        channel_id="kenh-nhat",
        youtube_channel_id="UCL3xuEku7ezoFg2C9pwcTXg",
        root_dir=tmp_path,
        flow_profile="resource_pack",
    )


def test_score_opportunities_exposes_source_quality_and_risk(tmp_path: Path) -> None:
    channel = _channel(tmp_path)
    evidence = {
        "serpapi": Evidence("serpapi", "ok", "断れない 人", [
            {"title": "result"},
            {"question": "なぜ 断れない 人 になるのか", "snippet": "心理的メカニズム", "type": "related_question"}
        ]),
        "google_trends": Evidence("google_trends", "ok", "断れない 人", [
            {"query": "断れない 人 対処法", "value": 100, "type": "rising_query"}
        ]),
        "vidiq": Evidence("vidiq", "ok", "断れない 人", [{"title": "competitor"}]),
    }
    rows = score_opportunities("断れない 人", "JP", "ja", evidence, channel)
    assert len(rows) == 1
    row = rows[0]
    assert row["evidence_sources"] == ["serpapi", "google_trends", "vidiq"]
    assert row["competitor_coverage"] == "observed"
    assert row["risk_flags"] == []


def test_score_opportunities_flags_insufficient_independent_sources(tmp_path: Path) -> None:
    channel = _channel(tmp_path)
    evidence = {
        "serpapi": Evidence("serpapi", "ok", "keyword", [{"title": "result"}]),
        "google_trends": Evidence("google_trends", "unavailable", "keyword"),
        "vidiq": Evidence("vidiq", "unavailable", "keyword"),
    }
    row = score_opportunities("keyword", "JP", "ja", evidence, channel)[0]
    assert "insufficient_independent_sources" in row["risk_flags"]
    assert "no_specific_demand_signal" in row["risk_flags"]
    assert row["specific_moment_coverage"] == "needs_validation"


def test_editorial_brief_is_channel_and_market_scoped(tmp_path: Path) -> None:
    channel = _channel(tmp_path)
    opportunity = {
        "opportunity_id": "opp-1",
        "keyword": "断れない 人",
        "country": "JP",
        "language": "ja",
        "gap_statement": "specific gap",
        "audience_moment": "specific moment",
        "unserved_question": "why",
        "editorial_angle": "angle",
        "promise": "promise",
        "evidence_sources": ["serpapi", "vidiq"],
    }
    research = MarketResearch(
        research_run_id="research-1", user_id="dev-user", channel_id="kenh-nhat",
        youtube_channel_id=channel.youtube_channel_id, keyword="断れない 人",
        country="JP", language="ja", created_at="now", evidence={}, normalized={},
        opportunities=[opportunity],
    )
    brief = editorial_brief(research, opportunity, channel)
    assert brief["market"] == {"country": "JP", "language": "ja", "keyword": "断れない 人"}
    assert brief["channel_profile"]["flow_profile"] == "resource_pack"
    assert brief["channel_profile"]["stop_before_media_generation"] is True
    assert "resource_pack" in brief["production_flow"]


def test_editorial_brief_rejects_opportunity_from_another_run(tmp_path: Path) -> None:
    channel = _channel(tmp_path)
    research = MarketResearch(
        research_run_id="research-1", user_id="dev-user", channel_id="kenh-nhat",
        youtube_channel_id=channel.youtube_channel_id, keyword="keyword", country="JP",
        language="ja", created_at="now", evidence={}, normalized={}, opportunities=[],
    )
    with pytest.raises(ValueError, match="không thuộc research run"):
        editorial_brief(research, {"opportunity_id": "other"}, channel)


def test_research_locked_candidates_are_one_and_validate() -> None:
    value = {
        "research_locked": True,
        "candidates": [{
            "id": "R01", "topic": "keyword", "audience_moment": "moment",
            "core_pain": "pain", "angle": "angle", "promise": "promise",
            "source_person": "research", "source_work": "keyword",
            "source_concept": "gap", "novelty": "research-locked",
        }],
    }
    validate_topic_candidates(value)
    assert value["candidates"][0]["id"] == "R01"


def test_approved_research_brief_requires_opportunity() -> None:
    class Context:
        config = {"approved_research_brief": {"opportunity": {"opportunity_id": "opp-1"}}}

    assert _approved_research_brief(Context()) == Context.config["approved_research_brief"]


def test_runner_passes_approved_brief_to_worker(tmp_path: Path) -> None:
    command = build_new_run_command(
        "run-1", tmp_path / "run-1", "production", no_channel_data=True,
        user_id="dev-user", channel_id="kenh-nhat", youtube_channel_id="UCx",
        approved_research_brief=tmp_path / "brief.json",
    )
    assert "--approved-research-brief" in command
    assert "--no-channel-data" in command


def test_approved_brief_scope_is_checked(tmp_path: Path) -> None:
    research = tmp_path / "research"
    research.mkdir()
    brief = research / "research-1.editorial-brief.json"
    brief.write_text(json.dumps({
        "user_id": "dev-user", "channel_id": "kenh-nhat",
        "opportunity": {"opportunity_id": "opp-1"},
        "channel_profile": {"stop_before_media_generation": True},
    }), encoding="utf-8")
    data = _read_approved_brief(brief, channel_root=tmp_path, user_id="dev-user", channel_id="kenh-nhat")
    assert data["opportunity"]["opportunity_id"] == "opp-1"


def test_market_research_serializes_evidence_without_losing_status(tmp_path: Path) -> None:
    channel = _channel(tmp_path)
    opportunity = {"opportunity_id": "opp-1"}
    research = MarketResearch(
        research_run_id="research-1", user_id=channel.user_id, channel_id=channel.channel_id,
        youtube_channel_id=channel.youtube_channel_id, keyword="keyword", country="JP",
        language="ja", created_at="now",
        evidence={"serpapi": Evidence("serpapi", "unavailable", "keyword", error="missing key")},
        normalized={"source_status": {"serpapi": "unavailable"}}, opportunities=[opportunity],
    )
    data = research.to_dict()
    assert data["evidence"]["serpapi"]["status"] == "unavailable"
    assert data["evidence"]["serpapi"]["error"] == "missing key"
    assert data["opportunities"] == [opportunity]
