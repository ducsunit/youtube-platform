from __future__ import annotations

import math
import re
from typing import Any

from .japanese_metrics import non_whitespace_chars
from .source_catalog import KNOWN_SOURCE_URLS

# Keep the legacy import path aligned with the canonical resource-pack validator.
# The API/pipeline compatibility layer still imports this module directly.
from .resource_pack.validation import (
    mechanism_is_covered,
    normalize_contract_format_lock,
    normalize_contract_titles,
    normalize_title_hook_contract,
    normalize_plan_example_budgets,
    normalize_editorial_promise,
    normalize_review_list,
    normalize_thumbnail_prompt,
    psychology_review_gate_verdict,
    select_video_candidates,
    title_hook_alignment,
    validate_contract as _validate_contract_canonical,
    validate_psychology_brief as _validate_psychology_brief_canonical,
    validate_source_bounded_brief_causality,
    validate_thumbnail,
)


# Claims in these categories require an explicit verified source. They are not
# safe to infer from a philosophy/self-help source or from an LLM-generated plan.
SENSITIVE_CLAIM_MARKERS = (
    "扁桃体",
    "脳科学",
    "脳は",
    "脳が",
    "生存本能",
    "生存に関わる",
    "原始の昔",
    "進化的",
    "幼少期",
    "子どもの頃",
    "親の顔色",
    "amygdala",
    "neuroscience",
    "survival instinct",
    "childhood trauma",
    "não bộ",
    "hạch hạnh nhân",
    "bản năng sinh tồn",
    "tuổi thơ",
)


# Legacy phrases retained for backwards-compatible imports. Psychology-first flow
# does not require fixed reassurance density or exact wording.
VALIDATION_PHRASES_JA = (
    "それはあなたの弱さではありません",
    "誰もあなたに説明してくれなかった",
    "あなたは壊れていません",
    "これは欠陥ではありません",
    "あなたは冷たくありません",
)

PSYCHOLOGY_ROUTES = {
    "EXPLANATION", "PROFILE_SIGNS", "PARADOX", "PROCESS", "RELATIONAL"
}
OPTIONAL_STATUSES = {"required", "useful", "unsupported", "irrelevant", "skip"}

# Deterministic warning signals, deliberately narrow to avoid flagging ordinary
# behavioral examples. Semantic review remains the authoritative story-dominance gate.
STORY_SEQUENCE_MARKERS_JA = (
    "ドアが開", "部屋に入", "窓の外を見", "その後", "翌日", "思い出した",
    "歩いてい", "振り返ると",
)


# Claim thật sự của brief — những gì video sẽ khẳng định. Candidates (giả thuyết
# đang cân nhắc, kèm source_support), exclusions (danh sách cấm — cố ý chứa thuật
# ngữ ngoài source), common_misconception (niềm tin sai của người xem) và các
# status đều KHÔNG phải claim: validator không được cấm AI nhắc tới khái niệm
# nhạy cảm trong các field đó, nếu không AI không thể "cân nhắc rồi loại" và
# brief hợp lệ sẽ fail liên tục (dead loop retry).
PSYCHOLOGY_BRIEF_CLAIM_FIELDS = (
    "psychological_identity",
    "early_reframe",
    "causal_chain",
    "inner_process_map",
)


def _brief_claim_text(value: dict) -> str:
    parts = [str(value.get(field, "")) for field in PSYCHOLOGY_BRIEF_CLAIM_FIELDS]
    for mechanism in value.get("selected_mechanisms", []):
        if isinstance(mechanism, dict):
            parts.extend(str(item) for item in mechanism.values())
    return "\n".join(parts)


def validate_psychology_brief(value: dict, source_pack: dict | None = None) -> None:
    """Compatibility entry point for the canonical psychology-brief contract."""
    _validate_psychology_brief_canonical(value, source_pack)


def anti_story_findings(text: str) -> list[str]:
    """Return deterministic story warnings; does not diagnose semantic quality."""
    findings = []
    hits = [marker for marker in STORY_SEQUENCE_MARKERS_JA if marker in text]
    if len(hits) >= 3:
        findings.append("sequential_story_markers: " + ", ".join(hits))
    # Japanese dialogue quotes: a long chain is usually a scene, one quoted thought is fine.
    quoted_utterances = re.findall(r"「([^」]*)」", text)
    if sum(1 for utterance in quoted_utterances if len(utterance.strip()) >= 15) >= 8:
        findings.append("dialogue_chain: quoted utterances exceed micro-example budget")
    return findings


# --- Psychology format check (plan v2 §13–15) ---------------------------------
#
# Metrics deterministic 0–10 cho stage psychology_format_check. Công thức còn là
# proxy (Sprint 6): gate dưới đây CHỈ là gợi ý, chờ calibrate sau 10–20 video
# thực tế với intro_retention/average_view_duration từ YouTube Analytics.
#
# self_recognition / insight_density scale theo mật độ trên 100 ký tự
# (SCRIPT_SCORE_PER_100 = 6): script 4.000 ký tự cần ~17 marker để đạt 10/10.

