from youtube_pipeline.resource_pack.claim_ledger import (
    attach_claim_ledger,
    build_claim_ledger,
    policy_violations,
    source_supports_reinforcement_loop,
    validate_claim_ledger,
)
from youtube_pipeline.resource_pack.validation import validate_plan
from youtube_pipeline.resource_pack.prompts import audit_prompt, repair_prompt, writing_prompt
from youtube_pipeline.resource_pack.pipeline import resource_pack_stages


def _habit_source():
    return {
        "source_concept": "反復と状況の手がかりによって形成される習慣",
        "allowed_paraphrases": ["習慣は反復と状況の手がかりによって形成されます"],
        "editorial_application": "帰宅後にスマートフォンへ向かう反応を観察する",
        "verified_sources": [{"title": "Habit study", "url": "https://example.test", "supports": "反復と状況の手がかりが行動に関係する"}],
        "forbidden_attributions": [],
    }


def test_claim_ledger_blocks_framework_leak_from_another_run():
    ledger = build_claim_ledger(_habit_source())
    validate_claim_ledger(ledger)
    assert "課題の分離" in ledger["forbidden_terms"]
    assert policy_violations("この動画では課題の分離を使います。", ledger) == ["課題の分離"]


def test_plan_rejects_reinforcement_loop_when_source_does_not_support_it():
    source = _habit_source()
    assert not source_supports_reinforcement_loop(source)
    plan = {
        "retention_blueprint": [{"movement": "cold_open"}],
        "hook_draft": "帰宅すると、スマホを開いてしまう。実は、いつもの反応が先に始まっています。",
        "planning_quality_gate": {
            "no_duplicate_sections": True, "every_section_advances_state": True,
            "psychology_is_spine": True, "no_plot_or_character_arc": True,
            "ending_creates_self_understanding": True,
        },
        "sections": [
            {
                "id": "S1", "psychological_job": "recognition", "behavior_link": "行動",
                "why_answered": "なぜ起きるか", "mechanisms_used": [], "example_budget": 0,
                "new_information": "一時的な安心が反応を維持する", "state_advance": "before -> after",
                "so_what_next": "next", "segment_function": "contradiction",
            }
            for _ in range(5)
        ],
    }
    try:
        validate_plan(plan, source)
    except ValueError as exc:
        assert "relief/reinforcement loop" in str(exc)
    else:
        raise AssertionError("expected unsupported reinforcement loop to be rejected")


def test_editorial_application_cannot_unlock_reinforcement_capability():
    source = _habit_source()
    source["editorial_application"] = "短期的な安心が反応を維持する"
    assert not source_supports_reinforcement_loop(source)
    assert not build_claim_ledger(source)["capabilities"]["reinforcement_loop"]


def test_verified_source_can_unlock_reinforcement_capability():
    source = _habit_source()
    source["verified_sources"][0]["supports"] = "短期的な安心による負の強化が回避反応を維持する"
    assert source_supports_reinforcement_loop(source)


def test_claim_ledger_is_visible_to_all_script_decision_prompts():
    source = attach_claim_ledger(_habit_source(), build_claim_ledger(_habit_source()))
    prompts = (
        writing_prompt({}, {}, source, {})
        + audit_prompt("auditor", {}, {}, source, "")
        + repair_prompt({}, {}, source, "", {})
    )
    assert "CLAIM LEDGER RULE" in prompts
    assert "reinforcement_loop=false" in prompts
    assert "課題の分離" in source["claim_ledger"]["forbidden_terms"]


def test_claim_ledger_fingerprints_all_script_mutating_stages():
    stages = {stage.name: stage for stage in resource_pack_stages()}
    for name in ("psychology_brief", "script_contract", "planning", "writing", "review", "consistency", "script_qa", "structure_check"):
        assert "claim_ledger" in stages[name].requires
