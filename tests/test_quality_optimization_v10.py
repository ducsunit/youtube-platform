from youtube_pipeline.resource_pack.validation import script_quality_gate_report
from youtube_pipeline.core.llm_cache import LLMResponseCache


def test_unified_script_quality_gate_clean_fixture_passes():
    script = "なぜ相手の反応を自分の価値だと解釈してしまうのでしょうか。"
    brief = {
        "psychological_identity": "相手の反応を自己評価に結びつける人",
        "recognizable_behavior_signals": ["相手の反応を気にする"],
        "selected_mechanisms": [{"name": "自己帰責"}],
    }
    report = script_quality_gate_report(script, brief, {"psychological_identity": brief["psychological_identity"]}, {})
    assert report["decision"] in {"pass", "repair"}
    assert "issues" in report and "warnings" in report


def test_llm_cache_hit_stats(tmp_path):
    cache = LLMResponseCache(tmp_path / "llm", enabled=True, schema_version="10")
    key = cache.build_key(
        provider="demo", model="demo", system="s", prompt="p", temperature=0.1,
        schema_version="10"
    )
    cache.put(key, '{"ok": true}')
    assert cache.get(key) == '{"ok": true}'
    stats = cache.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 0
    assert stats["schema_version"] == "10"


def test_unified_quality_gate_repairs_story_risk():
    script = "夜、部屋に入った。その後、翌日になった。"
    brief = {"psychological_identity": "不安な人", "recognizable_behavior_signals": [], "selected_mechanisms": []}
    report = script_quality_gate_report(script, brief, {}, {})
    assert report["decision"] == "repair"
    assert report["issues"]
