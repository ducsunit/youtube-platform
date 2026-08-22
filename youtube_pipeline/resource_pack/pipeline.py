from __future__ import annotations

import json
import hashlib
import logging
import re
import shutil
import uuid
from pathlib import Path
from typing import Callable

from ..core import ArtifactStore, FunctionStage, PipelineEngine, RunContext, RunState, StageResult
from .sections import PAUSE_BEFORE_OUTRO, PAUSE_BETWEEN_SECTIONS, PAUSE_PARAGRAPH_BREAK, build_tts_ready, insert_pause_tags, normalize_text, split_script_sections, split_tts_chunks, strip_minimax_tags
from .metrics import build_pause_map, non_whitespace_chars, scrub_source_citation_tokens, validate_japanese_script
from .analysis import build_channel_snapshot, build_performance_review
from .competitor import competitor_inject_text
from .providers import DemoResourceProvider, ResourceContentProvider, _run_provider_tasks_parallel
from .claim_ledger import (
    attach_claim_ledger,
    build_claim_ledger,
    causal_capability_violations,
    policy_violations,
    validate_claim_ledger,
)
from .prompts import (
    baked_text_thumbnail_prompt,
    target_duration_min_from_contract,
    target_min_chars_from_contract,
)
from ..topic_history import annotate_candidates, duplicate_reason, load_history, record_drafted

PRODUCTION_POLICY_VERSION = "2026-08-22.1"
STRUCTURE_POLICY_VERSION = "2026-08-22.1"
from .validation import (
    VALIDATION_PHRASES_JA,
    SUGGESTED_FORMAT_GATE,
    anti_story_findings,
    audit_passes,
    format_gate_verdict,
    generic_selfhelp_findings,
    direct_address_findings,
    normalize_audit_report,
    psychology_format_metrics,
    psychology_hook_findings,
    psychology_review_gate_verdict,
    select_video_candidates,
    validate_contract,
    normalize_contract_format_lock,
    normalize_contract_titles,
    normalize_title_hook_contract,
    normalize_review_list,
    validate_image_strategy,
    normalize_image_prompts,
    validate_plan,
    normalize_editorial_promise,
    validate_psychology_brief,
    validate_source_bounded_brief_causality,
    normalize_score_0_10,
    validate_prompt_pack,
    validate_publish_draft,
    validate_source_pack,
    validate_thumbnail,
    normalize_thumbnail_prompt,
    HOOK_SCENE_START_MARKERS_JA,
    HOOK_PSYCHOLOGY_MARKERS_JA,
    validate_topic_candidates,
    validate_topic_research,
    validate_topic_selection,
    unsupported_source_claims,
    mechanism_is_covered,
    title_hook_alignment,
)

logger = logging.getLogger(__name__)

MINIMAX_PROFILE = {
    "provider": "MiniMax",
    "speed": 1.02,
    "pitch": -1,
    "volume": 1.02,
    "reference_cpm_min": 380,
    "reference_cpm_max": 400,
    "calibration_required": False,
}


def _script_repetition_findings(script: str) -> list[dict]:
    """Find repeated long propositions before TTS and visual generation."""
    def normalize(value: str) -> str:
        return re.sub(r"[^一-龿ぁ-んァ-ンA-Za-z0-9]", "", value).lower()

    def grams(value: str) -> set[str]:
        compact = normalize(value)
        return {compact[index:index + 3] for index in range(max(0, len(compact) - 2))}

    sentences = [item.strip() for item in re.split(r"(?<=[。！？!?])\s*", script or "") if item.strip()]
    seen: list[tuple[int, set[str]]] = []
    repeated: list[dict] = []
    for index, sentence in enumerate(sentences):
        sentence_grams = grams(sentence)
        if len(sentence) < 24 or not sentence_grams:
            continue
        for previous_index, previous_grams in seen[-24:]:
            union = len(sentence_grams | previous_grams)
            similarity = len(sentence_grams & previous_grams) / union if union else 0.0
            if similarity >= 0.62:
                repeated.append({"first": previous_index, "second": index, "similarity": round(similarity, 2)})
                break
        seen.append((index, sentence_grams))
    return repeated


def _json(context: RunContext, artifact_type: str) -> dict:
    return context.store.read_json(artifact_type, context.state)


def _text(context: RunContext, artifact_type: str) -> str:
    return context.store.read_text(artifact_type, context.state)


def _source_policy(context: RunContext) -> dict:
    """Return the locked source pack augmented with its deterministic ledger."""
    return attach_claim_ledger(_json(context, "source_pack"), _json(context, "claim_ledger"))


def _psychology_topic_context(context: RunContext) -> str:
    """Build a backward-compatible topic string enriched with the selected psychological spine."""
    selected = _json(context, "selected_topic")
    parts = [selected.get("selected_topic", context.topic)]
    for key, label in (
        ("psychological_pattern", "psychological_pattern"),
        ("core_pain", "core_pain"),
        ("audience_moment", "recognition_context"),
        ("angle", "angle"),
        ("promise", "promise"),
    ):
        value = selected.get(key)
        if value:
            parts.append(f"{label}: {value}")
    return "\n".join(parts)


def _ingest(context: RunContext) -> StageResult:
    snapshot = build_channel_snapshot(context.raw_data)
    ref = context.store.put_json("channel_snapshot", "research/channel_snapshot.json", snapshot, "ingest")
    return StageResult([ref], {"video_count": snapshot["video_count"]}, snapshot.get("data_quality", []))


def _manual_topic(context: RunContext) -> str:
    provenance = context.config.get("input_provenance")
    if not isinstance(provenance, dict) or provenance.get("mode") != "manual_topic_no_channel_data":
        return ""
    value = str(provenance.get("manual_topic") or context.config.get("manual_topic") or "").strip()
    return "" if value.casefold() in {"", "none", "null", "undefined", "n/a"} else value


def _performance(context: RunContext) -> StageResult:
    review = build_performance_review(_json(context, "channel_snapshot"))
    ref = context.store.put_json("performance_review", "research/performance_review.json", review, "performance")
    return StageResult([ref], warnings=review["warnings"])


def _topic_research(context: RunContext) -> StageResult:
    topic = _manual_topic(context)
    if topic:
        value = {
            "channel_positioning": "Manual-topic run without channel analytics.",
            "audience_pains": ["指定テーマに含まれる日常の心理的負担", "その行動を自分の欠点として解釈すること"],
            "content_gaps": ["チャンネル分析を使わず、指定テーマをsource-boundedに整理する"],
            "trend_hypotheses": [
                {"hypothesis": "Manual topic is intentionally locked by the operator.", "evidence": "No channel dataset selected.", "confidence": "operator_locked"}
            ],
            "source_directions": [
                {"person": "To be determined by source lock", "work": "To be determined by source lock", "concept": "To be determined by source lock"}
            ],
            "research_notes": ["Manual topic locked by operator; no channel dataset was used for topic research."],
        }
        validate_topic_research(value)
        ref = context.store.put_json("topic_research", "research/topic-research.json", value, "topic_research")
        return StageResult([ref], {"manual_topic": topic, "channel_data_used": False})
    value = context.provider.research_topics(
        _json(context, "channel_snapshot"),
        _json(context, "performance_review"),
    )
    validate_topic_research(value)
    ref = context.store.put_json("topic_research", "research/topic-research.json", value, "topic_research")
    return StageResult(
        [ref],
        {
            "audience_pains": len(value["audience_pains"]),
            "content_gaps": len(value["content_gaps"]),
        },
    )


def _topic_candidates(context: RunContext) -> StageResult:
    topic = _manual_topic(context)
    if topic:
        value = {
            "candidates": [
                {
                    "id": "M%02d" % index,
                    "topic": topic if index == 1 else "%s（視点%d）" % (topic, index),
                    "audience_moment": "このテーマに関係する日常の具体的な瞬間",
                    "core_pain": "行動の背景を自分の欠点として扱ってしまうこと",
                    "angle": "指定テーマを一つの心理的パターンとして整理する",
                    "promise": "行動をより正確に観察する視点を持つ",
                    "source_person": "Manual source lock pending",
                    "source_work": "Manual source lock pending",
                    "source_concept": "Manual source lock pending",
                    "novelty": "operator-locked manual topic",
                }
                for index in range(1, 9)
            ]
        }
        validate_topic_candidates(value)
        ref = context.store.put_json("topic_candidates", "research/topic-candidates.json", value, "topic_candidates")
        return StageResult([ref], {"candidate_count": 8, "manual_topic": topic})
    value = context.provider.create_topic_candidates(
        _json(context, "topic_research"),
        _json(context, "channel_snapshot"),
        _json(context, "performance_review"),
        competitor_inject_text(),
    )
    history = load_history(context.store.root)
    value = annotate_candidates(value, history)
    validate_topic_candidates(value)
    ref = context.store.put_json("topic_candidates", "research/topic-candidates.json", value, "topic_candidates")
    return StageResult([ref], {"candidate_count": len(value["candidates"])})


def _topic_selection(context: RunContext) -> StageResult:
    candidates = _json(context, "topic_candidates")
    topic = _manual_topic(context)
    if topic:
        value = {
            "selected_topic": topic,
            "selected_candidate_id": "M01",
            "selection_reason": "Operator locked this topic; channel analytics were intentionally not used.",
            "scores": {"channel_fit": 0, "audience_pain": 0, "packaging_potential": 0, "retention_fit": 0, "source_strength": 0, "novelty": 0, "total": 0},
            "rejected_topics": [{"candidate_id": "M02", "reason": "Operator locked M01 as the only production topic."}],
            "source_person": "Manual source lock pending",
            "source_work": "Manual source lock pending",
            "source_concept": "Manual source lock pending",
            "audience_moment": "このテーマに関係する日常の具体的な瞬間",
            "promise": "行動をより正確に観察する視点を持つ",
        }
        validate_topic_selection(value, candidates)
        context.state.topic = topic
        context.topic = topic
        ref = context.store.put_json("selected_topic", "research/topic-selection.json", value, "topic_selection")
        return StageResult([ref], {"selected_topic": topic, "manual_topic": True})
    value = context.provider.select_topic(
        candidates,
        _json(context, "topic_research"),
        _json(context, "performance_review"),
    )
    history = load_history(context.store.root)
    published_history = [row for row in history if row.get("status") == "published"]
    if duplicate_reason(value, published_history):
        available = [row for row in candidates.get("candidates", []) if not duplicate_reason(row, published_history)]
        if available:
            replacement = max(available, key=lambda row: int(row.get("novelty", 0)) if str(row.get("novelty", "")).isdigit() else 0)
            value = {**value, "selected_topic": replacement["topic"], "selected_candidate_id": replacement["id"], "source_person": replacement.get("source_person", ""), "source_work": replacement.get("source_work", ""), "source_concept": replacement.get("source_concept", ""), "audience_moment": replacement.get("audience_moment", ""), "promise": replacement.get("promise", ""), "selection_reason": "Deterministically đổi sang candidate chưa xuất hiện trong topic history."}
        else:
            raise RuntimeError("topic_selection deterministic failure: toàn bộ candidate đã xuất hiện trong topic history.")
    validate_topic_selection(value, candidates)
    context.state.topic = value["selected_topic"]
    context.topic = value["selected_topic"]
    ref = context.store.put_json("selected_topic", "research/topic-selection.json", value, "topic_selection")
    return StageResult(
        [ref],
        {
            "selected_topic": value["selected_topic"],
            "score": value["scores"]["total"],
        },
    )


def _source_lock(context: RunContext) -> StageResult:
    value = context.provider.lock_source(context.topic, _json(context, "channel_snapshot"), _json(context, "performance_review"))
    validate_source_pack(value)
    ref = context.store.put_json("source_pack", "research/source_pack.json", value, "source_lock")
    return StageResult([ref], {"verified_sources": len(value["verified_sources"])})


def _claim_ledger(context: RunContext) -> StageResult:
    value = build_claim_ledger(_json(context, "source_pack"))
    validate_claim_ledger(value)
    ref = context.store.put_json("claim_ledger", "research/claim-ledger.json", value, "claim_ledger")
    return StageResult([ref], {"allowed_claims": len(value["allowed_claims"]), "forbidden_terms": len(value["forbidden_terms"])})