SCRIPT_METRIC_PER_100 = 6.0

# Identity-flattery thuần không kèm mechanism = generic self-help (plan §15 Bad).
GENERIC_SELFHELP_MARKERS_JA = (
    "あなたは繊細", "あなたは敏感", "あなたは優しい", "あなたは強い",
    "あなたは弱い", "あなたは特別", "あなたは深い", "あなたはそのまま",
    "誰にも理解されない", "みんなに好かれる",
)

# Reframe/insight vocabulary — proxy cho insight density (plan §13).
# Chỉ từ vựng ám chỉ aha/mechanism revelation, không dùng discourse connector
# thuần (つまり/逆に...) vì chúng không phân biệt script insight-dense.
INSIGHT_MARKERS_JA = (
    "実は", "本当は", "正体", "仕組み", "からくり", "一見",
    "見え方", "捉え方", "見えてしまう", "勘違い", "思い込み",
    "本質", "誤解", "錯覚", "勝手に", "無意識", "自動的",
    "歪み", "フィルター", "解釈", "盲点", "落とし穴",
    "見方が変わる", "景色が変わる",
    "気づき", "気づく", "腑に落ちる", "目から鱗",
)

# Trực xưng người xem — proxy cho self-recognition journey "That's me." (plan §8).
VIEWER_ADDRESS_MARKERS_JA = ("あなた",)

# Reframe signature — device quan sát từ kênh đối thủ @PsychToonsHQ: "Not X.
# It's Y. And there's a difference." lặp 3–5 lần/video (sau misconception, sau
# mỗi mechanism block, trước ending). Proxy deterministic: cấu trúc tương phản
# "XではなくY" / "XじゃなくてY". Không dùng "ではない" trần vì vướng câu hỏi tu
# từ ("ではないでしょうか") — nhưng "ではないか" không chứa "ではなく" nên các
# pattern dưới an toàn. Review rule v9 bắt buộc >= 2 landing (1 sớm + 1 ending);
# metric quy đổi ~3.3 điểm/landing, 3+ landing = 10.
_REFRAME_RE = re.compile(r"わけではなく|ではなくて|のではなく|ではなく|じゃなくて|じゃなく")
DIFFERENCE_MARKERS_JA = ("この違い", "その違い", "違いがある", "大きな違い")

# Gate gợi ý (plan §13): identity/behavioral/mechanism/insight >= 7,
# reframe_signature >= 6 (~2 landing), narrative_contamination <= 3.
# self_recognition đo nhưng KHÔNG gate.
SUGGESTED_FORMAT_GATE = {
    "psychological_identity": 7.0,
    "behavioral_density": 7.0,
    "mechanism_depth": 7.0,
    "insight_density": 7.0,
    "reframe_signature": 6.0,
    "narrative_contamination": 3.0,
}

_KANJI_RUN_RE = re.compile(r"[一-鿿々-〇々]{2,}|[゠-ヿ]{2,}")


def _content_tokens(text: str) -> list[str]:
    """Kanji/katakana runs (>=2 ký tự) — từ nội dung không phụ thuộc trợ từ/đuôi.

    Brief identity/signals thường là câu tiếng Nhật; matching từng run chống lại
    script chịu được cách diễn đạt khác (script paraphrase, không copy nguyên văn).
    """
    if not text:
        return []
    tokens = _KANJI_RUN_RE.findall(str(text))
    if tokens:
        return tokens
    # Fallback cho văn bản không có kanji (vd identity viết tiếng Việt): tách từ
    # theo khoảng trắng/dấu câu. Matching với script Nhật sẽ thấp — metric trung
    # thực 0 điểm, stage chỉ warning chứ không gate (chờ calibrate).
    return [
        word.strip().lower()
        for word in re.split(r"[\s、。・「」『』（）(),.:;!?！？]+", str(text))
        if len(word.strip()) >= 2
    ]


def _term_hits(script: str, terms: list[str]) -> list[str]:
    return [term for term in terms if term and term in script]


def _density_score(hits: int, script_chars: int, per_100: float = SCRIPT_METRIC_PER_100) -> float:
    if script_chars <= 0:
        return 0.0
    density = hits / (script_chars / 100.0)
    return round(min(10.0, density * per_100), 1)


