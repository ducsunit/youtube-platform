from youtube_pipeline.resource_pack.competitor import competitor_inject_text
from youtube_pipeline.resource_pack.source_catalog import APPROVED_SOURCE_CATALOG
from youtube_pipeline.resource_pack.validation import (
    derive_visual_density_targets,
    validate_publish_draft,
)


def test_publish_description_has_a_minimum_editorial_contract():
    draft = {
        "description_draft": "これは心理学の動画です。" * 25,
        "chapters_status": "DRAFT_OMITTED",
        "pinned_comment": "どの場面が一番近かったですか？",
        "hashtags": ["#心理学"],
        "tags": ["心理学"],
        "source_note": "参考資料を確認してください。",
    }
    validate_publish_draft(draft)


def test_publish_description_rejects_short_copy_and_excess_hashtags():
    draft = {
        "description_draft": "短い説明です。",
        "chapters_status": "DRAFT_OMITTED",
        "pinned_comment": "質問です。",
        "hashtags": ["#心理学"] * 6,
        "tags": ["心理学"],
        "source_note": "参考資料を確認してください。",
    }
    try:
        validate_publish_draft(draft)
    except ValueError as exc:
        assert "120" in str(exc)
    else:
        raise AssertionError("short description must fail the publish contract")


def test_visual_targets_include_a_recommended_event_range():
    targets = derive_visual_density_targets(
        {"target_duration_minutes": "9-11"},
        {"sections": [{"id": "S1"}] * 6},
    )
    assert targets["minimum_visual_events"] < targets["recommended_visual_events"][0]
    assert targets["recommended_visual_events"][0] < targets["recommended_visual_events"][1]


def test_resource_pack_uses_shared_competitor_writing_context():
    text = competitor_inject_text()
    assert "思考の深淵" in text
    assert "個性化" in text
    assert "35–45" in text


def test_source_catalog_contains_verified_academic_directions():
    urls = {item["url"] for item in APPROVED_SOURCE_CATALOG}
    assert "https://doi.org/10.1037/rev0000033" in urls
    assert "https://doi.org/10.1017/s0954579420000887" in urls
    assert "https://doi.org/10.1037/a0026545" in urls
    assert all(item.get("supports") for item in APPROVED_SOURCE_CATALOG)