def _psychology_brief(context: RunContext) -> StageResult:
    # Keep context.topic as a plain string for backward compatibility, but give
    # the psychology stage the richer selected-topic spine so it does not have
    # to reconstruct the psychological pattern from a bare topic label.
    topic_context = _psychology_topic_context(context)
    value = context.provider.create_psychology_brief(
        topic_context, _source_policy(context), _json(context, "performance_review")
    )
    validate_psychology_brief(value, _source_policy(context))
    validate_source_bounded_brief_causality(value, _source_policy(context))
    ref = context.store.put_json("psychology_brief", "script/psychology-brief.json", value, "psychology_brief")
    return StageResult([ref], {"route": value["route"], "mechanisms": len(value["selected_mechanisms"])})


def _narrative_contract(topic: str, brief: dict) -> dict:
    """Build legacy consumers' contract from the single narrative brief.

    The contract is production metadata, not a second creative decision.  Keeping
    it deterministic removes a frequent source of run-to-run disagreement while
    preserving the artifacts consumed by packaging and visual stages.
    """
    pack = brief.get("narrative_pack") if isinstance(brief.get("narrative_pack"), dict) else {}
    symbolic_spine = pack.get("symbolic_spine") if isinstance(pack.get("symbolic_spine"), dict) else {}
    raw_titles = pack.get("title_candidates") if isinstance(pack.get("title_candidates"), list) else []
    titles = [str(item.get("title", "")).strip() for item in raw_titles if isinstance(item, dict)]
    if not titles:
        titles = [topic, topic + "を抱える人の心理", topic + "が重くなる理由"]
    while len(titles) < 3:
        titles.append(titles[-1])
    chosen = str(pack.get("chosen_title") or titles[0]).strip()
    mechanisms = [str(row.get("name", "")).strip() for row in brief.get("selected_mechanisms", []) if isinstance(row, dict)]
    contract = {
        "core_self_insight": brief["editorial_dna"]["memory_line"],
        "central_emotion": brief["editorial_dna"]["audience_pain"],
        "psychological_identity": brief["psychological_identity"],
        "core_psychological_question": brief["core_psychological_question"],
        "main_tension": brief["main_tension"],
        "route": brief["route"],
        "selected_mechanisms": mechanisms,
        "single_core_promise": brief["editorial_dna"]["emotional_promise"],
        "title_candidates": [{"title": title, "mechanism": mechanisms[0] if mechanisms else "", "char_count": len(title)} for title in titles[:3]],
        "chosen_title": chosen,
        "chosen_title_char_count": len(chosen),
        "target_duration_minutes": "35-45",
        "target_char_min": 13600,
        "target_char_max": 17500,
        "hook_contract": {"recognition_by_seconds": 12, "misconception_or_tension_by_seconds": 30, "first_real_insight_by_seconds": 55, "core_question_by_seconds": 70},
        "format_lock": {
            "primary_format": "symbolic long-form psychological deep-dive",
            "content_center": "心理的パターンと内的プロセス: " + brief["psychological_identity"],
            "primary_narration": "symbolic psychological analysis with reflective narration",
            "secondary_device": "illustrative behavioral examples and symbolic vignettes",
            "forbidden_spine": ["unsupported factual story", "fictional claim presented as evidence", "diagnostic character journey", "chronological biography"],
        },
        "content_spine": {"psychological_pattern": brief["psychological_identity"], "core_question": brief["core_psychological_question"], "central_mechanism": mechanisms[0] if mechanisms else "", "causal_logic": "Use only the locked source support for: " + ", ".join(mechanisms), "viewer_self_understanding": brief["editorial_dna"]["memory_line"], "recurring_symbol": str(pack.get("recurring_symbol") or symbolic_spine.get("ordinary_object_or_place") or ""), "symbolic_boundary": "symbolic scenes are editorial illustration, never source evidence"},
        "recognition_device": {"behavioral_signals": brief["recognizable_behavior_signals"], "micro_examples": [], "usage_rule": "vignettes create recognition or symbolic understanding; they never prove a research claim"},
        "packaging_layer": {"title_question": brief["editorial_dna"]["title_angle"], "thumbnail_question": brief["editorial_dna"]["thumbnail_conflict"], "curiosity_gap": brief["core_psychological_question"], "packaging_must_not_become_content_spine": True},
        "spine_hierarchy": ["felt behavior", "misconception", "early reframe", "source-backed mechanism", "paradox", "quiet landing"],
        "thumbnail_brief": {"click_question": brief["editorial_dna"]["title_angle"], "visual_conflict": brief["editorial_dna"]["thumbnail_conflict"], "title_must_not_repeat": "thumbnail text expresses the emotional contradiction, not the full title"},
    }
    normalize_contract_titles(contract)
    normalize_contract_format_lock(contract)
    normalize_title_hook_contract(contract)
    return contract


def _narrative_plan(brief: dict) -> dict:
    """Convert narrative movements into the compatibility planning artifact."""
    pack = brief.get("narrative_pack") if isinstance(brief.get("narrative_pack"), dict) else {}
    movements = pack.get("movements") if isinstance(pack.get("movements"), list) else []
    revelations = pack.get("revelation_ladder") if isinstance(pack.get("revelation_ladder"), list) else []
    names = [str(row.get("name", "")).strip() for row in brief.get("selected_mechanisms", []) if isinstance(row, dict)]
    if not movements:
        movements = [
            {"phase": "RECOGNITION", "job": "sensory recognition and identity tension", "new_information": brief["common_misconception"]},
            {"phase": "REFRAME_QUESTION", "job": "early reframe and core question", "new_information": brief["early_reframe"]},
            {"phase": "MECHANISM", "job": "source-backed mechanism", "new_information": names[0] if names else brief["psychological_identity"]},
            {"phase": "CONSEQUENCE", "job": "paradox and implication", "new_information": brief["main_tension"]},
            {"phase": "INSIGHT_LANDING", "job": "quiet self-understanding", "new_information": brief["editorial_dna"]["memory_line"]},
        ]
    # A model may provide the compact revelation ladder but omit mechanical
    # movement metadata. Derive those movements without another creative call.
    if revelations and not any(str(row.get("phase", "")).upper() == "MECHANISM" for row in movements):
        insertion = []
        for revelation in revelations[:5]:
            if not isinstance(revelation, dict):
                continue
            insertion.append({
                "phase": "MECHANISM",
                "job": "advance one source-bounded revelation",
                "new_information": revelation.get("new_understanding", ""),
                "viewer_question": revelation.get("viewer_state_change", ""),
                "next_reveal": revelation.get("symbolic_turn", ""),
                "mechanisms_used": names[:1],
            })
        if insertion:
            movements = movements[:2] + insertion + movements[2:]
    sections = []
    for index, movement in enumerate(movements[:7], start=1):
        phase = str(movement.get("phase", "MECHANISM")).upper()
        used = movement.get("mechanisms_used") if isinstance(movement.get("mechanisms_used"), list) else []
        used = [name for name in used if name in names]
        if phase == "MECHANISM" and not used and names:
            used = [names[min(len(sections), len(names) - 1)]]
        sections.append({
            "id": "S%d" % index,
            "phase": phase,
            "segment_function": {"RECOGNITION": "recognition", "REFRAME_QUESTION": "reframe_question", "MECHANISM": "mechanism", "CONSEQUENCE": "integration", "PRACTICAL_SHIFT": "practical_shift", "SELF_OBSERVATION": "integration", "INSIGHT_LANDING": "insight_landing"}.get(phase, "integration"),
            "psychological_job": str(movement.get("job") or movement.get("psychological_job") or "advance the psychological understanding"),
            "behavior_link": str(movement.get("behavior_link") or brief["recognizable_behavior_signals"][0]),
            "why_answered": str(movement.get("viewer_question") or brief["core_psychological_question"]),
            "viewer_question_answered": str(movement.get("viewer_question") or brief["core_psychological_question"]),
            "mechanisms_used": used,
            "example_budget": 1 if phase in {"RECOGNITION", "MECHANISM", "CONSEQUENCE"} else 0,
            "new_information": str(movement.get("new_information") or brief["early_reframe"]),
            "state_advance": "BEFORE: behavior is only a personal flaw -> AFTER: " + str(movement.get("new_information") or "the pattern has a more precise meaning"),
            "so_what_next": str(movement.get("next_reveal") or "the next movement deepens the same central question"),
            "relative_weight": float(movement.get("relative_weight", 1.0) or 1.0),
        })
    for name in names:
        if not any(name in section["mechanisms_used"] for section in sections):
            target = next((section for section in sections if section["segment_function"] == "mechanism"), sections[-2])
            target["mechanisms_used"].append(name)
    hook = str(pack.get("opening_image") or brief["editorial_dna"]["behavioral_entry"]).strip()
    opening_lines = [line.strip() for line in re.split(r"[。！？\n]", hook[:240]) if line.strip()]
    scene_first = bool(opening_lines) and any(marker in opening_lines[0] for marker in HOOK_SCENE_START_MARKERS_JA)
    early_pivot = any(
        marker in line
        for line in opening_lines[:3]
        for marker in HOOK_PSYCHOLOGY_MARKERS_JA
    )
    if scene_first and not early_pivot:
        # narrative_brief owns the plan now, so this guard must live here rather
        # than in the retired multi-call planning repair flow. Keep the model's
        # behavioral recognition, then deterministically state the locked
        # reframe immediately; the writer can still make the prose natural.
        reframe = str(brief.get("early_reframe") or "").strip().rstrip("。！？?!")
        question = str(brief.get("core_psychological_question") or "").strip().rstrip("。！？?!")
        pivot = "実は、" + reframe + "。" if reframe else "なぜ、こうした反応が先に始まるのでしょうか。"
        hook = hook.rstrip() + ("" if hook.endswith(("。", "！", "？")) else "。") + pivot
        if question and "なぜ" not in pivot:
            hook += question + "。"
    if direct_address_findings(hook):
        # 思考の深淵 opens by addressing the viewer in the first breath; add the
        # recognition beat deterministically so a scene-first plan can never
        # reach the writer without one.
        hook = "あなたにも、心当たりはないでしょうか。" + hook

    return {
        "core_question": brief["core_psychological_question"],
        "hook_draft": hook,
        # Compatibility schema requires a non-empty blueprint. This is a
        # semantic marker, not a timestamp schedule or an extra creative pass.
        "retention_blueprint": [{"kind": "revelation_progression", "payoff": brief["core_psychological_question"]}],
        "sections": sections,
        "planning_quality_gate": {"no_duplicate_sections": True, "every_section_advances_state": True, "psychology_is_spine": True, "no_plot_or_character_arc": True, "ending_creates_self_understanding": True},
    }


def _narrative_brief(context: RunContext) -> StageResult:
    """One skill-led creative brief replaces brief, contract and plan calls."""
    topic_context = _psychology_topic_context(context)
    brief = context.provider.create_psychology_brief(topic_context, _source_policy(context), _json(context, "performance_review"))
    normalized_promise = normalize_editorial_promise(brief)
    corrected = False
    try:
        validate_psychology_brief(brief, _source_policy(context))
        validate_source_bounded_brief_causality(brief, _source_policy(context))
    except ValueError as exc:
        # Brief is upstream of all creative artifacts. One explicit correction
        # here prevents a bad causal chain from contaminating the entire run.
        message = str(exc)
        capability_hint = ""
        if "prediction-error" in message or "prediction_error" in message:
            capability_hint = (
                " The locked sources describe prediction/reward-error only as a bounded observation "
                "(for example neural responses); do NOT claim it updates future predictions or directly "
                "changes/starts/stops human behavior. Keep it at the exact descriptive level of the source."
            )
        elif "capability nguồn" in message:
            capability_hint = (
                " Stop the causal chain at the observation/association the locked sources actually support; "
                "do not add a new cognitive mechanism, loop, or downstream behavioral effect."
            )
        correction = (
            "\n\nCORRECTIVE BRIEF PASS (one pass only): the prior brief failed the locked "
            "source boundary with: %s. Return a complete replacement JSON. Keep only "
            "source-supported observations/associations; do not invent attention, judgment, "
            "fatigue, reinforcement, diagnosis, or childhood causal chains.%s"
            % (message, capability_hint)
        )
        brief = context.provider.create_psychology_brief(
            topic_context + correction,
            _source_policy(context),
            _json(context, "performance_review"),
        )
        normalized_promise = normalize_editorial_promise(brief) or normalized_promise
        validate_psychology_brief(brief, _source_policy(context))
        validate_source_bounded_brief_causality(brief, _source_policy(context))
        corrected = True
    contract = _narrative_contract(context.topic, brief)
    validate_contract(contract)
    plan = _narrative_plan(brief)
    validate_plan(plan, _source_policy(context), brief)
    refs = [
        context.store.put_json("psychology_brief", "script/psychology-brief.json", brief, "narrative_brief"),
        context.store.put_json("script_contract", "script/contract.json", contract, "narrative_brief"),
        context.store.put_json("planning", "script/planning.json", plan, "narrative_brief"),
    ]
    warnings = []
    if corrected:
        warnings.append("Narrative brief dùng một corrective source-bound pass.")
    if normalized_promise:
        warnings.append("Đã chuẩn hóa editorial promise khỏi wording chữa lành/generic recovery.")
    return StageResult(
        refs,
        {"movements": len(plan["sections"]), "mechanisms": len(brief["selected_mechanisms"]), "creative_calls": 1 + int(corrected)},
        warnings,
    )