def psychology_format_metrics(script: str, brief: dict, contract: dict | None = None) -> dict:
    """Plan v2 §13: psychological_identity, behavioral_density, mechanism_depth,
    self_recognition, insight_density, reframe_signature, narrative_contamination
    (0–10 mỗi chiều).

    Các metric là proxy deterministic; raw counts đi kèm để Sprint 6 calibrate.
    """
    script = script or ""
    script_chars = max(1, non_whitespace_chars(script))

    # psychological_identity: coverage token của identity trong script.
    identity_text = str(brief.get("psychological_identity", "") or "")
    if not identity_text.strip() and isinstance(contract, dict):
        identity_text = str(contract.get("psychological_identity", "") or "")
    identity_tokens = _content_tokens(identity_text)
    identity_hits = _term_hits(script, identity_tokens)
    if identity_tokens:
        psychological_identity = round(len(identity_hits) / len(identity_tokens) * 10, 1)
    else:
        psychological_identity = 0.0

    # behavioral_density: mỗi behavior signal được tính "covered" khi >= 50%
    # token nội dung của nó xuất hiện trong script.
    signals = [
        str(item) for item in brief.get("recognizable_behavior_signals", [])
        if str(item).strip()
    ]
    covered_signals = 0
    signal_details = []
    for signal in signals:
        tokens = _content_tokens(signal)
        if not tokens:
            continue
        hits = _term_hits(script, tokens)
        ratio = len(hits) / len(tokens)
        signal_details.append({"signal": signal, "token_hits": len(hits), "token_total": len(tokens), "ratio": round(ratio, 2)})
        if ratio >= 0.5:
            covered_signals += 1
    behavioral_density = round(covered_signals / len(signals) * 10, 1) if signals else 0.0

    # mechanism_depth: tên mechanism xuất hiện trong script (thuật ngữ phải được
    # gọi tên + giải thích — structure_check đã block khi thiếu tên).
    mechanism_names = [
        str(item.get("name", "")).strip()
        for item in brief.get("selected_mechanisms", [])
        if isinstance(item, dict) and str(item.get("name", "")).strip()
    ]
    mechanism_hits = _term_hits(script, mechanism_names)
    mechanism_depth = round(len(mechanism_hits) / len(mechanism_names) * 10, 1) if mechanism_names else 0.0

    # self_recognition: mật độ trực xưng người xem ("That's me." journey).
    address_hits = sum(script.count(marker) for marker in VIEWER_ADDRESS_MARKERS_JA)
    self_recognition = _density_score(address_hits, script_chars)

    # insight_density: mật độ từ vựng reframe/insight ("I never looked at it that way.").
    insight_hits = _term_hits(script, list(INSIGHT_MARKERS_JA))
    insight_density = _density_score(len(insight_hits), script_chars)

    # reframe_signature: số landing "XではなくY" — chữ ký reframe của đối thủ
    # PsychToons ("Not X. It's Y. And there's a difference."). Review rule v9 yêu
    # cầu >= 2 landing (1 sớm + 1 ending); ~3.3 điểm/landing, 3+ = 10.
    reframe_count = len(_REFRAME_RE.findall(script))
    difference_markers = _term_hits(script, list(DIFFERENCE_MARKERS_JA))
    reframe_signature = round(min(10.0, reframe_count * (10.0 / 3.0)), 1)

    # narrative_contamination: story-sequence markers + dialogue chain (càng thấp
    # càng tốt; structure_check đã block nặng trước khi stage này chạy).
    story_hits = [marker for marker in STORY_SEQUENCE_MARKERS_JA if marker in script]
    dialogue_chain = script.count("「") >= 8
    contamination_raw = len(story_hits) * 2 + (3 if dialogue_chain else 0)
    narrative_contamination = round(min(10.0, contamination_raw), 1)

    return {
        "psychological_identity": psychological_identity,
        "behavioral_density": behavioral_density,
        "mechanism_depth": mechanism_depth,
        "self_recognition": self_recognition,
        "insight_density": insight_density,
        "reframe_signature": reframe_signature,
        "narrative_contamination": narrative_contamination,
        "raw": {
            "script_chars": script_chars,
            "identity_token_hits": len(identity_hits),
            "identity_token_total": len(identity_tokens),
            "behavior_signals_covered": covered_signals,
            "behavior_signals_total": len(signals),
            "behavior_signal_details": signal_details,
            "mechanism_names": mechanism_names,
            "mechanism_names_hit": mechanism_hits,
            "viewer_address_hits": address_hits,
            "insight_marker_hits": insight_hits,
            "reframe_signature_count": reframe_count,
            "difference_marker_hits": difference_markers,
            "story_sequence_markers": story_hits,
            "dialogue_chain": dialogue_chain,
        },
    }




def _normalize_sentence(text: str) -> str:
    return re.sub(r"[^一-龿ぁ-んァ-ンA-Za-z0-9]", "", str(text or "")).lower()

def _char_ngrams(text: str, n: int = 3) -> set[str]:
    normalized = _normalize_sentence(text)
    if len(normalized) < n:
        return {normalized} if normalized else set()
    return {normalized[i:i+n] for i in range(len(normalized)-n+1)}

