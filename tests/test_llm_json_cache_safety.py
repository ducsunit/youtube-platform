from pathlib import Path

from youtube_pipeline.core.llm_cache import LLMResponseCache
from youtube_pipeline.providers import parse_json_object
from youtube_pipeline.domain.models import ValidationError


def test_cache_delete_removes_bad_entry(tmp_path: Path) -> None:
    cache = LLMResponseCache(tmp_path, True, "test")
    key = cache.build_key(
        provider="gemini",
        model="test",
        system="s",
        prompt="p",
        temperature=0.1,
        thinking_level="high",
        schema_version="test",
    )
    cache.put(key, '{"broken":')
    assert cache.get(key) == '{"broken":'
    cache.delete(key)
    assert cache.get(key) is None


def test_parser_rejects_malformed_json_without_silent_corruption() -> None:
    try:
        parse_json_object('{"broken":')
    except ValidationError as exc:
        assert "JSON" in str(exc) or "JSON" in repr(exc)
    else:
        raise AssertionError("Malformed JSON must be rejected")


def test_parser_accepts_valid_review_json_with_japanese_text() -> None:
    text = '{"decision":"pass","revised_draft_clean":"「うん」と返ってきても自分を責めない。\\n相手の感情は相手の課題です。"}'
    value = parse_json_object(text)
    assert value["decision"] == "pass"
    assert "うん" in value["revised_draft_clean"]