def _writing(context: RunContext) -> StageResult:
    contract = _json(context, "script_contract")
    plan = _json(context, "planning")
    source_pack = _source_policy(context)
    brief = _json(context, "psychology_brief")
    # Do not discover this method through ``__getattr__`` delegation. Legacy
    # provider adapters may proxy a demo provider but intentionally override
    # only write_script(); their explicit implementation remains authoritative.
    writer = getattr(type(context.provider), "write_script_movements", None)
    if callable(writer):
        raw_movements = writer(context.provider, contract, plan, source_pack, brief)
        movements = [
            {
                "id": str(item.get("id") or "S%d" % (index + 1)),
                "target_chars": int(item.get("target_chars") or 0),
                "text": str(item.get("text") or "").strip(),
            }
            for index, item in enumerate(raw_movements)
            if isinstance(item, dict) and str(item.get("text") or "").strip()
        ]
        if not movements:
            raise ValueError("Writer không trả writing movement hợp lệ.")
        value = "\n\n".join(item["text"] for item in movements)
        movement_ref = context.store.put_json("script_movements", "script/movements.json", {"movements": movements}, "writing")
    else:
        # Compatibility for custom providers installed before movement writing.
        value = context.provider.write_script(contract, plan, source_pack, brief)
        movement_ref = None
    ref = context.store.put_text("script_draft", "script/script-draft.txt", value, "writing")
    artifacts = [ref] + ([movement_ref] if movement_ref else [])
    return StageResult(artifacts, {"raw_chars": non_whitespace_chars(value), "writing_movements": len(movements) if movement_ref else 1})


def _script_audit(context: RunContext) -> StageResult:
    """Run one bounded source/editorial audit after writing.

    This deliberately replaces the former independent reviewer plus three-round
    consistency loop.  A run gets one audit and, only for a concrete finding,
    one targeted repair.  Source policy remains authoritative.
    """
    draft = _text(context, "script_draft")
    report = {"decision": "pass", "issues": [], "required_changes": [], "tts_ready": ""}
    refs = [
        context.store.put_json("review_report", "script/review-report.json", report, "script_audit"),
        context.store.put_text("reviewed_script", "script/script-reviewed.txt", draft, "script_audit"),
    ]
    result = _consistency(context, draft)
    return StageResult(refs + result.artifacts, {**result.metrics, "editorial_passes": 1}, result.warnings)


def _build_tts_ready(review: dict, revised: str) -> str:
    """Dựng tts_ready cho gate v7, ưu tiên tag anchors (pipeline tự chèn bằng code).

    Trả rỗng khi không dựng được — bước sections sẽ chèn tag <#x#> deterministic
    thay thế, run không bao giờ chết vì drift tts_ready.
    """
    anchors = review.get("tts_tag_anchors")
    if isinstance(anchors, list) and anchors:
        try:
            return build_tts_ready(revised, anchors)
        except ValueError as exc:
            logger.warning("Reviewer tts_tag_anchors không resolve được (fallback deterministic): %s", exc)
            return ""
    old = review.get("tts_ready")
    if isinstance(old, str) and old.strip():
        if normalize_text(strip_minimax_tags(old)) == normalize_text(revised):
            return old
        logger.warning(
            "Reviewer tts_ready lệch nội dung thật (không chỉ whitespace) — fallback deterministic."
        )
    else:
        logger.warning("Reviewer thiếu cả tts_tag_anchors lẫn tts_ready — fallback deterministic.")
    return ""


def _review(context: RunContext) -> StageResult:
    contract = _json(context, "script_contract")
    plan = _json(context, "planning")
    source_pack = _source_policy(context)
    draft = _text(context, "script_draft")
    review = context.provider.review_script(contract, plan, source_pack, draft, competitor_inject_text())
    if "final_script" in review:
        raise ValueError("Reviewer không được trả final_script; chỉ trả revised_draft_clean.")
    # Reviewer schemas drift in the wild: a provider may return issue objects or a
    # single string. Normalize before the control-flow checks so a formatting
    # variation cannot kill an otherwise valid Run Live.
    review["issues"] = normalize_review_list(review.get("issues"))
    review["required_changes"] = normalize_review_list(review.get("required_changes"))
    decision = str(review.get("decision", "")).strip().lower()
    if decision not in ("pass", "revise"):
        raise ValueError("Reviewer phải có decision pass hoặc revise.")
    if not isinstance(review.get("optimization_report"), str) or not review["optimization_report"].strip():
        raise ValueError("Reviewer thiếu optimization_report.")
    for key in ("issues", "required_changes"):
        if not isinstance(review.get(key), list) or not all(isinstance(item, str) for item in review[key]):
            raise ValueError("Reviewer.%s phải là danh sách chuỗi." % key)
    if decision == "revise" and not review["required_changes"]:
        # Drift format: provider đôi khi chọn revise nhưng bỏ trống structured list.
        # issues[] thường chứa đúng nội dung cần sửa — dùng thay thế; cả hai rỗng
        # nghĩa là reviewer không có yêu cầu hành động nào, hạ về pass thay vì
        # chết run (các gate hậu kiểm consistency/script_qa/structure vẫn chạy).
        if review.get("issues"):
            logger.warning("Reviewer revise nhưng required_changes rỗng — dùng issues[] thay thế.")
            review["required_changes"] = list(review["issues"])
        else:
            logger.warning("Reviewer revise nhưng không có required_changes lẫn issues — hạ decision về pass.")
            decision = "pass"
            review["decision"] = "pass"  # ghi lại để artifact persisted nhất quán
    title_alignment = title_hook_alignment(draft, contract)
    review["title_hook_alignment"] = title_alignment
    if not title_alignment["passed"]:
        decision = "revise"
        review["decision"] = "revise"
        review["required_changes"].append(
            "TITLE-TO-HOOK ALIGNMENT: trong khoảng 20 giây đầu, trả trực tiếp behavior/pain mà title hứa. "
            "Dùng ít nhất một opening anchor (%s), rồi mới chuyển sang reframe/core question; "
            "không lặp nguyên title hay thêm claim mới."
            % ", ".join(title_alignment["anchors"])
        )
    repetition_pairs = _script_repetition_findings(draft)
    review["deterministic_repetition"] = {
        "pair_count": len(repetition_pairs),
        "pairs": repetition_pairs[:10],
        "passed": len(repetition_pairs) < 2,
    }
    if len(repetition_pairs) >= 2:
        decision = "revise"
        review["decision"] = "revise"
        review.setdefault("required_changes", []).append(
            "DETERMINISTIC REPETITION GATE: gộp hoặc xóa các đoạn đang giải thích lại cùng một proposition; "
            "giữ lại bản rõ nhất rồi chuyển sang implication/revelation mới. Không thêm ví dụ, filler hoặc mechanism mới."
        )
    # Phase 7 (plan v2 §12): FORMAT_ALIGNMENT — reviewer phân loại format A–E.
    # D (personal narrative) và E (fictional story) bị cấm làm spine: dù mọi
    # điểm khác pass, decision bắt buộc revise kèm structure rewrite. C chỉ là
    # cảnh báo (target A+B); thiếu field không blocking (review cũ chưa có).
    format_alignment = review.get("format_alignment")
    if isinstance(format_alignment, dict):
        classification = str(format_alignment.get("classification", "")).strip().upper()
        if classification in ("D", "E") and decision == "pass":
            logger.warning("Reviewer format_alignment=%s nhưng decision=pass — ép revise.", classification)
            decision = "revise"
            review["decision"] = "revise"
            review["required_changes"].append(
                "FORMAT_ALIGNMENT %s: xóa chronological story progression; chuyển narrative paragraphs "
                "thành psychological observation, behavioral analysis hoặc mechanism explanation; "
                "giữ ví dụ hữu ích chỉ làm short illustration; không thay story này bằng story khác." % classification
            )
        elif classification == "C":
            review["issues"].append(
                "FORMAT_ALIGNMENT C (self-help essay) — chưa đạt A/B: tăng mechanism depth, "
                "giảm advice/flattery generic."
            )
            if decision == "pass":
                decision = "revise"
                review["decision"] = "revise"
                review.setdefault("required_changes", []).append(
                    "Self-help essay contamination: giữ một practical principle, cắt advice/reassurance chung chung "
                    "và đưa psychology mechanism trở lại làm spine."
                )
    else:
        logger.warning("Reviewer thiếu format_alignment — giữ nguyên decision (không blocking).")

    # The scorecard is diagnostic. Editorial review decides whether one concrete
    # weakness needs a repair; lexical score thresholds must not create a blind
    # rewrite loop. Hard psychology-first checks remain in structure_check.
    if not isinstance(context.provider, DemoResourceProvider):
        review["psychology_gate_diagnostic"] = {
            "passed": psychology_review_gate_verdict(review)[0],
            "failed": psychology_review_gate_verdict(review)[1],
            "blocking": False,
        }
        hook_findings = psychology_hook_findings(draft) + direct_address_findings(draft)
        if hook_findings:
            decision = "revise"
            review["decision"] = "revise"
            review.setdefault("required_changes", [])
            review["required_changes"].extend(
                "HOOK FORMAT GATE: %s — trong tối đa 6 câu đầu, giữ behavior cụ thể, gọi tên pain "
                "contradiction, rồi đặt đúng một WHY/open loop dẫn vào mechanism đã có source. "
                "Không thêm lời hứa giải pháp, neuroscience hoặc mechanism mới." % finding
                for finding in hook_findings
            )

    # Reviewer trả bản tái cấu trúc hoàn chỉnh + tag positions.
    # (PHẦN 5). Pipeline tự chèn <#x#> bằng code — không còn trông chờ model
    # copy lại 100% script, loại hẳn drift v7.
    revised = review.get("revised_draft_clean")
    if not isinstance(revised, str) or not revised.strip():
        raise ValueError("Reviewer thiếu revised_draft_clean (bản tái cấu trúc).")
    tts_ready = _build_tts_ready(review, revised)
    review["tts_ready"] = tts_ready
    # Scorecards are telemetry only. Older providers may still return them, so
    # normalize them when present, but never make their absence a run failure.
    score = review.get("score_report")
    if isinstance(score, dict):
        for key in ("retention_impact", "style_tone", "pacing_structure"):
            normalized = normalize_score_0_10(score.get(key))
            score[key] = normalized if normalized is not None else 0.0
    # Pipeline đếm lại bằng code — con số chính thức (rule v9 III.4: cấm ước lượng).
    verified_chars = non_whitespace_chars(revised)
    char_report = review.get("char_report") if isinstance(review.get("char_report"), dict) else {}
    char_report["verified_chars_by_code"] = verified_chars
    char_report["target_min_chars"] = target_min_chars_from_contract(contract)
    char_report["status"] = "ok" if verified_chars >= char_report["target_min_chars"] else "short"
    char_report["shortfall"] = max(0, char_report["target_min_chars"] - verified_chars)
    review["char_report"] = char_report

    if decision == "revise":
        reviewed_script = context.provider.apply_review(contract, plan, source_pack, draft, review)
    else:
        reviewed_script = draft

    # Provider APIs are stateless and cannot share a cross-vendor session ID.
    # Persisting this transcript makes the configured role sequence reproducible
    # on resume: writer draft -> reviewer findings -> editor revision.
    writer_session = {
        "strategy": "persisted_transcript",
        "writer_role": "writer",
        "reviewer_role": "reviewer",
        "editor_role": "editor",
        "decision": decision,
        "turns": [
            {"role": "writer", "type": "draft", "content": draft},
            {"role": "reviewer", "type": "review_findings", "content": review},
            {"role": "editor", "type": "revision" if decision == "revise" else "draft_preserved", "content": reviewed_script},
        ],
    }
    report_ref = context.store.put_json("review_report", "script/review-report.json", review, "review")
    session_ref = context.store.put_json("writer_session", "script/writer-session.json", writer_session, "review")
    script_ref = context.store.put_text("reviewed_script", "script/script-reviewed.txt", reviewed_script, "review")
    return StageResult([report_ref, session_ref, script_ref], {"review_decision": decision, "editor_revision": decision == "revise"})