def psychology_quality_findings(script: str, brief: dict | None = None, contract: dict | None = None) -> dict[str, Any]:
    """Deterministic post-review quality controller. Soft/targeted findings only.

    Detects repeated propositions, delayed first insight and repetitive landing
    without pretending lexical heuristics are a full semantic judge.
    """
    text = script or ""
    sentences = [x.strip() for x in re.split(r"(?<=[。！？!?])\s*", text) if x.strip()]
    repeated_pairs: list[dict[str, Any]] = []
    seen = []
    for idx, sentence in enumerate(sentences):
        grams = _char_ngrams(sentence)
        if len(sentence) < 24 or not grams:
            continue
        for prev_idx, prev_sentence, prev_grams in seen[-24:]:
            union = len(grams | prev_grams)
            overlap = (len(grams & prev_grams) / union) if union else 0.0
            if overlap >= 0.62:
                repeated_pairs.append({"first": prev_idx, "second": idx, "similarity": round(overlap, 2)})
                break
        seen.append((idx, sentence, grams))

    insight_markers = list(INSIGHT_MARKERS_JA)
    first_insight_pos = min((text.find(marker) for marker in insight_markers if marker in text), default=-1)
    first_insight_ratio = (first_insight_pos / max(1, len(text))) if first_insight_pos >= 0 else 1.0
    ending = text[int(len(text) * 0.82):]
    ending_reframe_hits = sum(ending.count(marker) for marker in ("ではなく", "じゃなくて", "この違い", "その違い"))
    ending_insight_hits = sum(ending.count(marker) for marker in insight_markers)

    findings: list[str] = []
    if len(repeated_pairs) >= 2:
        findings.append("insight_repetition")
    if first_insight_pos < 0 or first_insight_ratio > 0.15:
        findings.append("hook_delay")

    # A common live-run failure mode: mechanism depth is high but the script
    # keeps unpacking the same proposition instead of adding new distinctions.
    brief_mechanisms = len((brief or {}).get("selected_mechanisms", [])) if isinstance(brief, dict) else 0
    if brief_mechanisms >= 1 and text:
        # Keep this as telemetry, not an automatic rewrite trigger. The live runs
        # showed that forcing insight-density repairs made scripts schematic.
        marker_hits = sum(text.count(marker) for marker in INSIGHT_MARKERS_JA)
        marker_density = marker_hits / max(1.0, len(text) / 100.0)
    if ending_reframe_hits >= 3 or ending_insight_hits >= 4:
        findings.append("ending_repetition")

    metrics = psychology_format_metrics(text, brief or {}, contract or {})
    insight_density_gap = max(
        0.0,
        SUGGESTED_FORMAT_GATE["insight_density"] - metrics["insight_density"],
    )

    return {
        "insight_repetition_count": len(repeated_pairs),
        "hook_first_insight_ratio": round(first_insight_ratio, 3),
        "ending_reframe_hits": ending_reframe_hits,
        "ending_insight_hits": ending_insight_hits,
        "marker_density": round(marker_density if text else 0.0, 3),
        "insight_density_gap": round(insight_density_gap, 1),
        "findings": findings,
        "passed": not findings,
        "raw": {"repeated_pairs": repeated_pairs[:10]},
    }

def generic_selfhelp_findings(text: str) -> list[str]:
    """Plan v2 §15: identity-flattery thuần (Bad list) là dấu hiệu generic self-help."""
    return [marker for marker in GENERIC_SELFHELP_MARKERS_JA if marker in text]


def format_gate_verdict(metrics: dict) -> tuple[bool, list[str]]:
    """Gate GỢI Ý (plan v2 §13) — chưa calibrate; stage chỉ warning khi fail."""
    failed = []
    for key, threshold in SUGGESTED_FORMAT_GATE.items():
        value = metrics.get(key, 0.0)
        if key == "narrative_contamination":
            if value > threshold:
                failed.append(key)
        elif value < threshold:
            failed.append(key)
    return (not failed, failed)


def require_fields(value: dict, fields: tuple[str, ...], label: str) -> None:
    missing = [field for field in fields if field not in value or value[field] in (None, "", [])]
    if missing:
        raise ValueError("%s thiếu field: %s" % (label, ", ".join(missing)))


def validate_topic_research(value: dict) -> None:
    require_fields(
        value,
        ("channel_positioning", "audience_pains", "content_gaps", "trend_hypotheses", "source_directions", "research_notes"),
        "topic_research",
    )
    if len(value["audience_pains"]) < 2 or len(value["content_gaps"]) < 1:
        raise ValueError("Topic research chưa đủ audience pains/content gaps.")


def validate_topic_candidates(value: dict) -> None:
    require_fields(value, ("candidates",), "topic_candidates")
    candidates = value["candidates"]
    if not 8 <= len(candidates) <= 12:
        raise ValueError("Gemini phải tạo 8-12 topic candidates.")
    seen_ids = set()
    seen_topics = set()
    for candidate in candidates:
        require_fields(
            candidate,
            ("id", "topic", "audience_moment", "core_pain", "angle", "promise", "source_person", "source_work", "source_concept", "novelty"),
            "topic candidate",
        )
        if candidate["id"] in seen_ids or candidate["topic"] in seen_topics:
            raise ValueError("Topic candidates bị trùng ID hoặc topic.")
        seen_ids.add(candidate["id"])
        seen_topics.add(candidate["topic"])


