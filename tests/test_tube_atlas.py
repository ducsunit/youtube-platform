"""Tests for Tube Atlas workflow."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from youtube_pipeline.channel_context import ChannelContext
from youtube_pipeline.research import Evidence
from youtube_pipeline.tube_atlas import (
    AtlasReport,
    SubNiche,
    build_atlas_report,
    atlas_report_to_market_research,
    _analyze_competitor_coverage,
    _generate_angles,
    _calculate_demand_score,
)


def _channel(tmp_path: Path) -> ChannelContext:
    return ChannelContext(
        user_id="dev-user",
        channel_id="kenh-nhat",
        youtube_channel_id="UCL3xuEku7ezoFg2C9pwcTXg",
        root_dir=tmp_path,
        flow_profile="resource_pack",
    )


def test_analyze_competitor_coverage() -> None:
    titles = [
        "tâm linh là gì",
        "phép màu tâm linh",
        "thiền tâm linh cho người mới",
        "tâm linh và khoa học",
    ]
    coverage = _analyze_competitor_coverage(titles, "tâm linh")
    assert "tâm" in coverage
    assert "linh" in coverage
    assert coverage["tâm"] == 4
    assert coverage["linh"] == 4


def test_generate_angles_mechanism() -> None:
    angle, question, promise = _generate_angles("cơ chế tâm linh", [])
    assert "mechanism" in angle
    assert "cơ chế" in question
    assert "cơ chế" in promise


def test_generate_angles_psychology() -> None:
    angle, question, promise = _generate_angles("tâm lý tâm linh", [])
    assert "tâm lý" in question
    assert "tâm lý" in promise


def test_generate_angles_science() -> None:
    angle, question, promise = _generate_angles("khoa học tâm linh", [])
    assert "khoa học" in question
    assert "khoa học" in promise


def test_generate_angles_practice() -> None:
    angle, question, promise = _generate_angles("cách thiền tâm linh", [])
    assert "thực hành" in question or "áp dụng" in question
    assert "thực hành" in promise or "hướng dẫn" in promise


def test_generate_angles_comparison() -> None:
    angle, question, promise = _generate_angles("so sánh tâm linh và khoa học", [])
    assert "so sánh" in question or "khác biệt" in question


def test_calculate_demand_score() -> None:
    # rising_query should score higher
    score_rising = _calculate_demand_score("rising_query", 2, True, True)
    score_question = _calculate_demand_score("related_question", 2, True, True)
    score_organic = _calculate_demand_score("organic_title", 2, True, True)
    assert score_rising > score_question
    assert score_question > score_organic
    assert all(s <= 100 for s in [score_rising, score_question, score_organic])


def test_build_atlas_report_structure(tmp_path: Path) -> None:
    channel = _channel(tmp_path)

    # Mock provider responses
    with mock.patch("youtube_pipeline.tube_atlas.SerpApiProvider.collect") as mock_serp, \
         mock.patch("youtube_pipeline.tube_atlas.GoogleTrendsProvider.collect") as mock_trends:

        mock_serp.return_value = Evidence("serpapi", "ok", "tâm linh", [
            {"title": "tâm linh là gì"},
            {"title": "phép màu tâm linh"},
            {"question": "tâm linh là gì", "type": "related_question"},
            {"question": "cách thực hành tâm linh", "type": "related_question"},
        ])
        mock_trends.return_value = Evidence("google_trends", "ok", "tâm linh", [
            {"query": "tâm linh là gì", "type": "rising_query", "value": 100},
            {"query": "thiền tâm linh", "type": "rising_query", "value": 80},
        ])

        report = build_atlas_report("tâm linh", "VN", "vi", channel)

    assert isinstance(report, AtlasReport)
    assert report.seed_keyword == "tâm linh"
    assert report.country == "VN"
    assert report.language == "vi"
    assert len(report.sub_niches) > 0
    assert len(report.competitor_titles) > 0
    assert len(report.rising_queries) > 0
    assert len(report.related_questions) > 0

    # Top sub-niche should have high demand score
    top = report.sub_niches[0]
    assert isinstance(top, SubNiche)
    assert top.demand_score > 0
    assert top.angle
    assert top.unserved_question
    assert top.promise


def test_atlas_report_to_market_research(tmp_path: Path) -> None:
    channel = _channel(tmp_path)

    report = AtlasReport(
        seed_keyword="tâm linh",
        country="VN",
        language="vi",
        sub_niches=[
            SubNiche(
                keyword="tâm linh là gì",
                source="related_question",
                demand_score=75,
                competitor_count=3,
                angle="recognition → mechanism → self-understanding → practical shift",
                unserved_question="Tại sao tâm linh lại xảy ra theo cơ chế tâm lý nào?",
                promise="Hiểu cơ chế đằng sau tâm linh để tự kiểm soát thay vì bị cuốn theo.",
            ),
            SubNiche(
                keyword="thiền tâm linh",
                source="rising_query",
                demand_score=82,
                competitor_count=2,
                angle="recognition → mechanism → self-understanding → practical shift",
                unserved_question="Làm thế nào để áp dụng thiền tâm linh vào đời sống hàng ngày?",
                promise="Hướng dẫn thực hành thiền tâm linh từng bước, có bằng chứng.",
            ),
        ],
        competitor_titles=["tâm linh là gì", "phép màu tâm linh"],
        rising_queries=["tâm linh là gì", "thiền tâm linh"],
        related_questions=["tâm linh là gì", "cách thực hành tâm linh"],
    )

    research = atlas_report_to_market_research(report, channel, "dev-user")

    assert research.keyword == "tâm linh"
    assert len(research.opportunities) == 2
    assert research.opportunities[0]["keyword"] == "tâm linh là gì"
    assert research.opportunities[1]["keyword"] == "thiền tâm linh"
    assert "atlas_report" in research.normalized
    assert research.evidence["serpapi"].status == "ok"
    assert research.evidence["google_trends"].status == "ok"