def _audit_failure_reasons(round_result: dict) -> str:
    """Diễn giải chính xác gate nào của audit_passes đã chặn, cho error message.

    Trước đây stage chỉ báo "không vượt dual audit" nên phải đọc log model mới
    biết nguyên nhân.
    """
    reasons = []
    for name, audit in round_result.get("audits", {}).items():
        if audit_passes(audit):
            continue
        failed = []
        for flag in ("source_alignment", "outline_coverage", "title_alignment"):
            if not audit.get(flag):
                failed.append("%s=false" % flag)
        for field in ("unsupported_claims", "missing_outline_points"):
            values = audit.get(field) or []
            if values:
                failed.append("%s=%s" % (field, "; ".join(str(item) for item in values)))
        routing = audit.get("routing") or {}
        actual = "{provider}/{model}".format(
            provider=routing.get("provider", "unknown"),
            model=routing.get("model", "unknown"),
        )
        reasons.append("%s (%s) [%s]" % (name, actual, ", ".join(failed) if failed else "không rõ"))
    return " | ".join(reasons) if reasons else "không rõ"


def _remove_unsupported_audit_claims(script: str, *audits: dict) -> str:
    """Remove exact claims an auditor marked unsupported before the next audit.

    The editor is asked to rewrite first. This deterministic scrub is a last
    local safeguard for a recurring failure mode where it repeats the same
    unsupported causal sentence with softer wording. Matching tolerates the
    quote characters and spacing drift the auditor adds around a quoted claim,
    so a multi-clause 「…『…』…。」 finding still resolves to its script sentence.
    """
    def _norm(text: str) -> str:
        return re.sub(r"[\s、。！？!?『』「」\"'（）()・…]", "", str(text or ""))

    repaired = script
    for audit in audits:
        for item in (audit or {}).get("unsupported_claims") or []:
            if isinstance(item, dict):
                claim = item.get("claim") or item.get("text") or ""
            else:
                claim = item
            claim_core = _norm(claim)
            if len(claim_core) < 12:
                # Too short to match a sentence safely; skip rather than risk
                # deleting unrelated narration.
                continue
            # Split into sentences (keep the trailing punctuation) and drop the
            # first whose normalized form overlaps the claim core in either
            # direction. This survives quote/spacing differences.
            sentences = re.findall(r"[^。！？!?]*[。！？!?]", repaired)
            for sentence in sentences:
                sent_core = _norm(sentence)
                if not sent_core:
                    continue
                if claim_core in sent_core or (len(sent_core) >= 12 and sent_core in claim_core):
                    repaired = repaired.replace(sentence, "", 1)
                    break
            else:
                # Fallback: exact substring removal on the unquoted claim.
                stripped = str(claim).strip().strip("「」『』\"'")
                if stripped and stripped in repaired:
                    repaired = repaired.replace(stripped, "", 1)
    return re.sub(r"\n{3,}", "\n\n", repaired).strip()


def _finalize_source_audit_after_scrub(script: str, round_result: dict) -> tuple[str, bool, list[str]]:
    """Apply one bounded local cleanup when the last audit only flags exact claims.

    Auditor wording is nondeterministic, but an exact unsupported sentence is
    not. If every failing audit has no outline/title defect and only reports
    unsupported claims, removing those exact sentences is a deterministic
    source-boundary fix, not another model retry. Never use this path when an
    audit reports a missing supported point or another structural failure.
    """
    audits = list((round_result.get("audits") or {}).values())
    for audit in audits:
        if not audit.get("unsupported_claims"):
            continue
        if not audit.get("outline_coverage") or not audit.get("title_alignment"):
            return script, False, []
        if audit.get("missing_outline_points"):
            return script, False, []
        other_failures = [
            key for key in ("outline_coverage", "title_alignment")
            if not audit.get(key)
        ]
        if other_failures:
            return script, False, []
    cleaned = _remove_unsupported_audit_claims(script, *audits)
    if cleaned == script:
        return script, False, []
    # The exact-claim scrub above is intentionally the only mutation. The
    # caller performs the normal code-level source/policy checks with its
    # locked run context before accepting the result.
    removed = [
        str(item.get("claim") or item.get("text") or "").strip()
        for audit in audits
        for item in (audit.get("unsupported_claims") or [])
        if isinstance(item, dict) and str(item.get("claim") or item.get("text") or "").strip()
    ]
    return cleaned, True, removed


def _stored_writing_movements(context: RunContext) -> list[dict]:
    """Load writer-owned movement boundaries when this run was chunked.

    Paragraph boundaries are editorial choices and cannot safely be reconstructed
    after the fact. Persisted movement IDs let the source editor replace only a
    failing argument without silently summarising an entire long-form script.
    """
    try:
        payload = _json(context, "script_movements")
    except (KeyError, FileNotFoundError):
        return []
    rows = payload.get("movements") if isinstance(payload, dict) else []
    return [row for row in rows if isinstance(row, dict) and str(row.get("text") or "").strip()]


def _is_symbolic_long_form(contract: dict) -> bool:
    return (
        "symbolic long-form" in str((contract.get("format_lock") or {}).get("primary_format", "")).lower()
        and int(contract.get("target_char_min") or 0) >= 8000
    )


def _long_form_integrity_enabled(context: RunContext, contract: dict) -> bool:
    """Demo fixtures deliberately use concise narration and must remain runnable."""
    return _is_symbolic_long_form(contract) and not bool(getattr(context.provider, "is_demo_provider", False))


def _require_long_form_integrity(context: RunContext, contract: dict, script: str, baseline_chars: int, phase: str) -> None:
    """Prevent a targeted edit from turning a competitor-length script into a summary."""
    if not _long_form_integrity_enabled(context, contract):
        return
    actual = non_whitespace_chars(script)
    target_min = int(contract.get("target_char_min") or 0)
    floor = max(target_min, int(baseline_chars * 0.80))
    if actual < floor:
        raise ValueError(
            "%s làm vỡ long-form integrity: %d ký tự, cần ít nhất %d. "
            "Không chấp nhận repair rút 35-45 phút thành bản tóm tắt."
            % (phase, actual, floor)
        )


def _repair_failed_movements(context: RunContext, contract: dict, plan: dict, source_pack: dict, script: str, initial_audit: dict, initial_preflight: dict) -> tuple[str, list[dict]]:
    """Repair only movement-local source violations; never replace a full long script.

    Movement audits are independent of each other (same contract/source policy,
    own text), so they run concurrently; repairs for flagged movements run
    concurrently afterwards. Results are reassembled in original movement order.
    """
    movements = _stored_writing_movements(context)
    if len(movements) < 2:
        return "", []
    sections_by_id = {
        str(section.get("id")): section
        for section in plan.get("sections", [])
        if isinstance(section, dict)
    }

    def _local_screen(row: dict) -> tuple[dict, dict]:
        original = str(row["text"]).strip()
        movement_id = str(row.get("id") or "")
        local_audit = normalize_audit_report(
            context.provider.audit_script("auditor", contract, {**plan, "sections": [sections_by_id.get(movement_id, {})]}, source_pack, original),
            "auditor",
        )
        local_preflight = {
            "unsupported_claim_markers": unsupported_source_claims(original, source_pack),
            "unsupported_causal_capabilities": causal_capability_violations(original, source_pack),
            "policy_violations": policy_violations(original, _json(context, "claim_ledger")),
        }
        return local_audit, local_preflight

    screens = _run_provider_tasks_parallel([lambda row=row: _local_screen(row) for row in movements])

    def _repair_movement(row: dict, local_audit: dict, local_preflight: dict) -> str:
        original = str(row["text"]).strip()
        movement_id = str(row.get("id") or "")
        scoped_plan = {**plan, "sections": [sections_by_id.get(movement_id, {})]}
        result = context.provider.repair_script(
            contract,
            scoped_plan,
            source_pack,
            original,
            {
                "decision": "revise",
                "scope": "single_writing_movement",
                "movement_id": movement_id,
                "audit": local_audit,
                "preflight": local_preflight,
                "required_changes": [
                    "Chỉ sửa movement này; không viết lại các movement khác và không thêm kết luận mới.",
                    "Giữ psychological_job, new_information, state_advance và vị trí của movement trong plan.",
                    "Giữ ít nhất 80% và KHÔNG vượt quá 115% số ký tự của movement gốc; chỉ xóa/diễn giải lại phần vi phạm source, không thêm mở rộng hay filler.",
                ],
            },
        )
        replacement = str(result.get("final_script", "")).strip()
        if not replacement:
            raise ValueError("Movement repair %s trả script rỗng." % movement_id)
        original_chars = non_whitespace_chars(original)
        if non_whitespace_chars(replacement) < int(original_chars * 0.80):
            raise ValueError(
                "Movement repair %s bị collapse từ %d xuống %d ký tự; bỏ kết quả thay vì làm hỏng long-form."
                % (movement_id, original_chars, non_whitespace_chars(replacement))
            )
        # Upper bound: repair must not inflate a movement past the length cap.
        # A ballooning rewrite silently busts the ~55-minute duration ceiling,
        # so discard it and deterministically scrub only the exact flagged
        # sentences from the original movement instead.
        if non_whitespace_chars(replacement) > int(original_chars * 1.15):
            scrubbed_original = _remove_unsupported_audit_claims(original, local_audit)
            logger.warning(
                "Movement repair %s phình từ %d lên %d ký tự (>115%%); dùng scrub xoá-câu-chính-xác trên bản gốc để giữ cap độ dài.",
                movement_id, original_chars, non_whitespace_chars(replacement),
            )
            replacement = scrubbed_original.strip() or original
        return replacement

    repaired_rows: list[dict] = []
    repair_log: list[dict] = []
    pending_repairs = {}
    for row, (local_audit, local_preflight) in zip(movements, screens):
        requires_repair = not local_audit.get("source_alignment", True) or any(local_preflight.values())
        if requires_repair:
            pending_repairs[str(row.get("id") or "")] = (row, local_audit, local_preflight)
    if pending_repairs:
        repair_results = _run_provider_tasks_parallel([
            lambda item=item: _repair_movement(*item) for item in pending_repairs.values()
        ])
        replacements = {movement_id: replacement for movement_id, replacement in zip(pending_repairs.keys(), repair_results)}
    else:
        replacements = {}
    for row_index, row in enumerate(movements):
        original = str(row["text"]).strip()
        movement_id = str(row.get("id") or "")
        local_audit, _local_preflight = screens[row_index]
        if movement_id in replacements:
            replacement = replacements[movement_id]
            requires_repair = True
        else:
            replacement = original
            requires_repair = False
        repaired_rows.append({**row, "text": replacement})
        repair_log.append({"movement_id": movement_id, "repaired": requires_repair, "source_alignment": local_audit.get("source_alignment", True)})
    return "\n\n".join(str(row["text"]).strip() for row in repaired_rows), repair_log