def validate_topic_selection(value: dict, candidates: dict) -> None:
    require_fields(
        value,
        ("selected_topic", "selected_candidate_id", "selection_reason", "scores", "rejected_topics", "source_person", "source_work", "source_concept", "audience_moment", "promise"),
        "topic_selection",
    )
    rows = candidates["candidates"]
    selected = next((row for row in rows if row["id"] == value["selected_candidate_id"]), None)
    if selected is None or selected["topic"] != value["selected_topic"]:
        raise ValueError("Topic được chọn phải tồn tại và khớp candidate ID.")
    # Legacy compatibility only: production now emits the duration-neutral
    # retention_fit field. Do not make new production artifacts use the old
    # 8-10 minute name again.
    scores = value["scores"]
    if "retention_8_10m" not in scores and "retention_fit" in scores:
        scores["retention_8_10m"] = scores["retention_fit"]
    weights = {
        "channel_fit": 25,
        "audience_pain": 20,
        "packaging_potential": 20,
        "retention_8_10m": 15,
        "source_strength": 10,
        "novelty": 10,
    }
    for name, maximum in weights.items():
        score = int(scores.get(name, -1))
        if not 0 <= score <= maximum:
            raise ValueError("Điểm %s phải trong khoảng 0-%d." % (name, maximum))
    expected_total = sum(int(scores[name]) for name in weights)
    if int(scores.get("total", -1)) != expected_total:
        raise ValueError("Tổng điểm topic selection không khớp các thành phần.")


def validate_source_pack(value: dict) -> None:
    require_fields(
        value,
        (
            "audience_moment",
            "central_emotion",
            "core_self_insight",
            "source_person",
            "source_work",
            "source_concept",
            "verified_sources",
            "forbidden_attributions",
            "editorial_application",
        ),
        "source_pack",
    )
    for source in value["verified_sources"]:
        if not isinstance(source, dict) or not source.get("url"):
            raise ValueError("Mỗi verified source phải có URL.")
        if source["url"] not in KNOWN_SOURCE_URLS:
            raise ValueError("Source URL chưa nằm trong catalog đã xác minh: %s" % source["url"])


def validate_contract(value: dict) -> None:
    """Compatibility entry point for the canonical symbolic-long-form lock."""
    _validate_contract_canonical(value)


def unsupported_source_claims(text: str, source_pack: dict) -> list[str]:
    """Return sensitive claim markers absent from all verified source evidence."""
    source_evidence = " ".join(
        [
            str(source_pack.get("source_concept", "")),
            str(source_pack.get("editorial_application", "")),
            *[str(item) for item in source_pack.get("allowed_paraphrases", [])],
            *[
                "%s %s" % (source.get("title", ""), source.get("supports", ""))
                for source in source_pack.get("verified_sources", [])
                if isinstance(source, dict)
            ],
        ]
    ).lower()
    lowered = text.lower()
    return [
        marker
        for marker in SENSITIVE_CLAIM_MARKERS
        if marker.lower() in lowered and marker.lower() not in source_evidence
    ]


def validate_plan(
    value: dict,
    source_pack: dict | None = None,
    psychology_brief: dict | None = None,
) -> None:
    require_fields(value, ("retention_blueprint", "sections", "hook_draft", "planning_quality_gate"), "planning")
    sections = value["sections"]
    if not 5 <= len(sections) <= 7:
        raise ValueError("Planning phải có 5-7 movements; ưu tiên 5-6 khi đã đủ information gain.")
    mechanisms_seen: set[str] = set()
    for section in sections:
        require_fields(
            section,
            (
                "id", "psychological_job", "behavior_link", "why_answered",
                "example_budget", "new_information", "state_advance", "so_what_next",
                "segment_function",
            ),
            "planning section",
        )
        if "mechanisms_used" not in section or not isinstance(section["mechanisms_used"], list):
            raise ValueError("planning section.mechanisms_used phải là danh sách (có thể rỗng).")
        if "->" not in section["state_advance"] and "→" not in section["state_advance"]:
            raise ValueError("state_advance phải mô tả before -> after.")
        budget = section["example_budget"]
        if not isinstance(budget, int) or not 0 <= budget <= 2:
            raise ValueError("example_budget mỗi section phải là số nguyên 0-2.")
        mechanisms_seen.update(str(item) for item in section["mechanisms_used"])
    if sum(int(section["example_budget"]) for section in sections) > 4:
        raise ValueError("Planning dành quá nhiều ngân sách cho examples; example chỉ là evidence phụ.")
    gates = (
        "first_insight_before_30s", "first_major_payoff_before_5m",
        "no_duplicate_sections", "every_section_advances_state",
        "psychology_is_spine", "no_plot_or_character_arc", "ending_creates_self_understanding",
    )
    if not all(bool(value["planning_quality_gate"].get(key)) for key in gates):
        raise ValueError("Planning psychology-first quality gate chưa pass.")
    if psychology_brief is not None:
        core_question = str(value.get("core_question", "")).strip()
        if not core_question:
            core_question = str(psychology_brief.get("core_psychological_question", "")).strip()
            if core_question:
                value["core_question"] = core_question
        if not core_question:
            raise ValueError("Planning phải khóa đúng một core_question.")
        expected = {str(item["name"]) for item in psychology_brief["selected_mechanisms"]}
        if not expected.issubset(mechanisms_seen):
            raise ValueError("Planning chưa cover selected mechanisms: %s" % ", ".join(sorted(expected - mechanisms_seen)))
        if psychology_brief["origin_status"] in {"unsupported", "irrelevant", "skip"}:
            if any(str(section["segment_function"]).lower() == "origin_development" for section in sections):
                raise ValueError("Planning dùng origin/development dù psychology brief yêu cầu bỏ qua.")
    if source_pack is not None:
        import json
        # optional_reason/redundancy_risks là meta-commentary (lý do chọn/skip section,
        # rủi ro lặp ý), không phải claim của script — AI có thể nhắc khái niệm bị
        # loại ở đó (vd "origin bỏ vì 幼少期 không có source") mà không vi phạm.
        plan_copy = json.loads(json.dumps(value))
        for section in plan_copy.get("sections", []):
            section.pop("optional_reason", None)
        plan_copy.pop("redundancy_risks", None)
        unsupported = unsupported_source_claims(json.dumps(plan_copy, ensure_ascii=False), source_pack)
        if unsupported:
            raise ValueError(
                "Planning chứa cơ chế khoa học/tuổi thơ chưa có verified source: %s. "
                "Source pack phải được mở rộng trước, hoặc bỏ cơ chế này khỏi plan."
                % ", ".join(unsupported)
            )


