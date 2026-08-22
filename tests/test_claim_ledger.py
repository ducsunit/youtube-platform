from youtube_pipeline.resource_pack.claim_ledger import (
    attach_claim_ledger,
    build_claim_ledger,
    causal_capability_violations,
    policy_violations,
    source_supports_reinforcement_loop,
    source_causal_capabilities,
    validate_claim_ledger,
)
from youtube_pipeline.resource_pack.validation import (
    validate_plan,
    validate_psychology_brief,
    validate_source_bounded_brief_causality,
)
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


def test_prediction_error_source_does_not_unlock_human_learning_or_behavior_chain():
    source = {
        "source_concept": "報酬予測誤差",
        "allowed_paraphrases": ["脳は報酬そのものだけでなく、予測とのずれにも反応します"],
        "editorial_application": "結果と期待の距離を観察する",
        "verified_sources": [{
            "title": "Prediction study",
            "url": "https://example.test",
            "supports": "dopamine-neuron responses related to reward prediction and prediction error in primates",
        }],
        "forbidden_attributions": [],
    }
    assert causal_capability_violations(
        "予測誤差のあと、次の予測を見直し、行動を止めることがあります。", source
    ) == [
        "prediction_error_updates_future_prediction",
        "prediction_error_direct_behavior_effect",
    ]


def _source_bounded_brief(chain: str, *, why: str = "反復と状況の手がかりが行動に関係する"):
    return {
        "phenomenon_or_type": "帰宅後にスマートフォンを開く反応",
        "psychological_identity": "状況の手がかりと反復に結びついた習慣",
        "core_psychological_question": "なぜ意図よりいつもの反応が先に始まるのか",
        "main_tension": "変えたい意図と繰り返される反応が並ぶ",
        "recognizable_behavior_signals": ["帰宅後に座る", "スマートフォンを開く", "先延ばしになる"],
        "common_misconception": "意志が弱い",
        "early_reframe": "反復と状況の手がかりを見直す",
        "editorial_dna": {"audience_pain": "始められない", "behavioral_entry": "帰宅後にスマートフォンを開く", "contradiction": "やることは分かっている", "emotional_promise": "反応の条件を観察できる", "memory_line": "意図だけでは始まらない日がある", "title_angle": "始められない理由", "thumbnail_conflict": "スマートフォンとやること"},
        "mechanism_candidates": [{"name": "習慣", "role": "candidate", "source_support": "反復と状況", "confidence": "high"}],
        "selected_mechanisms": [{"name": "反復と状況の手がかりによって形成される習慣", "role": "mechanism", "behavior_explained": "帰宅後の反応", "why": why, "inner_process": "状況と反応の結びつきを観察する", "evidence_status": "verified", "source_boundary": "反復と状況の手がかりの関係まで"}],
        "causal_chain": [chain],
        "inner_process_map": [{"trigger": "帰宅", "thought_attention_body": "状況に結びついた反応を観察する", "response": "スマートフォンを開く", "function_or_cost": "意図だけでは始まりにくい"}],
        "origin_status": "skip", "strength_status": "skip", "cost_status": "useful", "practical_shift_status": "useful", "route": "PROCESS", "exclusions": ["diagnosis"],
    }


def test_brief_rejects_unsupported_decision_fatigue_chain_before_writing():
    source = attach_claim_ledger(_habit_source(), build_claim_ledger(_habit_source()))
    brief = _source_bounded_brief("誘惑が見える -> 注意が向く -> 判断が繰り返されて疲れる", why="判断が多いほど疲れが残る")
    validate_psychology_brief(brief, source)
    try:
        validate_source_bounded_brief_causality(brief, source)
    except ValueError as exc:
        assert "attention_pathway" in str(exc)
        assert "decision_fatigue" in str(exc)
    else:
        raise AssertionError("expected unsupported causal chain to be rejected")


def test_source_bounded_habit_brief_passes_without_extra_causal_chain():
    source = attach_claim_ledger(_habit_source(), build_claim_ledger(_habit_source()))
    brief = _source_bounded_brief("反復と状況の手がかり -> 行動が起こりやすくなりうる")
    validate_psychology_brief(brief, source)
    validate_source_bounded_brief_causality(brief, source)
    capabilities = source_causal_capabilities(source)
    assert capabilities["attention_pathway"] is False
    assert capabilities["decision_fatigue"] is False


def test_claim_ledger_is_visible_to_all_script_decision_prompts():
    source = attach_claim_ledger(_habit_source(), build_claim_ledger(_habit_source()))
    prompts = (
        writing_prompt({}, {}, source, {})
        + audit_prompt("auditor", {}, {}, source, "")
        + repair_prompt({}, {}, source, "", {})
    )
    assert "CLAIM LEDGER RULE" in prompts
    assert "reinforcement_loop=false" in prompts
    assert "Missing in-script citation is advisory only" in prompts
    assert "課題の分離" in source["claim_ledger"]["forbidden_terms"]


def test_claim_ledger_fingerprints_all_script_mutating_stages():
    stages = {stage.name: stage for stage in resource_pack_stages()}
    for name in ("narrative_brief", "writing", "script_audit", "script_qa", "structure_check"):
        assert "claim_ledger" in stages[name].requires