def _consistency(context: RunContext, initial_script: str | None = None) -> StageResult:
    contract = _json(context, "script_contract")
    plan = _json(context, "planning")
    source_pack = _source_policy(context)
    claim_ledger = _json(context, "claim_ledger")
    script = initial_script if initial_script is not None else _text(context, "reviewed_script")
    brief = _json(context, "psychology_brief")

    def preflight(value: str) -> dict:
        structure_issues, _mechanisms, _covered = _psychology_structure_issues(value, contract, plan, brief)
        return {
            "unsupported_claim_markers": unsupported_source_claims(value, source_pack),
            "unsupported_causal_capabilities": causal_capability_violations(value, source_pack),
            "policy_violations": policy_violations(value, claim_ledger),
            "structure_issues": structure_issues,
        }

    # unsupported_causal_capabilities is a deterministic regex heuristic that
    # cannot tell a proven-fact claim from a hedged interpretive one. For this
    # Jungian/interpretive channel the LLM auditor (SYMBOLIC INTERPRETATION RULE)
    # is the source-alignment authority, so this key is advisory only. The literal
    # neuroscience/childhood tokens (unsupported_claim_markers), forbidden-term
    # policy, and structure remain deterministic hard gates.
    _ADVISORY_PREFLIGHT_KEYS = ("unsupported_causal_capabilities",)

    def _hard_preflight_fail(pf: dict) -> bool:
        return any(v for k, v in pf.items() if k not in _ADVISORY_PREFLIGHT_KEYS)

    def _preflight_advisories(pf: dict) -> list[str]:
        notes: list[str] = []
        for key in _ADVISORY_PREFLIGHT_KEYS:
            values = pf.get(key) or []
            if values:
                notes.append("%s (advisory): %s" % (key, ", ".join(str(v) for v in values)))
        return notes

    def _apply_deterministic_title_gate(audit: dict, current_script: str) -> None:
        # The LLM's bare title_alignment boolean is subjective and cannot block
        # production alone (same policy as audit_passes' scorecard exclusion).
        # Use the inspectable deterministic anchor check ONLY to RESCUE a false
        # verdict: if the model says the hook misses the title but a contract
        # opening_anchor actually appears in the opening, accept it. Never turn a
        # model "true" into a failure — this only relaxes, never tightens.
        if audit.get("title_alignment") is True:
            return
        verdict = title_hook_alignment(current_script, contract)
        if bool(verdict.get("passed", True)):
            logger.warning(
                "Auditor title_alignment=false bị override bởi deterministic title_hook_alignment "
                "(matched anchors=%s). Bare boolean chủ quan không tự chặn run.",
                verdict.get("matched_anchors"),
            )
            audit["title_alignment"] = True

    initial_preflight = preflight(script)
    initial_audit = normalize_audit_report(
        context.provider.audit_script("auditor", contract, plan, source_pack, script), "auditor"
    )
    _apply_deterministic_title_gate(initial_audit, script)
    needs_repair = (
        not audit_passes(initial_audit)
        or _hard_preflight_fail(initial_preflight)
    )
    rounds = [{
        "round": 1,
        "passed": not needs_repair,
        "audits": {"auditor": initial_audit},
        "preflight": initial_preflight,
    }]

    if needs_repair:
        baseline_chars = non_whitespace_chars(script)
        movement_repaired, movement_log = _repair_failed_movements(
            context, contract, plan, source_pack, script, initial_audit, initial_preflight
        )
        if movement_repaired:
            script = movement_repaired
        else:
            repaired = context.provider.repair_script(
                contract,
                plan,
                source_pack,
                script,
                {
                    "decision": "revise",
                    "audit": initial_audit,
                    "preflight": initial_preflight,
                    "required_changes": [
                        "Đây là lượt repair duy nhất. Sửa đúng finding cụ thể, không rewrite toàn bộ script hoặc thêm mechanism mới.",
                        "Giữ nguyên số movement, thứ tự revelation, opening, practical shift và quiet landing; không được tóm tắt hoặc bỏ movement.",
                        "Giữ trong khoảng 80%-110% số ký tự gốc. KHÔNG kéo dài script: chỉ xóa/diễn giải lại phần vi phạm source. Long-form 35-45 phút, tuyệt đối không vượt 55 phút.",
                        "Phân biệt 2 loại finding: (1) claim KHOA HỌC/thần kinh nói như sự thật → XÓA hẳn. (2) diễn giải Jung/shadow viết ở dạng KHẲNG ĐỊNH → giữ ý nhưng đổi sang thể phỏng đoán ('〜と読めるかもしれません', '〜ように感じられることがあります', '〜場合があります'), KHÔNG xóa. Ưu tiên áp dụng đúng gợi ý 'repair' trong từng unsupported_claim của audit.",
                    ],
                },
            )
            script = str(repaired.get("final_script", "")).strip()
            # Upper bound: a whole-script repair must not inflate past the cap.
            if script and non_whitespace_chars(script) > int(baseline_chars * 1.10):
                scrubbed_whole = _remove_unsupported_audit_claims(
                    initial_script if initial_script is not None else _text(context, "reviewed_script"),
                    initial_audit,
                )
                logger.warning(
                    "Whole-script repair phình từ %d lên %d ký tự (>110%%); dùng scrub xoá-câu-chính-xác trên bản gốc để giữ cap độ dài.",
                    baseline_chars, non_whitespace_chars(script),
                )
                if scrubbed_whole.strip():
                    script = scrubbed_whole.strip()
            movement_log = [{"movement_id": "whole_script_legacy", "repaired": True}]
        if not script:
            raise ValueError("Targeted repair trả script rỗng.")
        _require_long_form_integrity(context, contract, script, baseline_chars, "Consistency repair")
        final_preflight = preflight(script)
        final_audit = normalize_audit_report(
            context.provider.audit_script("auditor", contract, plan, source_pack, script), "auditor"
        )
        _apply_deterministic_title_gate(final_audit, script)
        final_passed = audit_passes(final_audit) and not _hard_preflight_fail(final_preflight)
        rounds.append({
            "round": 2,
            "passed": final_passed,
            "audits": {"auditor": final_audit},
            "preflight": final_preflight,
            "movement_repairs": movement_log,
        })

    if not rounds[-1]["passed"]:
        # Deterministic last resort: if the only remaining defect is a set of
        # exact unsupported sentences (no outline/title/missing-point failure),
        # remove those exact sentences instead of failing the whole run. This is
        # a bounded source-tightening scrub, not another model rewrite.
        scrubbed, changed, removed = _finalize_source_audit_after_scrub(script, rounds[-1])
        if changed:
            scrub_preflight = preflight(scrubbed)
            if not _hard_preflight_fail(scrub_preflight):
                try:
                    _require_long_form_integrity(context, contract, scrubbed, baseline_chars, "Consistency scrub")
                    script = scrubbed
                    rounds.append({
                        "round": len(rounds) + 1,
                        "passed": True,
                        "audits": {},
                        "preflight": scrub_preflight,
                        "deterministic_claim_scrub": removed,
                    })
                except ValueError:
                    pass
    if not rounds[-1]["passed"]:
        raise ValueError(
            "Script không vượt source audit sau một lần repair có mục tiêu. Chi tiết: %s"
            % _audit_failure_reasons(rounds[-1])
        )
    causal_advisories = _preflight_advisories(rounds[-1].get("preflight") or {})
    for note in causal_advisories:
        logger.warning("Preflight advisory (không blocking) | %s", note)
    # issues[] không còn là fail condition (xem audit_passes) nên phải nổi lên
    # warning, tránh mất tín hiệu chất lượng của auditor.
    audit_notes = [
        f"{name}: {issue}"
        for name, audit in (rounds[-1].get("audits") or {}).items()
        for issue in audit.get("issues") or []
    ]
    for note in audit_notes:
        logger.warning("Audit note (không blocking) | %s", note)
    audits_ref = context.store.put_json("resource_audits", "script/audits.json", {"rounds": rounds}, "consistency")
    script_ref = context.store.put_text("final_script", "script/script.txt", script, "consistency")
    return StageResult(
        [audits_ref, script_ref],
        {"audit_rounds": len(rounds)},
        warnings=audit_notes + causal_advisories,
    )


def _put_script_qa(context: RunContext, script: str, producer: str) -> tuple:
    """Validate + ghi script_qa/pause_map cho script hiện tại.

    Dùng chung cho stage script_qa (validate bản từ consistency) và
    structure_check (re-gate bản đã repair — tránh QA stale trên bản pre-repair).
    """
    contract = _json(context, "script_contract")
    qa = validate_japanese_script(
        script,
        target_min_chars=int(contract["target_char_min"]),
        target_max_chars=int(contract["target_char_max"]),
    )
    if not qa["passed"]:
        raise ValueError("; ".join(qa["issues"]))
    pauses = {
        "format": "non_spoken_pause_cues",
        "usage": "Tham khảo nhịp đọc/dựng; minimax-prompt.txt mang tag <#x#> (rule v9) — script.txt luôn sạch.",
        "cues": build_pause_map(script),
    }
    qa_ref = context.store.put_json("script_qa", "script/script_qa.json", qa, producer)
    pause_ref = context.store.put_json("pause_map", "script/pause-map.json", pauses, producer)
    return qa_ref, pause_ref, qa, pauses


def _duration_guideline_warning(context: RunContext, qa: dict) -> str | None:
    """Keep duration visible without turning it into a filler-generating gate."""
    contract = _json(context, "script_contract")
    recommended_chars = target_min_chars_from_contract(contract)
    actual_chars = int(qa.get("non_whitespace_chars") or 0)
    if actual_chars >= recommended_chars:
        return None
    return (
        "UNDER_TARGET_DURATION: script có %d ký tự, ước tính %d-%d giây; ngắn hơn guideline tối thiểu "
        "%s phút (~%d ký tự). Không tự bơm filler hoặc retry: chỉ cân nhắc một editor pass khi planning/source "
        "còn một implication riêng biệt, có source support chưa được dùng."
        % (
            actual_chars,
            int(qa.get("estimated_duration_min_seconds") or 0),
            int(qa.get("estimated_duration_max_seconds") or 0),
            target_duration_min_from_contract(contract),
            recommended_chars,
        )
    )


def _script_qa(context: RunContext) -> StageResult:
    script = _text(context, "final_script")
    script, removed_citation_tokens = scrub_source_citation_tokens(script)
    if removed_citation_tokens:
        logger.warning(
            "Script QA removed source citation tokens from narration: %s",
            ", ".join(removed_citation_tokens),
        )
    contract = _json(context, "script_contract")
    qa = validate_japanese_script(
        script,
        target_min_chars=int(contract["target_char_min"]),
        target_max_chars=int(contract["target_char_max"]),
    )
    # The lower bound protects against an accidental summary after repair. The
    # upper bound remains a pacing guideline: a 1-2% sentence-safe overshoot is
    # preferable to cutting a valid final insight mid-movement.
    if _long_form_integrity_enabled(context, contract) and qa["non_whitespace_chars"] < qa["target_min_chars"]:
        raise ValueError(
            "Long-form duration integrity failure: %d ký tự, cần tối thiểu %d. "
            "Không tiếp tục sang thumbnail/hình với bản tóm tắt; hãy sửa movement/source bị thiếu thay vì bơm filler."
            % (qa["non_whitespace_chars"], qa["target_min_chars"])
        )
    if not qa["passed"]:
        repairable = any(
            issue.startswith("Foreign tokens chưa whitelist")
            or issue.startswith("Tỷ lệ ký tự tiếng Nhật")
            for issue in qa["issues"]
        )
        if not repairable:
            raise ValueError("; ".join(qa["issues"]))
        repaired = context.provider.repair_script(
            _json(context, "script_contract"),
            _json(context, "planning"),
            _source_policy(context),
            script,
            {
                "decision": "revise",
                "qa_issues": qa["issues"],
                "foreign_tokens": qa["foreign_tokens"],
                "required_changes": [
                    "Không kéo dài script để đạt quota ký tự; chỉ sửa đúng lỗi QA và giữ information density.",
                    "Chuyển tên tác giả/tựa nghiên cứu tiếng Anh sang cách viết tiếng Nhật hoặc bỏ citation khỏi narration. Giữ citation đầy đủ ở source_note/description, không đọc nguyên văn tiếng Anh trong script.",
                ],
            },
        )
        script = str(repaired.get("final_script", "")).strip()
        if not script:
            raise ValueError("Repair script_qa trả script rỗng.")
        script, removed_after_repair = scrub_source_citation_tokens(script)
        removed_citation_tokens = sorted(set(removed_citation_tokens + removed_after_repair))
        final_ref = context.store.put_text("final_script", "script/script.txt", script, "script_qa")
        qa_ref, pause_ref, qa, pauses = _put_script_qa(context, script, "script_qa")
        if _long_form_integrity_enabled(context, contract) and qa["non_whitespace_chars"] < qa["target_min_chars"]:
            raise ValueError(
                "Script QA repair làm vỡ long-form duration integrity: %d ký tự, cần tối thiểu %d."
                % (qa["non_whitespace_chars"], qa["target_min_chars"])
            )
        warnings = [warning for warning in (_duration_guideline_warning(context, qa),) if warning]
        return StageResult(
            [final_ref, qa_ref, pause_ref],
            {**qa, "pause_cues": len(pauses["cues"]), "source_citation_tokens_removed": removed_citation_tokens},
            warnings=warnings,
        )
    qa_ref, pause_ref, qa, pauses = _put_script_qa(context, script, "script_qa")
    artifacts = [qa_ref, pause_ref]
    if removed_citation_tokens:
        artifacts.insert(0, context.store.put_text("final_script", "script/script.txt", script, "script_qa"))
    warnings = [warning for warning in (_duration_guideline_warning(context, qa),) if warning]
    return StageResult(
        artifacts,
        {**qa, "pause_cues": len(pauses["cues"]), "source_citation_tokens_removed": removed_citation_tokens},
        warnings=warnings,
    )