def normalize_audit_score(value: dict) -> int:
    """Đưa overall_score về thang 0-100.

    Prompt yêu cầu thang 0-100 nhưng DeepSeek vẫn hay trả thang 1-10 (quan sát
    thực tế: deepseek=9 trong khi gemini=100 cho cùng một script). Điểm <= 10 đi
    kèm decision="pass" chỉ có thể là thang 1-10, nên quy đổi x10; decision và
    các gate có cấu trúc bên dưới vẫn là chốt chặn thật.
    """
    try:
        score = int(float(value.get("overall_score", 0)))
    except (TypeError, ValueError):
        return 0
    if 0 < score <= 10:
        return score * 10
    return score


def normalize_score_0_10(raw: Any) -> float | None:
    """Coerce một điểm con của score_report về float 0-10.

    Gemini hay trả điểm dạng string ("7"), thang 0-100 lạc vào một mục, hoặc
    null khi không đánh giá. score_report chỉ là thông tin tham khảo (các gate
    thật của review là decision/revised_draft_clean/char_report) nên không bao
    giờ chết run vì nó. Trả None khi không parse được gì.
    """
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return max(0.0, min(10.0, value))


def audit_passes(value: dict) -> bool:
    """Compatibility gate matching the production rule-based audit policy."""
    return (
        bool(value.get("source_alignment"))
        and bool(value.get("outline_coverage"))
        and bool(value.get("title_alignment"))
        and not value.get("unsupported_claims")
        and not value.get("missing_outline_points")
    )


