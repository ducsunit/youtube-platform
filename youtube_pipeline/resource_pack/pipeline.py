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
from .sections import PAUSE_BEFORE_OUTRO, PAUSE_BETWEEN_SECTIONS, PAUSE_PARAGRAPH_BREAK, build_tts_ready, insert_pause_tags, normalize_text, split_script_sections, strip_minimax_tags
from .metrics import build_pause_map, non_whitespace_chars, scrub_source_citation_tokens, validate_japanese_script
from .analysis import build_channel_snapshot, build_performance_review
from .competitor import competitor_inject_text
from .providers import DemoResourceProvider, ResourceContentProvider
from .claim_ledger import attach_claim_ledger, build_claim_ledger, policy_violations, validate_claim_ledger
from .prompts import (
    target_duration_min_from_contract,
    target_min_chars_from_contract,
)
from ..topic_history import annotate_candidates, duplicate_reason, load_history, record_completed

PRODUCTION_POLICY_VERSION = "2026-08-20.1"
from .validation import (
    VALIDATION_PHRASES_JA,
    SUGGESTED_FORMAT_GATE,
    anti_story_findings,
    audit_passes,
    format_gate_verdict,
    generic_selfhelp_findings,
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
    normalize_state_advance,
    validate_plan,
    normalize_plan_example_budgets,
    normalize_plan_editorial_metadata,
    validate_psychology_brief,
    normalize_score_0_10,
    validate_prompt_pack,
    validate_publish_draft,
    validate_source_pack,
    validate_thumbnail,
    normalize_thumbnail_prompt,
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


def _performance(context: RunContext) -> StageResult:
    review = build_performance_review(_json(context, "channel_snapshot"))
    ref = context.store.put_json("performance_review", "research/performance_review.json", review, "performance")
    return StageResult([ref], warnings=review["warnings"])


def _topic_research(context: RunContext) -> StageResult:
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
    value = context.provider.select_topic(
        candidates,
        _json(context, "topic_research"),
        _json(context, "performance_review"),
    )
    history = load_history(context.store.root)
    if duplicate_reason(value, history):
        available = [row for row in candidates.get("candidates", []) if not duplicate_reason(row, history)]
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
    ref = context.store.put_json("psychology_brief", "script/psychology-brief.json", value, "psychology_brief")
    return StageResult([ref], {"route": value["route"], "mechanisms": len(value["selected_mechanisms"])})


def _script_contract(context: RunContext) -> StageResult:
    value = context.provider.create_contract(
        context.topic, _source_policy(context), _json(context, "performance_review"),
        _json(context, "psychology_brief"),
    )
    if normalize_contract_format_lock(value):
        logger.warning("Contract format_lock wording normalized to the production metadata lock.")
    if normalize_title_hook_contract(value):
        logger.warning("Contract title_hook_contract normalized for title-to-opening alignment.")
    try:
        validate_contract(value)
    except ValueError as exc:
        # Known contract formatting defects get one targeted correction pass;
        # other contract failures remain deterministic failures.
        message = str(exc)
        repairable = (
            "title candidate" in message
            or "Chosen title" in message
            or "content_center" in message
        )
        if not repairable:
            raise
        logger.warning("Contract validation failed; requesting one targeted correction: %s", message)
        value = context.provider.create_contract(
            context.topic,
            _source_policy(context),
            _json(context, "performance_review"),
            _json(context, "psychology_brief"),
            validation_feedback=message,
        )
        if normalize_contract_format_lock(value):
            logger.warning("Repaired contract format_lock wording normalized to the production metadata lock.")
        normalize_title_hook_contract(value)
        try:
            validate_contract(value)
        except ValueError:
            if "content_center" not in message and "title candidate" not in message and "Chosen title" not in message:
                raise
            # Keep a valid psychological spine even if the repair model repeats
            # the scene wording: the validated identity is the safe source.
            normalize_contract_format_lock(value)
            normalize_contract_titles(value)
            normalize_title_hook_contract(value)
            validate_contract(value)
    ref = context.store.put_json("script_contract", "script/contract.json", value, "script_contract")
    return StageResult([ref], {"title_chars": len(value["chosen_title"])})


def _attach_missing_planning_mechanisms(plan: dict, brief: dict) -> None:
    """Make the locked mechanism names explicit in the plan after model repair."""
    expected = [
        str(item.get("name", "")).strip()
        for item in brief.get("selected_mechanisms", [])
        if isinstance(item, dict) and str(item.get("name", "")).strip()
    ]
    seen = {
        str(name).strip()
        for section in plan.get("sections", [])
        for name in section.get("mechanisms_used", [])
    }
    missing = [name for name in expected if name not in seen]
    if not missing:
        return
    sections = plan.get("sections") or []
    target = next(
        (section for section in sections if section.get("segment_function") in {"mechanism", "inner_world", "integration"}),
        sections[0] if sections else None,
    )
    if target is not None:
        target.setdefault("mechanisms_used", []).extend(missing)


def _planning(context: RunContext) -> StageResult:
    brief = _json(context, "psychology_brief")
    value = context.provider.create_plan(_json(context, "script_contract"), _source_policy(context), brief)
    for section in value.get("sections", []):
        section["state_advance"] = normalize_state_advance(section.get("state_advance"))
    normalize_plan_editorial_metadata(value)
    if normalize_plan_example_budgets(value):
        logger.warning("Planning example_budget vượt tổng 4; đã giảm metadata thừa deterministic.")
    try:
        validate_plan(value, _source_policy(context), brief)
    except ValueError as exc:
        # Hook and mechanism-name drift are local planner defects. Give the
        # writer one targeted repair pass instead of retrying blindly.
        message = str(exc)
        repairable = (
            "Hook micro-scene chưa pivot sớm" in message
            or "Planning chưa cover selected mechanisms" in message
            or "Planning dùng relief/reinforcement loop ngoài source pack" in message
        )
        if not repairable:
            raise
        logger.warning("Planning validation failed; requesting one targeted correction: %s", message)
        value = context.provider.create_plan(
            _json(context, "script_contract"),
            _source_policy(context),
            brief,
            validation_feedback=message,
        )
        for section in value.get("sections", []):
            section["state_advance"] = normalize_state_advance(section.get("state_advance"))
        normalize_plan_editorial_metadata(value)
        if normalize_plan_example_budgets(value):
            logger.warning("Planning repair example_budget vượt tổng 4; đã giảm metadata thừa deterministic.")
        try:
            validate_plan(value, _source_policy(context), brief)
        except ValueError as repair_exc:
            repair_message = str(repair_exc)
            combined_messages = "%s\n%s" % (message, repair_message)
            # Preserve a recognition micro-scene but add the locked question
            # immediately after it if the targeted repair still lacks a pivot.
            contract = _json(context, "script_contract")
            question = str(contract.get("core_psychological_question", "")).strip()
            hook = str(value.get("hook_draft", "")).strip()
            if "Hook micro-scene chưa pivot sớm" in combined_messages and question and hook:
                sentences = [part for part in re.split(r"(?<=[。！？])", hook) if part]
                value["hook_draft"] = "".join(sentences[:1]) + question.rstrip("。！？?!") + "。" + "".join(sentences[1:])
            if "Planning chưa cover selected mechanisms" in combined_messages:
                _attach_missing_planning_mechanisms(value, brief)
            validate_plan(value, _source_policy(context), brief)
    ref = context.store.put_json("planning", "script/planning.json", value, "planning")
    return StageResult([ref], {"sections": len(value["sections"])})


def _writing(context: RunContext) -> StageResult:
    value = context.provider.write_script(_json(context, "script_contract"), _json(context, "planning"), _source_policy(context), _json(context, "psychology_brief"))
    ref = context.store.put_text("script_draft", "script/script-draft.txt", value, "writing")
    return StageResult([ref], {"raw_chars": len(value)})


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
        hook_findings = psychology_hook_findings(draft)
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
    unsupported causal sentence with softer wording.
    """
    repaired = script
    for audit in audits:
        for item in (audit or {}).get("unsupported_claims") or []:
            if isinstance(item, dict):
                claim = item.get("claim") or item.get("text") or ""
            else:
                claim = item
            claim = str(claim).strip().strip("「」『』\"'")
            if not claim or claim not in repaired:
                continue
            sentence = re.compile(r"[^。！？!?]*" + re.escape(claim) + r"[^。！？!?]*[。！？!?]")
            updated = sentence.sub("", repaired, count=1)
            repaired = updated if updated != repaired else repaired.replace(claim, "", 1)
    return repaired


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


def _consistency(context: RunContext) -> StageResult:
    contract = _json(context, "script_contract")
    plan = _json(context, "planning")
    source_pack = _source_policy(context)
    claim_ledger = _json(context, "claim_ledger")
    script = _text(context, "reviewed_script")
    rounds = []
    for round_number in range(1, 4):
        unsupported = unsupported_source_claims(script, source_pack)
        policy_blocked = policy_violations(script, claim_ledger)
        if unsupported or policy_blocked:
            boundary_findings = {
                "decision": "revise",
                "source_boundary_violation": True,
                "unsupported_claim_markers": unsupported,
                "policy_violations": policy_blocked,
                "required_changes": [
                    "Source pack là authority cao nhất. Xóa hoàn toàn mọi claim khoa học, tiến hóa hoặc nguyên nhân tuổi thơ không có trong verified_sources/allowed_paraphrases; không được làm mềm câu rồi giữ lại cùng claim.",
                    "Nếu plan yêu cầu nội dung không có nguồn, bỏ nội dung đó và thay bằng diễn giải editorial_application có căn cứ.",
                    "Không dùng các forbidden_terms trong CLAIM LEDGER của run này.",
                ],
            }
            repaired = context.provider.repair_script(contract, plan, source_pack, script, boundary_findings)
            script = str(repaired.get("final_script", "")).strip()
            if not script:
                raise ValueError("Repair source-boundary trả script rỗng.")
            remaining = unsupported_source_claims(script, source_pack) + policy_violations(script, claim_ledger)
            if remaining:
                raise ValueError(
                    "Editor repair vẫn còn claim ngoài source pack: %s" % ", ".join(remaining)
                )
        audit = normalize_audit_report(
            context.provider.audit_script("auditor", contract, plan, source_pack, script), "auditor"
        )
        audits = {"auditor": audit}
        passed = audit_passes(audit)
        round_result = {"round": round_number, "passed": passed, "audits": audits}
        rounds.append(round_result)
        if passed:
            break
        if round_number < 3:
            repaired = context.provider.repair_script(
                contract,
                plan,
                source_pack,
                script,
                {
                    **round_result,
                    "required_changes": [
                        "Source pack có ưu tiên cao hơn plan. Không khôi phục claim mà verified_sources không hỗ trợ.",
                        "Với từng unsupported_claims, phải xóa hẳn câu hoặc thay bằng câu chỉ diễn đạt đúng source pack/allowed_paraphrases; không được giữ lại cùng ý nhân quả bằng từ đồng nghĩa hay thêm mức độ 'có thể'.",
                        "Không suy ra cơ chế tâm lý mới từ một ví dụ hành vi. Nếu source không nói rõ, bỏ cơ chế đó và giữ phần quan sát hành vi trung tính.",
                        "Editorial application chỉ được dùng khi source_pack.editorial_application hoặc allowed_paraphrases hỗ trợ trực tiếp. Không mang framework, author, causal mechanism hoặc practical principle từ một run/topic khác vào script.",
                        "Nếu source chỉ hỗ trợ behavior + context/habit/interpretation ở mức giới hạn, giữ script ở đúng mức đó; không tự suy ra responsibility boundary, diagnosis hoặc causal mechanism thứ hai.",
                        "Nếu claim_ledger.capabilities.reinforcement_loop=false, xóa causal chain relief ngắn hạn -> phản ứng được duy trì/củng cố; chỉ giữ observation cost không nhân quả.",
                    ],
                },
            )
            script = str(repaired.get("final_script", "")).strip()
            if not script:
                raise ValueError("Repair trả script rỗng.")
            script = _remove_unsupported_audit_claims(script, audit)
    if not rounds[-1]["passed"]:
        cleaned, scrubbed, removed_claims = _finalize_source_audit_after_scrub(script, rounds[-1])
        if scrubbed:
            code_remaining = unsupported_source_claims(cleaned, source_pack) + policy_violations(cleaned, claim_ledger)
            if not code_remaining:
                script = cleaned
                for audit_name, audit in (rounds[-1].get("audits") or {}).items():
                    if audit.get("unsupported_claims"):
                        audit["unsupported_claims"] = []
                        audit["source_alignment"] = True
                rounds[-1]["passed"] = all(
                    audit_passes(item) for item in (rounds[-1].get("audits") or {}).values()
                )
                logger.warning(
                    "Consistency final deterministic source scrub removed %d exact unsupported claim(s).",
                    len(removed_claims),
                )
                rounds[-1]["deterministic_source_scrub"] = {
                    "applied": True,
                    "removed_claims": removed_claims,
                }
    if not rounds[-1]["passed"]:
        raise ValueError(
            "Script không vượt consistency/source audit sau 3 vòng. Chi tiết: %s"
            % _audit_failure_reasons(rounds[-1])
        )
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
        warnings=audit_notes,
    )


def _put_script_qa(context: RunContext, script: str, producer: str) -> tuple:
    """Validate + ghi script_qa/pause_map cho script hiện tại.

    Dùng chung cho stage script_qa (validate bản từ consistency) và
    structure_check (re-gate bản đã repair — tránh QA stale trên bản pre-repair).
    """
    qa = validate_japanese_script(script)
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
    qa = validate_japanese_script(script)
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


def _psychology_structure_issues(script: str, contract: dict, planning: dict, brief: dict) -> tuple[list[str], list[str], list[str]]:
    """Evaluate the psychology-first spine independently from any fixed script template."""
    story_findings = anti_story_findings(script)
    issues = list(story_findings)
    mechanism_items = [item for item in brief.get("selected_mechanisms", []) if isinstance(item, dict)]
    mechanisms = [str(item.get("name", "")) for item in mechanism_items]
    covered = [name for item, name in zip(mechanism_items, mechanisms) if _mechanism_is_covered(script, item)]
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
    if not any(section.get("segment_function") == "insight_landing" for section in planning.get("sections", [])):
        issues.append("planning lacks self-understanding insight landing")
    if brief.get("origin_status") in {"unsupported", "irrelevant", "skip"}:
        if any(marker in script for marker in ("幼少期", "子どもの頃", "生まれつき")):
            issues.append("origin/childhood explanation used without brief support")
    return issues, mechanisms, covered


def _structure_check(context: RunContext) -> StageResult:
    """Blocking psychology-first gate with a bounded anti-story repair loop."""
    script = _text(context, "final_script")
    input_script_sha = hashlib.sha256(script.encode("utf-8")).hexdigest()

    # Chỉ khóa vĩnh viễn khi script ĐẦU VÀO không đổi: nếu upstream (consistency/
    # apply_review) sửa script rồi resume, stage phải có cửa sổ repair mới thay vì
    # kẹt "exhausted 3 rounds" từ report cũ.
    report_path = context.store.root / "script/structure-check.json"
    if report_path.exists():
        prior = json.loads(report_path.read_text(encoding="utf-8"))
        if (
            prior.get("status") == "fail"
            and len(prior.get("repair_rounds", [])) >= 3
            and prior.get("input_script_sha") == input_script_sha
        ):
            raise ValueError("Psychology-first structure repair already exhausted 3 rounds.")

    contract = _json(context, "script_contract")
    planning = _json(context, "planning")
    brief = _json(context, "psychology_brief")
    issues, mechanisms, covered = _psychology_structure_issues(script, contract, planning, brief)
    repair_rounds = []

    # Demo runs are deterministic fixtures and must never spend an LLM repair call.
    # A broken Demo subclass therefore fails transparently with its report intact.
    if issues and not isinstance(context.provider, DemoResourceProvider):
        for round_number in range(1, 4):
            before_issues = list(issues)
            before_score = max(0, 100 - len(before_issues) * 25)
            findings = {
                "structure_repair": True,
                "psychology_first": True,
                "required_changes": before_issues,
                "rewrite_rule": "preserve supported claims; replace plot/scene chains with direct behavior → inner process → mechanism → why → insight narration",
            }
            repaired = context.provider.repair_script(
                contract, planning, _source_policy(context), script, findings
            )
            candidate = str(repaired.get("final_script", "")).strip()
            if not candidate:
                raise ValueError("Structure repair trả final_script rỗng.")
            script = candidate
            issues, mechanisms, covered = _psychology_structure_issues(
                script, contract, planning, brief
            )
            repair_rounds.append({
                "round": round_number,
                "before_score": before_score,
                "before_issues": before_issues,
                "after_score": max(0, 100 - len(issues) * 25),
                "after_issues": list(issues),
            })
            if not issues:
                break

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
    }
    ref = context.store.put_json("structure_check", "script/structure-check.json", report, "structure_check")
    if issues:
        raise ValueError("Psychology-first structure check failed: %s" % "; ".join(issues))

    artifacts = [ref]
    warnings: list[str] = []
    if repair_rounds:
        # Ghi final_script CHỈ KHI đã pass — trước đây ghi trước raise khiến file
        # script.txt lệch artifact_index (ref chưa vào index) và phá resume
        # ("Missing artifact: final_script" ở stage sau).
        artifacts.append(
            context.store.put_text("final_script", "script/script.txt", script, "structure_check")
        )
        # Re-gate QA trên script ĐÃ repair: stage script_qa chạy trước đây validate
        # bản pre-repair nên duration/char gate có thể stale so với script cuối.
        qa_ref, pause_ref, qa, _ = _put_script_qa(context, script, "structure_check")
        artifacts.extend([qa_ref, pause_ref])
        min_seconds = qa["estimated_duration_min_seconds"]
        max_seconds = qa["estimated_duration_max_seconds"]
        duration_warning = _duration_guideline_warning(context, qa)
        if duration_warning:
            warnings.append(duration_warning)
        if max_seconds > 900:
            warnings.append(
                "Script sau structure repair ước tính %d–%d giây, vượt trần cảnh báo 15 phút; timing chỉ là telemetry."
                % (min_seconds, max_seconds)
            )
    return StageResult(
        artifacts,
        {"structure_score": score, "issues_count": 0, "repair_rounds": len(repair_rounds)},
        warnings=warnings,
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
    """Vietnamese manager-QA translation; never replaces Japanese final script."""
    translated = context.provider.translate_to_vietnamese(_text(context, "final_script"))
    ref = context.store.put_text("script_vi", "script/script-vi.txt", translated, "translate_script_vi")
    return StageResult([ref], {"vi_chars": len(translated)})


def _sections(context: RunContext) -> StageResult:
    """Chia script thành sections theo planning (không còn chia chunk).

    Script được giữ nguyên độ dài thực tế → gen MiniMax được trong MỘT lần gọi
    từ script/minimax-prompt.txt; sections chỉ để derive timeline ở trang
    "Dựng video" (web build service tính timeline từ sections + storyboard).
    Số section khớp planning.json (S1..SN) nên mọi beat/event đều map được cửa
    sổ (lỗi cũ: chunker ra ít hơn → event cuối script bị bỏ).
    """
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
    # Dọn tàn dư flow cũ (chia chunk): người dùng glob theo script/chunks sẽ gen
    # audio nhầm file stale. sections.json mới là nguồn duy nhất cho mốc/tên file.
    chunk_dir = context.store.root / "script/chunks"
    if chunk_dir.is_dir():
        shutil.rmtree(chunk_dir)
    (context.store.root / "script/chunk-manifest.json").unlink(missing_ok=True)
    return StageResult(
        [sections_ref, prompt_ref],
        {"sections": len(rows), "total_chars": payload["total_chars"]},
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
    overlay_ref = context.store.put_json("thumbnail_overlay", "thumbnail/overlay-spec.json", value["overlay_spec"], "thumbnail_contract")
    checklist_ref = context.store.put_text("thumbnail_checklist", "thumbnail/manual-checklist.md", "# Thumbnail manual checklist\n\n- Đọc `click_hypothesis` và `hook_alignment` trong thumbnail/contract.json trước khi edit. Thumbnail phải hứa đúng behavior/contradiction mà cold open trả trong 20 giây đầu.\n- Gen ảnh nền không chữ.\n- Dùng visual anchor `video-build/images/IMG-01.png` nếu provider hỗ trợ ảnh tham chiếu.\n- Nếu provider không hỗ trợ reference image, giữ nguyên CHARACTER_BIBLE và không tạo mascot mới.\n- Chỉ một nhân vật/focal action, một visual conflict, một warm accent có chủ đích; không collage, hard split hay badge urgency giả.\n- Overlay đúng spec; headline 4-8 ký tự phải đọc được ở preview 128×72.\n- Tạo preview 128×72 và squint test trên ảnh thật: PENDING_USER.\n- Nhân vật là học giả Nhật hư cấu; không tái tạo khuôn mặt/người thật (likeness/privacy gate).\n- Khai báo Altered/Synthetic Content trong YouTube Studio cho ảnh realistic AI (xem privacy/privacy.md).\n", "thumbnail_contract")
    return StageResult([contract_ref, prompt_ref, overlay_ref, checklist_ref], qa)


def _image_strategy(context: RunContext) -> StageResult:
    contract = _json(context, "script_contract")
    plan = _json(context, "planning")
    value = context.provider.create_image_strategy(contract, plan, _json(context, "thumbnail_contract"))
    validate_image_strategy(value, contract, plan)
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
    validate_image_strategy(
        strategy,
        _json(context, "script_contract"),
        _json(context, "planning"),
    )
    value = context.provider.create_image_prompts(strategy, _json(context, "script_contract"))
    normalize_image_prompts(value, strategy)
    qa = validate_prompt_pack(value, strategy)
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
    "thumbnail_prompt", "image_strategy", "storyboard", "image_prompts_all", "image_prompt_qa",
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
            "Gen thumbnail theo style reference, dùng học giả Nhật hư cấu; overlay chữ thủ công và chạy squint test.",
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
4. Gen thumbnail theo style lock PsychToons: flat illustrated cartoon, viền đen dày, màu phẳng (no gradient/shading), background navy #1A2332, chữ Nhật đậm overlay thủ công; chỉ đổi tư thế, biểu cảm và cảm xúc của nhân vật.
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
        FunctionStage("topic_research", _topic_research, requires=("channel_snapshot", "performance_review")),
        FunctionStage("topic_candidates", _topic_candidates, requires=("topic_research", "channel_snapshot", "performance_review")),
        FunctionStage("topic_selection", _topic_selection, requires=("topic_candidates", "topic_research", "performance_review"), version="2"),
        FunctionStage("source_lock", _source_lock, requires=("selected_topic", "channel_snapshot", "performance_review")),
        FunctionStage("claim_ledger", _claim_ledger, requires=("source_pack",), version="2"),
        FunctionStage("psychology_brief", _psychology_brief, requires=("selected_topic", "source_pack", "claim_ledger", "performance_review"), version="3"),
        FunctionStage("script_contract", _script_contract, requires=("source_pack", "claim_ledger", "psychology_brief", "performance_review"), version="8"),
        FunctionStage("planning", _planning, requires=("script_contract", "source_pack", "claim_ledger", "psychology_brief"), version="10"),
        FunctionStage("writing", _writing, requires=("script_contract", "planning", "source_pack", "claim_ledger", "psychology_brief"), version="7"),
        FunctionStage("review", _review, requires=("script_draft", "script_contract", "planning", "source_pack", "claim_ledger"), version="13"),
        FunctionStage("consistency", _consistency, requires=("reviewed_script", "script_contract", "planning", "source_pack", "claim_ledger"), version="8"),
        FunctionStage("script_qa", _script_qa, requires=("final_script", "claim_ledger"), version="7"),
        FunctionStage("structure_check", _structure_check, requires=("final_script", "script_contract", "planning", "psychology_brief", "claim_ledger"), version="4"),
        FunctionStage("psychology_format_check", _psychology_format_check, requires=("final_script", "structure_check", "psychology_brief", "script_contract"), version="3"),
        FunctionStage("translate_script_vi", _translate_script_vi, requires=("final_script", "structure_check"), version="1"),
        FunctionStage("sections", _sections, requires=("final_script", "script_qa", "planning"), version="2"),
        FunctionStage("thumbnail_contract", _thumbnail, requires=("final_script", "script_contract"), version="5"),
        FunctionStage("image_strategy", _image_strategy, requires=("script_contract", "planning", "thumbnail_contract"), version="4"),
        FunctionStage("image_prompts", _image_prompts, requires=("image_strategy", "script_contract", "planning"), version="5"),
        FunctionStage("publish_draft", _publish, requires=("script_contract", "source_pack"), version="2"),
        FunctionStage("resource_pack", _resource_pack, requires=("sections", "thumbnail_contract", "image_prompt_pack", "publish_metadata"), version="7"),
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
            "target_duration_minutes": [6, 12],
            "target_duration_max_warning_minutes": 15,
            "target_chars": [2300, 6000],
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
        record_completed(self.output_dir, result.run_id, {**selected, "chosen_title": contract.get("chosen_title", "")}, brief)
        return result