def _mechanism_is_covered(script: str, mechanism: dict) -> bool:
    if mechanism_is_covered(script, mechanism):
        return True
    """Accept a natural explanation instead of requiring an editorial label."""
    name = str(mechanism.get("name", "")).strip()
    if not name:
        return False
    if name in script:
        return True

    # Mechanism names are editorial metadata and may be Vietnamese/English
    # while the spoken script is Japanese. Match source-bound explanatory
    # terms from the mechanism fields instead of demanding that internal label.
    japanese_runs = re.findall(r"[ぁ-んァ-ヶー一-龯]{2,}", "\n".join(
        str(mechanism.get(key, ""))
        for key in ("behavior_explained", "why", "inner_process")
    ))
    japanese_terms = {
        run[start:start + width]
        for run in japanese_runs
        for width in (2, 3, 4)
        for start in range(max(0, len(run) - width + 1))
    }
    stop_terms = {"する", "ため", "こと", "よう", "それ", "この", "その", "行動", "状態", "可能性", "必要", "一部"}
    matched_terms = {term for term in japanese_terms if term not in stop_terms and term in script}
    if len(matched_terms) >= 2:
        return True

    families = []
    if any(term in name for term in ("状況", "手がかり", "文脈", "環境")):
        families.append(("context", ("状況", "手がかり", "環境", "合図")))
    if any(term in name for term in ("習慣", "反復", "ルーティン")):
        families.append(("repetition", ("習慣", "反復", "繰り返", "いつもの")))
    if any(term in name for term in ("反応", "起動", "自動")):
        families.append(("response", ("反応", "起動", "行動", "始まり")))

    # One generic word is not enough. The script must express at least two
    # distinct parts of the named mechanism in natural Japanese.
    hits = sum(1 for _family, terms in families if any(term in script for term in terms))
    return len(families) >= 2 and hits >= 2


def _mechanism_has_script_language_evidence(mechanism: dict) -> bool:
    """Only enforce lexical coverage when mechanism metadata is Japanese too."""
    text = " ".join(str(mechanism.get(key, "")) for key in (
        "name", "behavior_explained", "why", "inner_process",
    ))
    return bool(re.search(r"[ぁ-んァ-ヶー一-龯]", text))


def _plan_has_self_understanding_landing(planning: dict) -> bool:
    """Accept a combined practical-shift/quiet-landing movement.

    Symbolic long-form permits 5-7 movements, so a separate section label is
    not required when the final movement clearly lands in reflection rather
    than another tip list.
    """
    sections = planning.get("sections", [])
    if any(section.get("segment_function") == "insight_landing" for section in sections):
        return True
    if not sections or not planning.get("planning_quality_gate", {}).get("ending_creates_self_understanding"):
        return False
    final = sections[-1]
    text = " ".join(str(final.get(key, "")) for key in (
        "psychological_job", "new_information", "viewer_question_answered", "state_advance", "so_what_next",
    ))
    return any(marker in text for marker in ("自分", "観察", "理解", "見", "責め", "人格"))


def _psychology_structure_issues(script: str, contract: dict, planning: dict, brief: dict) -> tuple[list[str], list[str], list[str]]:
    """Check source/mechanism integrity without policing symbolic narration.

    The new editorial form deliberately permits bounded scenes and recurring
    symbols. Scene-marker counts therefore remain telemetry in the format
    report, not a reason to erase a valid narrative from the final script.
    """
    issues: list[str] = []
    mechanism_items = [item for item in brief.get("selected_mechanisms", []) if isinstance(item, dict)]
    mechanisms = [str(item.get("name", "")) for item in mechanism_items]
    covered = [
        name for item, name in zip(mechanism_items, mechanisms)
        if not _mechanism_has_script_language_evidence(item) or _mechanism_is_covered(script, item)
    ]
    missing = [name for name in mechanisms if name not in covered]
    if missing:
        issues.append(
            "selected psychological mechanism is not named or explained in script: "
            + ", ".join(missing)
        )
    if not contract.get("core_psychological_question"):
        issues.append("missing core psychological question in contract")
    if not contract.get("main_tension"):
        issues.append("missing main psychological tension in contract")
    if not _plan_has_self_understanding_landing(planning):
        issues.append("planning lacks self-understanding insight landing")
    if brief.get("origin_status") in {"unsupported", "irrelevant", "skip"}:
        if any(marker in script for marker in ("幼少期", "子どもの頃", "生まれつき")):
            issues.append("origin/childhood explanation used without brief support")
    return issues, mechanisms, covered


def _structure_check(context: RunContext) -> StageResult:
    """Deterministic post-repair gate; it never starts another model rewrite."""
    script = _text(context, "final_script")
    input_script_sha = hashlib.sha256(script.encode("utf-8")).hexdigest()

    contract = _json(context, "script_contract")
    planning = _json(context, "planning")
    brief = _json(context, "psychology_brief")
    issues, mechanisms, covered = _psychology_structure_issues(script, contract, planning, brief)
    repair_rounds = []

    score = max(0, 100 - len(issues) * 25)
    report = {
        "structure_score": score,
        "status": "pass" if not issues else "fail",
        "issues": issues,
        "warnings": [],
        "psychology_route": brief.get("route"),
        "mechanisms_expected": mechanisms,
        "mechanisms_explicitly_covered": covered,
        "story_findings": anti_story_findings(script),
        "repair_rounds": repair_rounds,
        "input_script_sha": input_script_sha,
        "script_sha": hashlib.sha256(script.encode("utf-8")).hexdigest(),
        "structure_policy_version": STRUCTURE_POLICY_VERSION,
    }
    ref = context.store.put_json("structure_check", "script/structure-check.json", report, "structure_check")
    if issues:
        raise ValueError("Psychology-first structure check failed: %s" % "; ".join(issues))

    return StageResult(
        [ref],
        {"structure_score": score, "issues_count": 0, "repair_rounds": 0},
    )


def _psychology_format_check(context: RunContext) -> StageResult:
    """Plan v2 §13–15 (Sprint 4–5): metric deterministic cho psychology-first format.

    Chạy SAU structure_check (lệch sơ đồ §17 có chủ đích): structure_check được
    phép rewrite final_script khi repair, nên đo sau mới mô tả đúng script cuối
    cùng được TTS/publish. Stage thuần code (0 LLM call) — Demo không tốn gì.

    NON-BLOCKING: gate chỉ là GỢI Ý (plan §13 — "threshold nên được calibration
    sau 10–20 video thực tế"). Mọi thiếu hụt thành warning; structure_check vẫn
    là lớp blocking duy nhất cho anti-story/mechanism. Metrics + derived scores
    được log để Sprint 6 ghép với intro_retention/average_view_duration.
    """
    script = _text(context, "final_script")
    brief = _json(context, "psychology_brief")
    contract = _json(context, "script_contract")
    metrics = psychology_format_metrics(script, brief, contract)
    gate_passed, gate_failed = format_gate_verdict(metrics)
    selfhelp_findings = generic_selfhelp_findings(script)

    warnings = []
    if gate_failed:
        warnings.append(
            "psychology_format_check gate gợi ý chưa đạt: %s (thresholds chưa "
            "calibrate — không block; xem SUGGESTED_FORMAT_GATE)." % ", ".join(gate_failed)
        )
    if selfhelp_findings:
        warnings.append(
            "generic self-help flattery markers (plan §15): %s — nên thay bằng "
            "mechanism explanation." % ", ".join(selfhelp_findings)
        )
    if metrics["raw"]["identity_token_total"] == 0:
        warnings.append(
            "psychological_identity rỗng hoặc không có token nội dung — "
            "psychological_identity metric = 0, cần kiểm tra brief."
        )

    derived_scores = {
        "format_score": round(
            (metrics["psychological_identity"] + metrics["behavioral_density"] + metrics["insight_density"]) / 3, 1
        ),
        "mechanism_score": metrics["mechanism_depth"],
        "narrative_score": round(10.0 - metrics["narrative_contamination"], 1),
    }
    report = {
        "schema": "psychology_format_check",
        "plan_reference": "psychology_first_content_engine_v2_plan.md §13–15 (Sprint 4–5)",
        "blocking": False,
        "position_note": (
            "Chạy sau structure_check (khác sơ đồ §17): structure_check có thể "
            "rewrite final_script khi repair — đo sau để metric mô tả script cuối cùng."
        ),
        "metrics": {key: value for key, value in metrics.items() if key != "raw"},
        "raw": metrics["raw"],
        "derived_scores": derived_scores,
        "suggested_gate": {
            "thresholds": dict(SUGGESTED_FORMAT_GATE),
            "passed": gate_passed,
            "failed": gate_failed,
            "note": (
                "Gợi ý chưa calibrate (plan §13) — stage non-blocking. Calibrate "
                "thresholds sau 10–20 video bằng calibration.intro_retention/"
                "average_view_duration (Sprint 6)."
            ),
        },
        "generic_selfhelp_findings": selfhelp_findings,
        "calibration": {
            "intro_retention": None,
            "average_view_duration": None,
            "how": "Điền sau publish từ YouTube Analytics rồi đối chiếu với metrics/derived_scores (Sprint 6).",
        },
        "script_sha": hashlib.sha256(script.encode("utf-8")).hexdigest(),
    }
    ref = context.store.put_json(
        "psychology_format_check", "script/psychology-format-check.json", report, "psychology_format_check"
    )
    stage_metrics = {
        **{key: value for key, value in metrics.items() if key != "raw"},
        **derived_scores,
        "format_gate_passed": gate_passed,
    }
    return StageResult([ref], stage_metrics, warnings=warnings)


def _translate_script_vi(context: RunContext) -> StageResult:
    """Vietnamese manager-QA translation; never replaces Japanese final script.

    This is a reviewer convenience artifact, not a build resource. A provider
    timeout or transient failure here must not sink an otherwise complete
    resource pack, so the stage degrades to a placeholder plus a warning.
    """
    try:
        translated = context.provider.translate_to_vietnamese(_text(context, "final_script"))
    except Exception as exc:  # noqa: BLE001 - QA aid only, must not fail the run
        logger.warning("translate_script_vi degraded (non-blocking): %s", exc)
        placeholder = "[translate_script_vi unavailable: %s]\n" % exc
        ref = context.store.put_text("script_vi", "script/script-vi.txt", placeholder, "translate_script_vi")
        return StageResult([ref], {"vi_chars": 0, "translation_available": False}, ["Bản dịch VI QA bị bỏ qua (provider lỗi/timeout) — không ảnh hưởng tài nguyên dựng."])
    ref = context.store.put_text("script_vi", "script/script-vi.txt", translated, "translate_script_vi")
    return StageResult([ref], {"vi_chars": len(translated), "translation_available": True})