def _luminance(hex_color: str) -> float:
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", hex_color):
        raise ValueError("Màu phải ở dạng #RRGGBB.")
    values = [int(hex_color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4 for value in values]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(first: str, second: str) -> float:
    high, low = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def title_overlap_percent(title: str, thumbnail_text: str) -> float:
    title_chars = set(re.sub(r"[\s\W_]", "", title))
    thumb_chars = set(re.sub(r"[\s\W_]", "", thumbnail_text))
    if not thumb_chars:
        return 0.0
    return len(title_chars & thumb_chars) / len(thumb_chars) * 100


def derive_visual_density_targets(contract: dict, plan: dict) -> dict[str, int]:
    """Derive minimum coverage from duration instead of a fixed image quota."""
    duration_text = str(contract.get("target_duration_minutes", "9-11"))
    def _minutes(value: str) -> float | None:
        match = re.fullmatch(r"(\d+)(?::(\d{1,2}))?", value.strip())
        if not match:
            return None
        return float(match.group(1)) + float(match.group(2) or 0) / 60.0

    parts = re.split(r"\s*[-–]\s*", duration_text)
    parsed = [_minutes(part) for part in parts]
    parsed = [value for value in parsed if value is not None]
    duration_minutes = sum(parsed) / len(parsed) if parsed else 9.0
    duration_seconds = max(60, int(round(duration_minutes * 60)))

    # Front-loaded schedule: denser opening, progressively slower later.
    remaining = duration_seconds
    visual_events = 0
    for window_seconds, seconds_per_event in (
        (30, 6),
        (60, 8),
        (210, 12),
        (max(0, duration_seconds - 360), 16),
        (60, 20),
    ):
        active = min(remaining, window_seconds)
        if active > 0:
            visual_events += math.ceil(active / seconds_per_event)
            remaining -= active
    section_floor = len(plan.get("sections", [])) * 5
    visual_events = max(visual_events, section_floor, 1)
    # ~85% beats carry their own image; reuse only for deliberate callbacks
    # and the end card (mỗi cảnh hiển thị ngắn + Ken Burns → video đỡ nhàm,
    # thay vì tốn credit gen video AI).
    unique_images = max(1, math.ceil(visual_events * 0.85))
    return {
        "duration_seconds_reference": duration_seconds,
        "minimum_visual_events": visual_events,
        "minimum_unique_images": unique_images,
    }


def validate_image_strategy(
    value: dict,
    contract: dict | None = None,
    plan: dict | None = None,
) -> None:
    require_fields(value, ("estimated_unique_images", "estimated_total_visual_events", "density_check", "no_filler_check", "visual_beats", "opening_visual_contract"), "image_strategy")
    beats = value["visual_beats"]
    if not isinstance(beats, list) or not beats:
        raise ValueError("Image strategy phải có ít nhất một visual beat.")
    beat_to_image: dict[str, str] = {}
    image_index = 0
    # Pass 1: gán image_id cho mọi beat new_image trước, để pass 2 resolve reuse
    # theo cả beat ID lẫn image ID (chuẩn hóa định dạng như "img_01"/"IMG01").
    for beat in beats:
        require_fields(
            beat,
            ("id", "script_section", "visual_information", "mode", "new_image"),
            "visual beat",
        )
        beat_id = str(beat["id"])
        if beat_id in beat_to_image:
            raise ValueError("Visual beat ID bị trùng: %s" % beat_id)
        if bool(beat["new_image"]):
            image_index += 1
            beat["image_id"] = "IMG-%02d" % image_index
            beat["reuse_image_id"] = None

    def _norm(ref: str) -> str:
        return "".join(ch for ch in ref.lower() if ch.isalnum())

    image_id_by_norm = {_norm(str(beat["image_id"])): str(beat["image_id"]) for beat in beats if bool(beat["new_image"])}
    # Pass 2: beat reuse trỏ theo beat ID (beat đã xử lý) hoặc image ID (bất kỳ hướng).
    for beat in beats:
        beat_id = str(beat["id"])
        if bool(beat["new_image"]):
            beat_to_image[beat_id] = str(beat["image_id"])
            continue
        reuse_ref = str(beat.get("reuse_image_id") or "")
        image_id = beat_to_image.get(reuse_ref) or image_id_by_norm.get(_norm(reuse_ref))
        if not image_id:
            raise ValueError(
                "Beat %s reuse ảnh không tồn tại: %s (reuse theo beat ID trước đó hoặc image ID của beat new_image)" % (beat_id, reuse_ref)
            )
        beat["image_id"] = image_id
        beat["reuse_image_id"] = image_id
        beat_to_image[beat_id] = image_id
    value["estimated_unique_images"] = image_index
    value["estimated_total_visual_events"] = len(beats)
    if contract is not None and plan is not None:
        targets = derive_visual_density_targets(contract, plan)
        value["density_targets"] = targets
        if len(beats) < targets["minimum_visual_events"]:
            raise ValueError(
                "Image strategy quá thưa: %d visual events, cần tối thiểu %d theo duration/sections."
                % (len(beats), targets["minimum_visual_events"])
            )
        if image_index < targets["minimum_unique_images"]:
            raise ValueError(
                "Image strategy reuse quá nhiều: %d ảnh unique, cần tối thiểu %d theo density động."
                % (image_index, targets["minimum_unique_images"])
            )
        # Trần unique ~85% beats — chặn lạm dụng ảnh mới cho mọi beat (lỗi live
        # run video-08: 64 unique cho 64 events → events_per_image 1.0 < 1.30,
        # lãng phí ~50% credit gen ảnh). Reuse dành cho callback/end card.
        max_unique = max(1, math.ceil(len(beats) * 0.85))
        if image_index > max_unique:
            raise ValueError(
                "Image strategy lạm dụng ảnh mới: %d unique cho %d events (tối đa %d = ceil(events × 0.85)); reuse cho deliberate callback/end card."
                % (image_index, len(beats), max_unique)
            )
    if not value["density_check"] or not value["no_filler_check"]:
        raise ValueError("Image strategy density/no-filler gate chưa pass.")


def normalize_image_prompts(value: dict, strategy: dict | None = None) -> None:
    """Normalize provider output and complete truncated prompt responses."""
    for image in value.get("images", []):
        prompt = str(image.get("prompt", "")).strip()
        lowered = prompt.lower()
        additions = []
        if "16:9" not in lowered:
            additions.append("16:9 full bleed composition.")
        if "flat illustrated" not in lowered:
            additions.append("Flat illustrated cartoon style, thick black outline, solid colors, no gradients, navy #1A2332 background.")
        if "negative:" not in lowered:
            additions.append("Negative: text, logo, watermark, extra fingers, distorted hands, duplicate subjects.")
        image["prompt"] = " ".join([prompt, *additions]).strip()
    if not isinstance(strategy, dict):
        return
    beats = strategy.get("visual_beats") or []
    expected_images = [beat for beat in beats if bool(beat.get("new_image"))]
    existing = {
        str(image.get("image_id")): image
        for image in value.get("images", [])
        if str(image.get("image_id", ""))
    }
    images = []
    for beat in expected_images:
        image_id = str(beat["image_id"])
        image = existing.get(image_id)
        if image is None:
            visual = str(beat.get("visual_information", "psychology visual beat")).strip()
            image = {
                "image_id": image_id,
                "beat_ids": [str(beat["id"])],
                "prompt": (
                    "Japanese psychology illustration: %s. Anonymous recurring character or simple visual metaphor, "
                    "clear readable action, flat illustrated cartoon, thick black outline, solid colors, no gradients, "
                    "navy #1A2332 background, 16:9 full bleed. Negative: text, logo, watermark, photorealism, clutter."
                ) % visual,
            }
        image.setdefault("beat_ids", [str(beat["id"])])
        images.append(image)
    value["images"] = images
    existing_storyboard = {
        str(row.get("beat_id")): row
        for row in value.get("storyboard", [])
        if str(row.get("beat_id", ""))
    }
    image_by_beat = {str(beat["id"]): str(beat["image_id"]) for beat in beats}
    storyboard = []
    for index, beat in enumerate(beats, start=1):
        beat_id = str(beat["id"])
        row = dict(existing_storyboard.get(beat_id) or {})
        row.update({
            "event_id": "E%02d" % index,
            "time": row.get("time") or beat.get("time", "DRAFT_TIMING"),
            "beat_id": beat_id,
            "image_id": image_by_beat[beat_id],
            "new_image": bool(beat.get("new_image")),
            "motion": row.get("motion") or ("slow push-in" if index % 2 else "gentle pan"),
            "visual_information": row.get("visual_information") or str(beat.get("visual_information", "psychology visual beat")),
        })
        storyboard.append(row)
    value["storyboard"] = storyboard


def validate_prompt_pack(value: dict, strategy: dict) -> dict[str, Any]:
    require_fields(value, ("images", "storyboard"), "image_prompt_pack")
    validate_image_strategy(strategy)
    beats = strategy["visual_beats"]
    expected_ids = [beat["image_id"] for beat in beats if bool(beat["new_image"])]
    expected = len(expected_ids)
    images = value["images"]
    storyboard = value["storyboard"]
    issues = []
    if len(images) != expected:
        issues.append("Prompt count %d không khớp expected %d." % (len(images), expected))
    ids = {image.get("image_id") for image in images}
    missing_ids = [image_id for image_id in expected_ids if image_id not in ids]
    extra_ids = sorted(str(image_id) for image_id in ids if image_id not in set(expected_ids))
    if missing_ids:
        issues.append("Thiếu image IDs: %s." % ", ".join(missing_ids))
    if extra_ids:
        issues.append("Thừa image IDs: %s." % ", ".join(extra_ids))
    for image in images:
        prompt = str(image.get("prompt", ""))
        lowered = prompt.lower()
        if not all(token in lowered for token in ("16:9", "flat illustrated", "negative:")):
            issues.append("Prompt %s chưa self-contained." % image.get("image_id"))
    expected_by_beat = {beat["id"]: beat["image_id"] for beat in beats}
    storyboard_beats = []
    for row in storyboard:
        storyboard_beats.append(row.get("beat_id"))
        if row.get("image_id") not in ids:
            issues.append("Storyboard trỏ tới image không tồn tại: %s" % row.get("image_id"))
        expected_image = expected_by_beat.get(row.get("beat_id"))
        if expected_image is None:
            issues.append("Storyboard trỏ tới beat không tồn tại: %s" % row.get("beat_id"))
        elif row.get("image_id") != expected_image:
            issues.append("Beat %s phải dùng %s, không phải %s." % (row.get("beat_id"), expected_image, row.get("image_id")))
        if not row.get("visual_information"):
            issues.append("Storyboard event thiếu visual_information.")
    expected_beats = [beat["id"] for beat in beats]
    if storyboard_beats != expected_beats:
        issues.append("Storyboard phải có đúng một event cho mỗi visual beat theo đúng thứ tự.")
    ratio = len(storyboard) / len(images) if images else 0
    return {"unique_images": len(images), "visual_events": len(storyboard), "events_per_image": round(ratio, 2), "issues": issues, "passed": not issues}


# Cảnh chữ/typography/infographic không nên gen video (image-to-video từ ảnh
# tĩnh sẽ méo chữ). Dùng CỤM từ cho caption — token đơn "caption" vướng dòng
# negative "English captions…" trong prompt cinematic.
TEXT_SCENE_BLOCKLIST = (
    "typography", "infographic", "flowchart", "diagram", "symbol", "icon",
    "graphic", "text overlay", "panel", "split screen", "split-screen",
    "title card", "end card",
    "caption reads", "caption below", "caption beneath",
    "caption at the bottom", "caption over", "caption under",
)

# Từ hành động → ảnh có người/đạo cụ động → gen video sẽ sống động hơn.
ACTION_WORDS = ("scholar", "worker", "hand", "pen", "book", "scale",
                "bubble", "speech", "ticking", "checklist")

# select_video_candidates được re-export từ resource_pack.validation (canonical)
# ở đầu file — bản duplicate tại đây đã bị xóa để hai đường import không lệch code.