def _sections(context: RunContext) -> StageResult:
    """Derive visual sections and independent <=5k TTS inputs from final script."""
    script = _text(context, "final_script")
    planning = _json(context, "planning")
    section_count = len([s for s in planning.get("sections", []) if s.get("id")])
    if section_count < 1:
        raise ValueError("planning.json thiếu sections — không xác định được số section.")
    cpm_min = MINIMAX_PROFILE["reference_cpm_min"]
    cpm_max = MINIMAX_PROFILE["reference_cpm_max"]
    sections, policy = split_script_sections(script, section_count, cpm_min=cpm_min, cpm_max=cpm_max)
    rows = [
        {"index": sec.index, "id": sec.id, "chars": sec.chars, "file": sec.file, "text": sec.text}
        for sec in sections
    ]
    # minimax-prompt: ưu tiên tts_ready từ reviewer nếu khớp 100% final script;
    # ngược lại chèn tag <#x#> deterministic theo mốc section (strip tags == script).
    review_report = _json(context, "review_report")
    tts_ready = review_report.get("tts_ready", "") if isinstance(review_report, dict) else ""
    warnings = []
    if tts_ready and normalize_text(strip_minimax_tags(tts_ready)) == normalize_text(script):
        minimax_prompt = tts_ready
        prompt_source = "review_tts_ready"
    else:
        if tts_ready:
            warnings.append(
                "tts_ready của reviewer lệch final_script (editor đã hoàn thiện) — "
                "đã chèn tag <#x#> deterministic theo mốc section."
            )
        minimax_prompt = insert_pause_tags(script, sections)
        prompt_source = "deterministic_sections"
    if normalize_text(strip_minimax_tags(minimax_prompt)) != normalize_text(script):
        raise ValueError("minimax-prompt không khớp script sau khi bỏ tag <#x#>.")
    payload = {
        "tts_profile": MINIMAX_PROFILE,
        "section_policy": policy,
        "sections": rows,
        "total_chars": sum(row["chars"] for row in rows),
        "round_trip_passed": "".join(sec.text for sec in sections) == script,
        "pause_policy": {
            "format": "minimax_t2a_tag",
            "syntax": "<#x#>",
            "between_sections": PAUSE_BETWEEN_SECTIONS,
            "before_outro": PAUSE_BEFORE_OUTRO,
            "paragraph_break": PAUSE_PARAGRAPH_BREAK,
            "minimax_prompt_source": prompt_source,
        },
    }
    sections_ref = context.store.put_json("sections", "script/sections.json", payload, "sections")
    prompt_ref = context.store.put_text("minimax_prompt", "script/minimax-prompt.txt", minimax_prompt, "sections")
    # TTS providers commonly cap a request at 5,000 characters. These chunks
    # are intentionally separate from planning sections: changing their count
    # must never break beat-to-section timing in the video builder.
    tts_chunks = split_tts_chunks(script, max_chars=4800)
    tts_dir = context.store.root / "script/audio-chunks"
    if tts_dir.is_dir():
        shutil.rmtree(tts_dir)
    tts_refs = []
    manifest_rows = []
    for chunk in tts_chunks:
        relative_path = "script/audio-chunks/" + chunk.file
        tts_refs.append(context.store.put_text("tts_chunk_%03d" % chunk.index, relative_path, chunk.text, "sections"))
        manifest_rows.append({
            "id": chunk.id,
            "index": chunk.index,
            "file": chunk.file,
            "chars": chunk.chars,
            "path": relative_path,
            "audio_output": "audio/chunks/%03d.mp3" % chunk.index,
        })
    tts_manifest = {
        "version": 1,
        "provider_character_limit": 5000,
        "chunk_character_limit": 4800,
        "source": "script/script.txt",
        "round_trip_passed": "".join(chunk.text for chunk in tts_chunks) == script,
        "chunks": manifest_rows,
        "merge_output": "audio/narration-merged.mp3",
    }
    tts_manifest_ref = context.store.put_json("tts_chunks", "script/audio-chunks/manifest.json", tts_manifest, "sections")
    # Remove retired pre-v4 chunk paths so old manual input is never mistaken
    # for the current final narration.
    chunk_dir = context.store.root / "script/chunks"
    if chunk_dir.is_dir():
        shutil.rmtree(chunk_dir)
    (context.store.root / "script/chunk-manifest.json").unlink(missing_ok=True)
    return StageResult(
        [sections_ref, prompt_ref, tts_manifest_ref, *tts_refs],
        {"sections": len(rows), "tts_chunks": len(tts_chunks), "total_chars": payload["total_chars"]},
        warnings,
    )


def _thumbnail(context: RunContext) -> StageResult:
    contract = _json(context, "script_contract")
    value = context.provider.create_thumbnail(contract, _text(context, "final_script"), competitor_inject_text())
    normalize_thumbnail_prompt(value)
    qa = validate_thumbnail(value, contract["chosen_title"])
    if qa.get("warnings"):
        logger.warning(
            "Thumbnail packaging warnings: %s",
            " | ".join(str(item) for item in qa["warnings"]),
        )
    if not qa["passed"]:
        raise ValueError("; ".join(qa["issues"]))
    contract_ref = context.store.put_json("thumbnail_contract", "thumbnail/contract.json", {**value, "tv_readability_round1": qa}, "thumbnail_contract")
    prompt_ref = context.store.put_text("thumbnail_prompt", "thumbnail/thumbnail-prompt.txt", value["image_prompt"] + "\n\nNegative: " + value["negative_prompt"] + "\n", "thumbnail_contract")
    text_prompt_ref = context.store.put_text(
        "thumbnail_prompt_text",
        "thumbnail/thumbnail-prompt-text.txt",
        baked_text_thumbnail_prompt(value, contract["chosen_title"]) + "\n",
        "thumbnail_contract",
    )
    overlay_ref = context.store.put_json("thumbnail_overlay", "thumbnail/overlay-spec.json", value["overlay_spec"], "thumbnail_contract")
    checklist_ref = context.store.put_text("thumbnail_checklist", "thumbnail/manual-checklist.md", "# Thumbnail manual checklist\n\n- Đọc `click_hypothesis` và `hook_alignment` trong thumbnail/contract.json trước khi edit. Thumbnail phải hứa đúng behavior/contradiction mà cold open trả trong 20 giây đầu.\n- `thumbnail-prompt.txt`: gen ảnh nền không chữ để ghép overlay thủ công.\n- `thumbnail-prompt-text.txt`: phương án AI gen sẵn đúng headline Nhật trong `thumbnail_text`; kiểm tra chính tả trên ảnh trước khi dùng.\n- Dùng visual anchor `video-build/images/IMG-01.png` nếu provider hỗ trợ ảnh tham chiếu.\n- Nếu provider không hỗ trợ reference image, giữ nguyên CHARACTER_BIBLE và không tạo mascot mới.\n- Chỉ một nhân vật/focal action, một visual conflict, một warm accent có chủ đích; không collage, hard split hay badge urgency giả.\n- Tạo preview 128×72 và squint test trên ảnh thật: PENDING_USER.\n- Nhân vật là học giả Nhật hư cấu; không tái tạo khuôn mặt/người thật (likeness/privacy gate).\n- Khai báo Altered/Synthetic Content trong YouTube Studio cho ảnh realistic AI (xem privacy/privacy.md).\n", "thumbnail_contract")
    return StageResult([contract_ref, prompt_ref, text_prompt_ref, overlay_ref, checklist_ref], qa)


def _image_strategy(context: RunContext) -> StageResult:
    contract = _json(context, "script_contract")
    plan = _json(context, "planning")
    # Visual coverage must follow the finished narration, never the broad
    # editorial duration range in the contract. Audio timing will refine this
    # later during video build.
    script_qa = _json(context, "script_qa")
    actual_duration = round((
        int(script_qa["estimated_duration_min_seconds"])
        + int(script_qa["estimated_duration_max_seconds"])
    ) / 2)
    visual_contract = {
        **contract,
        "visual_duration_seconds": actual_duration,
        "visual_duration_source": "script_qa_estimate",
    }
    value = context.provider.create_image_strategy(visual_contract, plan, _json(context, "thumbnail_contract"))
    validate_image_strategy(value, visual_contract, plan)
    for beat in value["visual_beats"]:
        beat.pop("time", None)
    value["timeline_policy"] = {
        "owner": "deterministic_storyboard_builder",
        "source": "script_qa_then_audio_build",
        "model_time_accepted": False,
    }
    ref = context.store.put_json("image_strategy", "visuals/strategy.json", value, "image_strategy")
    return StageResult(
        [ref],
        {
            "unique_images": value["estimated_unique_images"],
            "visual_events": value["estimated_total_visual_events"],
            **value["density_targets"],
        },
        ["DRAFT_TIMING: chưa có audio thật."],
    )


def _image_prompts(context: RunContext) -> StageResult:
    strategy = _json(context, "image_strategy")
    # Recompute dynamic image IDs/counts from beats before asking the provider.
    # This also repairs older checkpoints whose strategy only had numeric estimates.
    script_qa = _json(context, "script_qa")
    visual_contract = {
        **_json(context, "script_contract"),
        "visual_duration_seconds": round((
            int(script_qa["estimated_duration_min_seconds"])
            + int(script_qa["estimated_duration_max_seconds"])
        ) / 2),
        "visual_duration_source": "script_qa_estimate",
    }
    validate_image_strategy(strategy, visual_contract, _json(context, "planning"))
    value = context.provider.create_image_prompts(strategy, visual_contract)
    normalize_image_prompts(
        value,
        strategy,
        duration_seconds=int(visual_contract["visual_duration_seconds"]),
        sections=_json(context, "sections"),
    )
    qa = validate_prompt_pack(value, strategy, require_timing=True)
    if not qa["passed"]:
        raise ValueError("; ".join(qa["issues"][:10]))
    # Chọn ảnh NÊN gen image-to-video (heuristic thuần — không gọi model) và
    # đánh dấu trước khi put_json để prompt-pack.json mang field video_selected.
    selected = select_video_candidates(
        value["images"], value["storyboard"], strategy.get("visual_beats"))
    selected_set = set(selected)
    for image in value["images"]:
        image["video_selected"] = image.get("image_id") in selected_set
    prompt_dir = context.store.root / "visuals/prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    for stale_batch in prompt_dir.glob("prompts-batch-*.txt"):
        stale_batch.unlink()
    images = value["images"]
    refs = []
    merged = "\n\n".join(row["prompt"].replace("\n", " ").strip() for row in images) + "\n"
    refs.append(context.store.put_text("image_prompts_all", "visuals/prompts/prompts-ALL.txt", merged, "image_prompts"))
    refs.append(context.store.put_json("storyboard", "visuals/storyboard.json", value["storyboard"], "image_prompts"))
    refs.append(context.store.put_json("image_prompt_pack", "visuals/prompt-pack.json", value, "image_prompts"))
    refs.append(context.store.put_json("image_prompt_qa", "visuals/prompt-qa.json", qa, "image_prompts"))
    # prompts-video.txt: danh sách ảnh NÊN gen image-to-video (clip) — motion
    # hint lấy từ event storyboard đầu tiên của ảnh; user gen clip từ chính ảnh
    # đã gen rồi bỏ vào video-build/clips/ (engine ưu tiên clip, thiếu → ảnh).
    lines = [
        "# AUTO-GENERATED bởi stage image_prompts — ảnh NÊN gen image-to-video (clip).",
        "# Mỗi dòng: IMG-xx | <motion gợi ý> — gen clip TỪ CHÍNH ảnh đã gen (image-to-video),",
        "# rồi bỏ vào video-build/clips/ với tên IMG-xx.mp4 → engine ưu tiên clip, thiếu thì fallback ảnh tĩnh.",
        "# Cảnh chữ/typography/infographic không nằm trong danh sách. Sửa tay thoải mái.", "",
    ]
    # Read prompts-ALL.txt (ACTUAL prompts used to generate images) instead of
    # using prompt-pack.json (requested prompts). This ensures Veo image-to-video
    # generation uses the same style/description as the actual generated images.
    all_prompts_file = context.store.root / "visuals/prompts/prompts-ALL.txt"
    actual_prompts = []
    if all_prompts_file.is_file():
        content = all_prompts_file.read_text(encoding="utf-8")
        # Split by double newlines, each prompt is one paragraph
        actual_prompts = [p.strip() for p in content.split("\n\n") if p.strip()]

    # Build lookup: image_id → actual prompt used for generation
    # IMG-01 corresponds to index 0, IMG-02 to index 1, etc.
    actual_prompts_by_id = {}
    for i, prompt in enumerate(actual_prompts, start=1):
        image_id = "IMG-%02d" % i
        actual_prompts_by_id[image_id] = prompt

    first_event = {}
    for event in value["storyboard"]:
        first_event.setdefault(event["image_id"], event)

    for image_id in selected:
        event = first_event.get(image_id) or {}

        # Use the ACTUAL prompt from prompts-ALL.txt (what was really used to generate the image)
        # This includes the full style description that matches the generated image
        actual_prompt = actual_prompts_by_id.get(image_id, "")

        # Get motion from storyboard
        motion = str(event.get("motion") or "").strip()

        # Build Veo prompt: motion — FULL ACTUAL PROMPT (truncated if needed)
        # This ensures Veo sees the exact style/description used to generate the source image
        if actual_prompt:
            # Use full actual prompt, truncate only if extremely long
            prompt_text = actual_prompt[:350]  # Veo can handle longer prompts
        else:
            # Fallback to storyboard info if prompts-ALL.txt wasn't available
            prompt_text = str(event.get("visual_information") or "").replace("\n", " ").strip()

        hint = " — ".join(x for x in (motion, prompt_text) if x)
        lines.append("%s | %s" % (image_id, hint[:450]))
    refs.append(context.store.put_text(
        "video_prompts", "visuals/prompts/prompts-video.txt",
        "\n".join(lines) + "\n", "image_prompts"))
    return StageResult(refs, qa)


def _publish(context: RunContext) -> StageResult:
    contract = _json(context, "script_contract")
    value = context.provider.create_publish_draft(contract, _json(context, "source_pack"))
    validate_publish_draft(value)
    # Build formatted publish sheet — rõ từng field, dễ copy-paste vào YouTube Studio
    title = contract.get("chosen_title", "")
    description = value.get("description_draft", "")
    source_note = value.get("source_note", "")
    hashtags = value.get("hashtags", [])
    tags = value.get("tags", [])
    pinned = value.get("pinned_comment", "")

    hashtag_line = " ".join(hashtags) if hashtags else ""
    tags_line = "、".join(tags) if tags else ""

    description_body = description.rstrip()
    if hashtag_line:
        description_body = description_body + "\n\n" + hashtag_line
    if source_note:
        description_body = description_body + "\n\n" + source_note

    publish_sheet = (
        "TITLE:\n"
        + title + "\n"
        + "\n"
        + "DESCRIPTION:\n"
        + description_body + "\n"
        + "\n"
        + "TAGS:\n"
        + tags_line + "\n"
        + "\n"
        + "PINNED COMMENT:\n"
        + pinned + "\n"
    )

    description_ref = context.store.put_text("description_draft", "publish/description-draft.txt", publish_sheet, "publish_draft")
    pinned_ref = context.store.put_text("pinned_comment", "publish/pinned_comment.txt", pinned + "\n", "publish_draft")
    metadata_ref = context.store.put_json("publish_metadata", "publish/metadata.json", value, "publish_draft")
    return StageResult([description_ref, pinned_ref, metadata_ref])


RESOURCE_PACK_REQUIRED = (
    "channel_snapshot", "performance_review", "topic_research", "topic_candidates", "selected_topic",
    "source_pack", "psychology_brief", "script_contract", "planning",
    "final_script", "script_vi", "resource_audits", "script_qa", "pause_map", "sections", "minimax_prompt",
    "psychology_format_check",
    "thumbnail_contract",
    "thumbnail_prompt", "thumbnail_prompt_text", "image_strategy", "storyboard", "image_prompts_all", "image_prompt_qa",
    "description_draft", "pinned_comment", "publish_metadata",
)


def _resource_pack(context: RunContext) -> StageResult:
    required = RESOURCE_PACK_REQUIRED
    missing = [name for name in required if name not in context.state.artifact_index]
    corrupt = [name for name in required if name in context.state.artifact_index and not context.store.verify(context.state.artifact_index[name])]
    if missing or corrupt:
        raise ValueError("Resource pack invalid; missing=%s corrupt=%s" % (missing, corrupt))
    manifest = {
        "schema_version": 1,
        "run_id": context.state.run_id,
        "topic": context.topic,
        "profile": context.state.profile,
        "minimax_tts_profile": MINIMAX_PROFILE,
        "policy_reference": "privacy/privacy.md",
        "thumbnail_style_reference": "thumbnail-template/thumbnail-video1.png",
        "artifacts": {
            name: ref.to_dict()
            for name, ref in context.state.artifact_index.items()
            if name != "channel_input"
        },
        "manual_next_steps": [
            "Gen MiniMax MỘT lần từ script/minimax-prompt.txt (bản có tag <#x#> theo rule v9 — strip tag ra đúng script.txt; script.txt luôn sạch) với speed 1.02, pitch -1, volume 1.02 (không chia chunk, không ghép).",
            "Đối chiếu script/pause-map.json để kiểm tra nhịp nghỉ; không đọc cue thành lời.",
            "Chọn `thumbnail/thumbnail-prompt.txt` để gen nền không chữ + overlay thủ công, hoặc `thumbnail/thumbnail-prompt-text.txt` để AI gen sẵn headline Nhật; luôn chạy squint test.",
            "Rà soát privacy/privacy.md và Altered/Synthetic Content trước khi upload.",
            "Gen ảnh từ visuals/prompts/prompts-ALL.txt; đặt tên IMG-01, IMG-02… theo đúng thứ tự prompt rồi bỏ vào video-build/images/.",
            "Gen clip (tùy chọn) image-to-video từ visuals/prompts/prompts-video.txt (từ CHÍNH ảnh đã gen) → video-build/clips/IMG-xx.mp4 — engine ưu tiên clip, thiếu thì fallback ảnh tĩnh.",
            "Bỏ 1 file audio GHÉP (toàn bộ video) vào audio/ — trang Dựng video sẽ tự cắt theo section và đo thời gian thật.",
            "Mở trang Dựng video trên web, chọn run này → xem còn thiếu gì → bấm Dựng → video-final.mp4 nằm trong video-build/.",
        ],
    }
    qa = {"passed": True, "required_artifacts": len(required), "missing": [], "corrupt": [], "pack_assembled": True, "video_export": "manual", "auto_render": False}
    checklist = """# Manual production checklist

1. Gen MiniMax MỘT lần từ script/minimax-prompt.txt (bản có tag <#x#> — strip tag ra đúng script.txt) với speed 1.02, pitch -1, volume 1.02 (không chia chunk, không ghép).
2. Đối chiếu pause-map.json và nghe lỗi phát âm.
3. Đo audio thật; ghi duration và CPM vào manual_results.json.
4. Gen thumbnail theo style lock ink-paper của đối thủ Nhật: `thumbnail-prompt.txt` cho nền không chữ + overlay thủ công; `thumbnail-prompt-text.txt` cho AI gen sẵn headline Nhật. Luôn kiểm tra spelling/squint test; chỉ đổi tư thế, biểu cảm và cảm xúc của nhân vật.
5. Dùng nhân vật minh họa vô danh, phi giới tính; không tái tạo khuôn mặt/người thật, không để người xem hiểu người được trích dẫn đang trực tiếp phát ngôn.
6. Overlay chữ thủ công, kiểm tra chính tả Nhật và chạy squint test ở 128×72.
7. Đối chiếu `privacy/privacy.md`: nội dung phải có biên tập/góc nhìn riêng, không copy hàng loạt; rà soát mục Altered/Synthetic Content trong YouTube Studio cho tài sản realistic AI.
8. Gen ảnh theo visuals/prompts/prompts-ALL.txt; đặt tên IMG-01, IMG-02… theo đúng thứ tự prompt rồi bỏ vào video-build/images/.
9. (Tùy chọn) Gen clip image-to-video từ visuals/prompts/prompts-video.txt (từ CHÍNH ảnh đã gen, không gen cảnh chữ) → video-build/clips/IMG-xx.mp4 — engine ưu tiên clip, thiếu thì fallback ảnh tĩnh.
10. Bỏ 1 file audio GHÉP (toàn bộ video) vào audio/ — trang Dựng video trên web sẽ đo thời gian thật, cắt theo section, sinh prompts-build.py + marks.tsv, rồi bấm Dựng để gọi youtube_pipeline/build-video.py ráp video-final.mp4. Bấm Dựng lại mỗi khi bỏ thêm ảnh/audio mới.
"""
    manifest_ref = context.store.put_json("resource_manifest", "resource_manifest.json", manifest, "resource_pack")
    qa_ref = context.store.put_json("resource_pack_qa", "qa/resource_pack_qa.json", qa, "resource_pack")
    checklist_ref = context.store.put_text("manual_production_checklist", "qa/manual-production-checklist.md", checklist, "resource_pack")
    return StageResult([manifest_ref, qa_ref, checklist_ref], qa)


def resource_pack_stages(output_dir: Path | None = None) -> list[FunctionStage]:
    # Flow 3-bước: (1) pipeline làm TÀI NGUYÊN → dừng ở resource_pack; (2) người
    # gen TTS/ảnh ngoài, bỏ vào audio/ + video-build/images/ (tên IMG-xx);
    # (3) trang "Dựng video" trên web gọi build service (timeline.py + video_build.py)
    # để dựng prompts-build.py/marks.tsv, cắt audio và gọi build-video.py (trong
    # package) để ráp video-final.mp4.
    return [
        FunctionStage("ingest", _ingest, requires=("channel_input",), version="3"),
        FunctionStage("performance", _performance, requires=("channel_snapshot",), version="3"),
        FunctionStage("topic_research", _topic_research, requires=("channel_snapshot", "performance_review"), version="2"),
        FunctionStage("topic_candidates", _topic_candidates, requires=("topic_research", "channel_snapshot", "performance_review"), version="2"),
        FunctionStage("topic_selection", _topic_selection, requires=("topic_candidates", "topic_research", "performance_review"), version="3"),
        FunctionStage("source_lock", _source_lock, requires=("selected_topic", "channel_snapshot", "performance_review")),
        FunctionStage("claim_ledger", _claim_ledger, requires=("source_pack",), version="3"),
        # One skill-led creative brief emits compatibility artifacts consumed by
        # downstream packaging/visual stages. It replaces three independent
        # model calls (brief -> contract -> planning).
        FunctionStage("narrative_brief", _narrative_brief, requires=("selected_topic", "source_pack", "claim_ledger", "performance_review"), version="6"),
        FunctionStage("writing", _writing, requires=("script_contract", "planning", "source_pack", "claim_ledger", "psychology_brief"), version="11"),
        # One audit plus at most one targeted repair; no generic review pass.
        FunctionStage("script_audit", _script_audit, requires=("script_draft", "script_contract", "planning", "source_pack", "claim_ledger", "psychology_brief"), version="5"),
        FunctionStage("script_qa", _script_qa, requires=("final_script", "claim_ledger"), version="12"),
        FunctionStage("structure_check", _structure_check, requires=("final_script", "script_contract", "planning", "psychology_brief", "claim_ledger"), version="7"),
        FunctionStage("psychology_format_check", _psychology_format_check, requires=("final_script", "structure_check", "psychology_brief", "script_contract"), version="4"),
        FunctionStage("translate_script_vi", _translate_script_vi, requires=("final_script", "structure_check"), version="2"),
        FunctionStage("sections", _sections, requires=("final_script", "script_qa", "planning"), version="3"),
        FunctionStage("thumbnail_contract", _thumbnail, requires=("final_script", "script_contract"), version="10"),
        FunctionStage("image_strategy", _image_strategy, requires=("final_script", "script_qa", "sections", "script_contract", "planning", "thumbnail_contract"), version="8"),
        FunctionStage("image_prompts", _image_prompts, requires=("image_strategy", "script_qa", "sections", "script_contract", "planning"), version="8"),
        FunctionStage("publish_draft", _publish, requires=("script_contract", "source_pack"), version="2"),
        FunctionStage("resource_pack", _resource_pack, requires=("sections", "thumbnail_contract", "image_prompt_pack", "publish_metadata"), version="8"),
    ]


class ResourcePackPipeline:
    def __init__(
        self,
        provider: ResourceContentProvider,
        output_dir: Path,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        progress: Callable[[str], None] = print,
    ) -> None:
        self.provider = provider
        self.output_dir = output_dir
        self.store = ArtifactStore(output_dir)
        self.engine = PipelineEngine(resource_pack_stages(self.output_dir), max_retries=max_retries, retry_delay=retry_delay)
        self.progress = progress

    def create_state(self, raw_data: str, run_id: str | None = None) -> RunState:
        routing_snapshot = None
        router = getattr(self.provider, "router", None)
        if router is not None and hasattr(router, "snapshot"):
            routing_snapshot = router.snapshot()
        config_snapshot = {
            "production_policy_version": PRODUCTION_POLICY_VERSION,
            "minimax_tts_profile": MINIMAX_PROFILE,
            "target_duration_minutes": [35, 45],
            "target_duration_max_warning_minutes": 55,
            "target_chars": [13600, 17500],
            "target_chars_is_guideline": True,
        }
        if routing_snapshot is not None:
            config_snapshot["model_routing"] = routing_snapshot
        state = RunState(
            run_id=run_id or uuid.uuid4().hex,
            profile="resource_pack",
            topic="",
            config_snapshot=config_snapshot,
        )
        ref = self.store.put_text("channel_input", "input/youtube_data.json", raw_data, "input")
        state.artifact_index["channel_input"] = ref
        state.input_artifacts["channel_input"] = ref.sha256
        self.store.save_state(state)
        return state

    def load_state(self) -> RunState:
        return self.store.load_state()

    def run(self, state: RunState, raw_data: str | None = None) -> RunState:
        source = raw_data if raw_data is not None else self.store.read_text("channel_input", state)
        context = RunContext(
            state=state,
            store=self.store,
            provider=self.provider,
            raw_data=source,
            topic=state.topic,
            config=state.config_snapshot,
            progress=self.progress,
        )
        result = self.engine.run(context)
        selected = self.store.read_json("selected_topic", result)
        brief = self.store.read_json("psychology_brief", result)
        contract = self.store.read_json("script_contract", result)
        record_drafted(self.output_dir, result.run_id, {**selected, "chosen_title": contract.get("chosen_title", "")}, brief)
        return result
