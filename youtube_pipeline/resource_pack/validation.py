from __future__ import annotations

import math
import re
import unicodedata
from typing import Any

from .claim_ledger import source_supports_reinforcement_loop

from .metrics import non_whitespace_chars
from .source_catalog import KNOWN_SOURCE_URLS


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

# Briefs may use Vietnamese labels while the spoken production script uses
# Japanese. Localized aliases keep the contract stable without foreign tokens
# leaking into narration.
MECHANISM_ALIASES = {
    "phantachnhiemvu": ("課題の分離", "課題を分ける", "相手の課題", "自分の課題"),
    "課題の分離": ("課題の分離", "課題を分ける", "相手の課題", "自分の課題"),
    "responsibilityseparation": ("課題の分離", "責任を分ける", "相手の責任", "自分の責任"),
}


def _mechanism_key(value: object) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^0-9a-zA-Zぁ-んァ-ン一-龯]", "", ascii_text or normalized).lower()


def mechanism_terms(item: dict[str, Any]) -> tuple[str, ...]:
    name = str(item.get("name", "")).strip()
    return tuple(dict.fromkeys((name, *MECHANISM_ALIASES.get(_mechanism_key(name), ())))) if name else ()


def mechanism_is_covered(script: str, item: dict[str, Any]) -> bool:
    """Accept a localized mechanism label when its canonical alias is explained."""
    terms = mechanism_terms(item)
    if any(term and term in script for term in terms):
        return True
    name = str(item.get("name", ""))
    families = []
    if any(term in name for term in ("状況", "手がかり", "文脈", "環境")):
        families.append(("context", ("状況", "手がかり", "環境", "合図")))
    if any(term in name for term in ("習慣", "反復", "ルーティン")):
        families.append(("repetition", ("習慣", "反復", "繰り返", "いつもの")))
    if any(term in name for term in ("反応", "起動", "自動")):
        families.append(("response", ("反応", "起動", "行動", "始まり")))
    hits = sum(1 for _family, terms in families if any(term in script for term in terms))
    return len(families) >= 2 and hits >= 2

# Deterministic warning signals, deliberately narrow to avoid flagging ordinary
# behavioral examples. Semantic review remains the authoritative story-dominance gate.
STORY_SEQUENCE_MARKERS_JA = (
    "ドアが開", "部屋に入", "窓の外を見", "その後", "翌日", "思い出した",
    "歩いてい", "振り返ると",
)

# Scene-first opening signals. These are intentionally narrower than STORY_SEQUENCE_MARKERS_JA:
# a topic may legitimately mention LINE/smartphone, but the hook must not begin by
# narrating a scene and only reveal the psychology later.
HOOK_SCENE_START_MARKERS_JA = (
    "夜、", "朝、", "昼、", "会議室", "布団の中", "ベッドの中",
    "スマホを開", "スマホを見", "LINEを送", "LINEを開", "ドアが閉",
    "部屋に入", "窓の外",
)
HOOK_PSYCHOLOGY_MARKERS_JA = (
    "なぜ", "こういう人", "このタイプ", "心理", "傾向", "思い込み",
    "仕組み", "正体", "無意識", "実は", "あなたは", "人がいます",
    "人もいます", "〜してしまう", "してしまう人",
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
    require_fields(
        value,
        (
            "phenomenon_or_type", "psychological_identity",
            "core_psychological_question", "main_tension",
            "recognizable_behavior_signals", "common_misconception", "early_reframe",
            "mechanism_candidates", "selected_mechanisms", "causal_chain",
            "inner_process_map", "origin_status", "strength_status", "cost_status",
            "practical_shift_status", "route", "exclusions",
        ),
        "psychology_brief",
    )
    if value["route"] not in PSYCHOLOGY_ROUTES:
        raise ValueError("psychology_brief.route không hợp lệ.")
    if not 3 <= len(value["recognizable_behavior_signals"]) <= 6:
        raise ValueError("Psychology brief phải có 3-6 behavior signals.")
    selected = value["selected_mechanisms"]
    if not 1 <= len(selected) <= 2:
        raise ValueError("Chỉ chọn 1-2 psychological mechanisms cho một video.")
    for mechanism in selected:
        require_fields(
            mechanism,
            ("name", "role", "behavior_explained", "why", "inner_process", "evidence_status"),
            "selected mechanism",
        )
    for field in ("origin_status", "strength_status", "cost_status", "practical_shift_status"):
        if value[field] not in OPTIONAL_STATUSES:
            raise ValueError("%s có status không hợp lệ." % field)
    if source_pack is not None:
        unsupported = unsupported_source_claims(_brief_claim_text(value), source_pack)
        if unsupported:
            raise ValueError(
                "Psychology brief chứa claim ngoài source pack: %s. "
                "Các khái niệm này chỉ được xuất hiện trong mechanism_candidates/"
                "exclusions/common_misconception, không trong selected_mechanisms/"
                "psychological_identity/early_reframe/causal_chain/inner_process_map."
                % ", ".join(unsupported)
            )


def anti_story_findings(text: str) -> list[str]:
    """Return deterministic story warnings; does not diagnose semantic quality."""
    findings = []
    hits = [marker for marker in STORY_SEQUENCE_MARKERS_JA if marker in text]
    if len(hits) >= 3:
        findings.append("sequential_story_markers: " + ", ".join(hits))
    # Count substantial quoted utterances, not short labels such as 「課題の分離」
    # or 「いいですよ」. The old raw quote counter rejected valid direct narration.
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

# Diagnostic semantic scorecard. Production review uses concrete editorial
# findings; these thresholds are retained for telemetry/backward compatibility
# and are not a rewrite quota.
PSYCHOLOGY_REVIEW_GATE = {
    "psychology_spine_min": 7.0,
    "mechanism_depth_min": 7.0,
    "insight_density_min": 6.0,
    "recognition_min": 6.0,
    "story_dominance_max": 3.0,
    "example_dependency_max": 3.0,
    "reframe_signature_min": 0,
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
    mechanism_hits = [
        name for item, name in zip(brief.get("selected_mechanisms", []), mechanism_names)
        if isinstance(item, dict) and mechanism_is_covered(script, item)
    ]
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


def psychology_review_gate_verdict(review: dict) -> tuple[bool, list[str]]:
    """Return a diagnostic semantic scorecard verdict for compatibility.

    Scores come from the LLM reviewer because deterministic lexical metrics cannot
    reliably distinguish a psychology explanation from a story with psychology
    commentary. Missing scorecard fields fail closed; production does not use
    this verdict as an automatic rewrite trigger.
    """
    scorecard = review.get("psychology_scorecard")
    if not isinstance(scorecard, dict):
        return False, ["missing_psychology_scorecard"]

    failed: list[str] = []
    lower_bounds = {
        "psychology_spine": PSYCHOLOGY_REVIEW_GATE["psychology_spine_min"],
        "mechanism_depth": PSYCHOLOGY_REVIEW_GATE["mechanism_depth_min"],
        "insight_density": PSYCHOLOGY_REVIEW_GATE["insight_density_min"],
        "recognition": PSYCHOLOGY_REVIEW_GATE["recognition_min"],
    }
    for key, minimum in lower_bounds.items():
        raw = scorecard.get(key)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            failed.append(key)
            continue
        if value < minimum:
            failed.append(key)

    for key, maximum in (
        ("story_dominance", PSYCHOLOGY_REVIEW_GATE["story_dominance_max"]),
        ("example_dependency", PSYCHOLOGY_REVIEW_GATE["example_dependency_max"]),
    ):
        raw = scorecard.get(key)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            failed.append(key)
            continue
        if value > maximum:
            failed.append(key)

    raw_reframe = scorecard.get("reframe_signature_count")
    try:
        reframe_count = int(raw_reframe)
    except (TypeError, ValueError):
        failed.append("reframe_signature_count")
    else:
        if reframe_count < PSYCHOLOGY_REVIEW_GATE["reframe_signature_min"]:
            failed.append("reframe_signature_count")
    return (not failed, failed)


def psychology_hook_findings(text: str) -> list[str]:
    """Detect a slow hook before review, without turning lexical style into a hard gate."""
    opening = str(text or "").strip()[:420]
    if not opening:
        return ["empty_opening"]
    lines = [line.strip() for line in re.split(r"[。！？\n]", opening) if line.strip()]
    if not lines:
        return ["empty_opening"]
    scene_hits = [line for line in lines[:3] if any(marker in line for marker in HOOK_SCENE_START_MARKERS_JA)]
    psychology_hits = [line for line in lines[:4] if any(marker in line for marker in HOOK_PSYCHOLOGY_MARKERS_JA)]
    if len(scene_hits) >= 2 and not psychology_hits:
        return ["opening_scene_led_without_early_psychological_pivot"]
    # Psychology Direct needs more than recognition: the first few lines must
    # expose the felt contradiction and leave one mechanism-led question open.
    # This only requests the editor's single targeted polish pass; it never
    # blocks production because Japanese can express the same idea many ways.
    early = "。".join(lines[:6])
    has_contradiction = any(marker in early for marker in ("のに", "なのに", "それでも", "本当は", "なのに"))
    has_open_loop = any(marker in early for marker in ("なぜ", "どうして", "でしょうか", "のか"))
    if not (has_contradiction and has_open_loop):
        return ["opening_lacks_pain_contradiction_or_open_loop"]
    return []


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


def script_quality_gate_report(
    script: str,
    brief: dict | None = None,
    contract: dict | None = None,
    review: dict | None = None,
) -> dict[str, Any]:
    """Return the unified post-review quality report used by integrations.

    Deterministic format metrics are advisory. Story-sequence findings are the
    only blocking condition because they directly violate the psychology-first
    format and can be acted on without inventing new claims.
    """
    text = str(script or "")
    brief = brief if isinstance(brief, dict) else {}
    contract = contract if isinstance(contract, dict) else {}
    metrics = psychology_format_metrics(text, brief, contract)
    _format_ok, format_warnings = format_gate_verdict(metrics)
    issues = anti_story_findings(text)
    # LLM scorecards and lexical metrics are diagnostics only. They must not
    # turn a low proxy score into an automatic rewrite request.
    return {
        "decision": "repair" if issues else "pass",
        "issues": issues,
        "warnings": format_warnings,
        "metrics": metrics,
    }


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

        # Optional v2 fields: prompt mới có thể cung cấp chúng, nhưng validator
        # không bắt buộc để giữ backward compatibility với candidate artifacts cũ.
        # Khi có mặt, chúng phải mô tả psychological subject trước situation.
        pattern = str(candidate.get("psychological_pattern", "")).strip()
        manifestations = candidate.get("behavioral_manifestations")
        if pattern and len(pattern) < 8:
            raise ValueError("psychological_pattern của topic candidate quá ngắn.")
        if manifestations is not None:
            if not isinstance(manifestations, list) or not 2 <= len(manifestations) <= 6:
                raise ValueError("behavioral_manifestations phải là danh sách 2-6 behavior.")
        if pattern and str(candidate.get("audience_moment", "")).strip() == pattern:
            raise ValueError("audience_moment không được lặp lại psychological_pattern.")


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
    scores = value["scores"]
    # Migrate artifacts generated before retention became duration-neutral.
    if "retention_fit" not in scores and "retention_8_10m" in scores:
        scores["retention_fit"] = scores.pop("retention_8_10m")
    weights = {
        "channel_fit": 25,
        "audience_pain": 20,
        "packaging_potential": 20,
        "retention_fit": 15,
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
        if not isinstance(source, dict) or not source.get("title") or not source.get("url"):
            raise ValueError("Mỗi verified source phải có title và URL.")
        if not str(source.get("supports", "")).strip():
            raise ValueError("Mỗi verified source phải mô tả claim được hỗ trợ trong supports.")
        if source["url"] not in KNOWN_SOURCE_URLS:
            raise ValueError("Source URL chưa nằm trong catalog đã xác minh: %s" % source["url"])


def validate_publish_draft(value: dict) -> None:
    """Validate the copy package before it is written to the publish sheet."""
    require_fields(
        value,
        ("description_draft", "chapters_status", "pinned_comment", "hashtags", "tags", "source_note"),
        "publish_draft",
    )
    if value["chapters_status"] != "DRAFT_OMITTED":
        raise ValueError("Phase 1 không được bịa chapters trước audio thật.")
    if len(str(value["description_draft"]).strip()) < 120:
        raise ValueError("Description draft phải có ít nhất 120 ký tự tiếng Nhật.")
    if len(value["hashtags"]) > 5:
        raise ValueError("Description chỉ được tối đa 5 hashtags.")
    if not isinstance(value["tags"], list) or not value["tags"]:
        raise ValueError("Publish draft phải có tags tiếng Nhật.")


def validate_contract(value: dict) -> None:
    require_fields(
        value,
        (
            "single_core_promise", "psychological_identity",
            "core_psychological_question", "main_tension", "route",
            "selected_mechanisms", "title_candidates", "chosen_title",
            "target_char_min", "target_char_max", "hook_contract", "thumbnail_brief",
            "format_lock",
        ),
        "script_contract",
    )
    # Phase 4 (plan v2 §6): contract phải khóa FORMAT, không chỉ psychology —
    # primary format là psychological profile/deep-dive, forbidden spine là các
    # dạng narrative. Planning/writing/review/QA đều kế thừa lock này.
    lock = value["format_lock"]
    if not isinstance(lock, dict):
        raise ValueError("script_contract.format_lock phải là object.")
    require_fields(
        lock,
        ("primary_format", "content_center", "primary_narration", "secondary_device", "forbidden_spine"),
        "script_contract.format_lock",
    )
    if "psychological" not in str(lock["primary_format"]).lower():
        raise ValueError("format_lock.primary_format phải là psychological profile / deep-dive.")
    content_center = str(lock["content_center"]).lower()
    primary_narration = str(lock["primary_narration"]).lower()
    secondary_device = str(lock["secondary_device"]).lower()
    # Japanese providers often express the same lock as 心理的パターン or
    # 行動傾向. Accept those semantic anchors without accepting a bare scene.
    content_center_markers = (
        "behavior", "pattern", "kiểu người", "psychological",
        "心理", "行動傾向", "行動パターン", "思考パターン",
        "認知パターン", "心理傾向", "心理構造", "内的プロセス",
    )
    if not any(term in content_center for term in content_center_markers):
        raise ValueError("format_lock.content_center phải khóa psychological pattern/behavior, không phải scene/story.")
    if not any(term in primary_narration for term in ("direct", "psychological", "explanation", "analysis")):
        raise ValueError("format_lock.primary_narration phải là direct psychological explanation/analysis.")
    if not any(term in secondary_device for term in ("example", "behavior", "micro")):
        raise ValueError("format_lock.secondary_device phải giới hạn example/behavior như thiết bị phụ.")
    if not isinstance(lock["forbidden_spine"], list) or len(lock["forbidden_spine"]) < 3:
        raise ValueError("format_lock.forbidden_spine phải liệt kê ít nhất 3 forbidden spine.")
    if len(value["title_candidates"]) != 3:
        raise ValueError("Script contract phải có đúng 3 title candidates.")
    for candidate in value["title_candidates"]:
        actual = len(str(candidate.get("title", "")))
        if not 18 <= actual <= 28:
            raise ValueError("Mỗi title candidate phải dài 18-28 ký tự.")
        candidate["char_count"] = actual
    title_count = len(value["chosen_title"])
    if not 18 <= title_count <= 28:
        raise ValueError("Chosen title phải dài 18-28 ký tự; hiện tại %d." % title_count)
    value["chosen_title_char_count"] = title_count
    try:
        target_min = int(value["target_char_min"])
        target_max = int(value["target_char_max"])
    except (TypeError, ValueError) as exc:
        raise ValueError("Target ký tự phải là số nguyên dương.") from exc
    if target_min <= 0 or target_max < target_min:
        raise ValueError("Target ký tự không hợp lệ.")


def normalize_contract_format_lock(value: dict) -> bool:
    """Make format-lock metadata deterministic rather than provider-wording fragile.

    ``format_lock`` constrains downstream writing; it is not creative content.
    A provider may describe the exact intended constraint as e.g. "short
    illustrative situations", which should never terminate a Run Live merely
    because it omits the English token ``example``. Preserve valid wording and
    normalize only missing/invalid metadata to the safe production lock.
    """
    lock = value.get("format_lock")
    if not isinstance(lock, dict):
        lock = {}
        value["format_lock"] = lock
    changed = False

    def set_if_invalid(key: str, valid: bool, fallback: object) -> None:
        nonlocal changed
        if not valid:
            lock[key] = fallback
            changed = True

    primary = str(lock.get("primary_format", "")).lower()
    set_if_invalid(
        "primary_format",
        "psychological" in primary,
        "psychological profile / psychological deep-dive",
    )
    content = str(lock.get("content_center", "")).lower()
    content_markers = (
        "behavior", "pattern", "kiểu người", "psychological", "心理", "行動傾向",
        "行動パターン", "思考パターン", "認知パターン", "心理傾向", "心理構造", "内的プロセス",
    )
    identity = str(value.get("psychological_identity", "")).strip()
    set_if_invalid(
        "content_center",
        any(term in content for term in content_markers),
        "心理的パターン: " + identity if identity else "心理的パターンと行動傾向",
    )
    narration = str(lock.get("primary_narration", "")).lower()
    set_if_invalid(
        "primary_narration",
        any(term in narration for term in ("direct", "psychological", "explanation", "analysis")),
        "direct psychological explanation / analysis",
    )
    secondary = str(lock.get("secondary_device", "")).lower()
    set_if_invalid(
        "secondary_device",
        any(term in secondary for term in ("example", "behavior", "micro")),
        "behavioral micro-examples used only for recognition and evidence",
    )
    forbidden = lock.get("forbidden_spine")
    set_if_invalid(
        "forbidden_spine",
        isinstance(forbidden, list) and len(forbidden) >= 3,
        ["narrative story", "personal anecdote", "cinematic monologue", "fictional character journey"],
    )
    return changed


def normalize_review_list(value: object) -> list[str]:
    """Coerce reviewer list drift into the stable ``list[str]`` contract.

    Gemini sometimes returns ``issues``/``required_changes`` as objects such
    as ``{"issue": "...", "reason": "..."}``, or as one string. These are
    still usable editorial findings; rejecting the whole run is unnecessary
    schema brittleness. Preserve the useful text deterministically and leave
    content/source decisions to the existing audit stages.
    """
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    normalized: list[str] = []
    for item in items:
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            parts = []
            for key in ("issue", "claim", "reason", "message", "description", "text"):
                candidate = item.get(key)
                if candidate is not None and str(candidate).strip():
                    parts.append(str(candidate).strip())
            text = " — ".join(dict.fromkeys(parts))
            if not text:
                text = json.dumps(item, ensure_ascii=False, sort_keys=True)
        else:
            text = str(item).strip()
        if text:
            normalized.append(text)
    return normalized


def normalize_contract_titles(value: dict) -> None:
    """Repair title packaging length after the model's targeted correction."""
    minimum, maximum = 18, 28
    suffix = "の心理とは？その理由"

    def _normalize(raw: object) -> str:
        title = str(raw or "").strip()
        if len(title) > maximum:
            return title[:maximum].rstrip()
        if len(title) < minimum:
            title = (title + suffix)[:maximum]
            while len(title) < minimum:
                title += "？"
        return title

    candidates = value.get("title_candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            if isinstance(candidate, dict):
                candidate["title"] = _normalize(candidate.get("title"))
                candidate["char_count"] = len(candidate["title"])
    if "chosen_title" in value:
        value["chosen_title"] = _normalize(value.get("chosen_title"))
        value["chosen_title_char_count"] = len(value["chosen_title"])


def normalize_title_hook_contract(value: dict) -> bool:
    """Ensure the packaging promise has inspectable anchors for the cold open."""
    raw = value.get("title_hook_contract")
    changed = not isinstance(raw, dict)
    previous = dict(raw) if isinstance(raw, dict) else {}
    title = str(value.get("chosen_title", "")).strip()
    packaging = value.get("packaging_layer") if isinstance(value.get("packaging_layer"), dict) else {}
    behavior = str(previous.get("title_behavior") or packaging.get("title_question") or title).strip()
    pain = str(previous.get("title_pain") or value.get("main_tension") or title).strip()
    anchors = previous.get("opening_anchors")
    if not isinstance(anchors, list):
        anchors = []
        changed = True
    cleaned = [str(item).strip() for item in anchors if len(str(item).strip()) >= 2]
    if not cleaned:
        candidates = re.findall(r"[一-鿿々-〇ァ-ヿ]{2,}", behavior + " " + title)
        cleaned = [item for item in candidates if item not in {"心理", "理由", "人の", "こと"}][:3]
        changed = True
    normalized = {
        "title_behavior": behavior,
        "title_pain": pain,
        "opening_anchors": cleaned[:3],
        "payoff_by_seconds": 20,
    }
    if previous != normalized:
        changed = True
    value["title_hook_contract"] = normalized
    return changed


def title_hook_alignment(script: str, contract: dict) -> dict[str, object]:
    """Check title-to-opening alignment without requiring a verbatim title."""
    title_contract = contract.get("title_hook_contract") or {}
    anchors = title_contract.get("opening_anchors") if isinstance(title_contract, dict) else []
    anchors = [str(item).strip() for item in anchors if len(str(item).strip()) >= 2]
    opening = str(script or "")[:650]

    def comparable(text: str) -> str:
        # Japanese narration naturally changes commas, quotes, and spacing. The
        # contract checks the promised content phrase, not typography.
        return re.sub(r"[\s、。！？!？『』「」\"'（）()・…]", "", text)

    compact_opening = comparable(opening)

    def appears_naturally(anchor: str) -> bool:
        compact_anchor = comparable(anchor)
        if compact_anchor in compact_opening:
            return True
        # Allow a short inserted noun such as メッセージ in
        # 「返したいのに、開けない」 -> 「返したいのにメッセージを開けない」,
        # but preserve character order so unrelated opening text cannot pass.
        if len(compact_anchor) < 5:
            return False
        pattern = "[ぁ-ゟ一-鿿々-〇ァ-ヿ]{0,8}".join(map(re.escape, compact_anchor))
        return re.search(pattern, compact_opening) is not None

    matched = [anchor for anchor in anchors if appears_naturally(anchor)]
    return {
        "checked": bool(anchors),
        "anchors": anchors,
        "matched_anchors": matched,
        "opening_char_window": len(opening),
        "passed": bool(matched) if anchors else True,
    }


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


def normalize_state_advance(value: object) -> str:
    """Normalize planner state_advance into a stable ``before -> after`` string.

    Gemini occasionally returns the same semantic transition using different
    punctuation or as ``{"before": ..., "after": ...}``. Normalize those
    format variants before enforcing the planning contract.
    """
    if isinstance(value, dict):
        before = str(value.get("before", "")).strip()
        after = str(value.get("after", "")).strip()
        if before and after:
            return f"{before} -> {after}"
        return ""

    text = str(value or "").strip()
    if not text:
        return ""

    lowered = text.lower()
    # Common explicit labels from structured-but-string responses.
    for marker in ("->", "→", "⇒", "=>"):
        if marker in text:
            left, right = text.split(marker, 1)
            left = left.strip()
            right = right.strip()
            left = re.sub(r"^(before|from)\s*[:：]\s*", "", left, flags=re.I).strip()
            right = re.sub(r"^(after|to)\s*[:：]\s*", "", right, flags=re.I).strip()
            if left and right:
                return f"{left} -> {right}"

    before_match = re.search(r"\bbefore\s*[:：]\s*(.+?)(?=\bafter\s*[:：]|/|;|$)", text, flags=re.I)
    after_match = re.search(r"\bafter\s*[:：]\s*(.+)$", text, flags=re.I)
    if before_match and after_match:
        before = before_match.group(1).strip(" ;/")
        after = after_match.group(1).strip(" ;/")
        if before and after:
            return f"{before} -> {after}"

    # Japanese/English natural-language transitions occasionally use an
    # explicit before/after delimiter such as "A / B". Do not guess arbitrary
    # prose; only accept the labeled forms above.
    return text


def validate_plan(
    value: dict,
    source_pack: dict | None = None,
    psychology_brief: dict | None = None,
) -> None:
    require_fields(value, ("retention_blueprint", "sections", "hook_draft", "planning_quality_gate"), "planning")
    sections = value["sections"]
    if not 3 <= len(sections) <= 7:
        raise ValueError("Planning phải có 3-7 movements; ưu tiên 5-6 khi nội dung thực sự cần.")
    mechanisms_seen: set[str] = set()
    for section in sections:
        require_fields(
            section,
            (
                "id", "psychological_job", "behavior_link", "why_answered",
                "example_budget", "new_information",
                "state_advance", "so_what_next", "segment_function",
            ),
            "planning section",
        )
        # Backward-compatible migration: older plans used why_answered as the
        # viewer question. New plans should emit the explicit field.
        if "viewer_question_answered" not in section:
            section["viewer_question_answered"] = str(section.get("why_answered", "")).strip()
        if "mechanisms_used" not in section or not isinstance(section["mechanisms_used"], list):
            raise ValueError("planning section.mechanisms_used phải là danh sách (có thể rỗng).")
        state_advance = normalize_state_advance(section.get("state_advance"))
        if "->" not in state_advance:
            raise ValueError("state_advance phải mô tả before -> after.")
        section["state_advance"] = state_advance
        if not str(section["viewer_question_answered"]).strip():
            raise ValueError("Mỗi planning section phải trả lời một psychological question cụ thể.")
        budget = section["example_budget"]
        if not isinstance(budget, int) or not 0 <= budget <= 2:
            raise ValueError("example_budget mỗi section phải là số nguyên 0-2.")
        weight = section.get("relative_weight", 1.0)
        if isinstance(weight, bool):
            raise ValueError("relative_weight phải là số dương.")
        try:
            weight = float(weight)
        except (TypeError, ValueError) as exc:
            raise ValueError("relative_weight phải là số dương.") from exc
        if weight <= 0:
            raise ValueError("relative_weight phải là số dương.")
        section["relative_weight"] = weight
        mechanisms_seen.update(str(item) for item in section["mechanisms_used"])
    # Clock placement is derived from the final script, not from planner guesses.
    gates = (
        "no_duplicate_sections", "every_section_advances_state",
        "psychology_is_spine", "no_plot_or_character_arc", "ending_creates_self_understanding",
    )
    if not all(bool(value["planning_quality_gate"].get(key)) for key in gates):
        raise ValueError("Planning psychology-first quality gate chưa pass.")

    total_example_budget = sum(int(section["example_budget"]) for section in sections)
    if total_example_budget > 4:
        raise ValueError(
            "Planning dành quá nhiều ngân sách cho examples (%d). Example phải là evidence phụ, "
            "không được trở thành content spine." % total_example_budget
        )

    # Recognition mở cửa chứ không kéo dài thành scene. Nếu section đầu tiên là
    # recognition thì section kế tiếp phải chuyển sang psychology/reframe/mechanism.
    if sections[0].get("segment_function") == "recognition" and len(sections) > 1:
        next_function = str(sections[1].get("segment_function", "")).lower()
        if next_function in {"recognition"}:
            raise ValueError("Planning không được có recognition nối tiếp; phải chuyển sang psychology.")
    hook = str(value.get("hook_draft", "")).strip()
    if hook:
        opening_lines = [line.strip() for line in re.split(r"[。！？\n]", hook[:240]) if line.strip()]
        scene_first = bool(opening_lines) and any(marker in opening_lines[0] for marker in HOOK_SCENE_START_MARKERS_JA)
        early_pivot = any(
            marker in line
            for line in opening_lines[:3]
            for marker in HOOK_PSYCHOLOGY_MARKERS_JA
        )
        if scene_first and not early_pivot:
            raise ValueError(
                "Hook micro-scene chưa pivot sớm: trong 1-2 câu phải chuyển sang psychological pattern, misconception, reframe hoặc question."
            )
    continuity = value.get("continuity_map")
    if continuity is not None:
        if not isinstance(continuity, dict):
            raise ValueError("continuity_map phải là object khi được khai báo.")
        if not str(continuity.get("big_open_loop", "")).strip():
            raise ValueError("continuity_map.big_open_loop không được rỗng.")
        payoff_path = continuity.get("payoff_path", [])
        turns = continuity.get("retention_turns", [])
        if not isinstance(payoff_path, list) or not payoff_path:
            raise ValueError("continuity_map.payoff_path phải có ít nhất một payoff source-backed.")
        if not isinstance(turns, list) or len(turns) > 3:
            raise ValueError("continuity_map.retention_turns chỉ được có 0-3 turns.")
        for turn in turns:
            if not isinstance(turn, dict) or not str(turn.get("new_information", "")).strip():
                raise ValueError("Mỗi continuity retention turn phải mô tả new_information.")
            if any(key in turn for key in ("time", "timestamp", "seconds")):
                raise ValueError("continuity retention turn không được khóa timestamp; timing derive từ script.")

    if psychology_brief is not None:
        # The core question is one editorial anchor, not a new section. Older
        # plans omitted it, so migrate from the validated brief in place.
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
        if not source_supports_reinforcement_loop(source_pack):
            plan_text = json.dumps(plan_copy, ensure_ascii=False).lower()
            reinforcement_markers = (
                "負の強化", "強化され", "一時的な安心", "短期的な安心",
                "一時的に不安を下げ", "反応が維持", "維持される",
                "negative reinforcement", "short-term relief", "reinforcement loop",
            )
            found = [marker for marker in reinforcement_markers if marker in plan_text]
            if found:
                raise ValueError(
                    "Planning dùng relief/reinforcement loop ngoài source pack: %s. "
                    "Chỉ mô tả cost quan sát được, không nói relief ngắn hạn duy trì phản ứng."
                    % ", ".join(found)
                )


def normalize_plan_example_budgets(value: dict, maximum: int = 4) -> bool:
    """Cap example metadata without changing the psychological argument.

    Example budget is editorial planning metadata, not generated content. Keep
    the earliest recognition/mechanism allowance and remove excess allowances
    from later sections so a model returning 5 does not trigger a blind retry.
    """
    sections = value.get("sections") or []
    total = sum(
        int(section.get("example_budget", 0))
        for section in sections
        if isinstance(section, dict) and isinstance(section.get("example_budget", 0), int)
    )
    changed = False
    for section in reversed(sections):
        if total <= maximum:
            break
        if not isinstance(section, dict):
            continue
        budget = section.get("example_budget")
        if not isinstance(budget, int):
            continue
        reduction = min(budget, total - maximum)
        if reduction:
            section["example_budget"] = budget - reduction
            total -= reduction
            changed = True
    return changed


def normalize_plan_editorial_metadata(value: dict) -> bool:
    """Migrate clock-based plans to relative editorial weights."""
    changed = False
    for section in value.get("sections") or []:
        if not isinstance(section, dict):
            continue
        if "relative_weight" not in section:
            section["relative_weight"] = 1.0
            changed = True
        if "estimated_seconds" in section:
            section.pop("estimated_seconds", None)
            changed = True
    blueprint = value.get("retention_blueprint")
    if isinstance(blueprint, list):
        for movement in blueprint:
            if isinstance(movement, dict) and "time" in movement:
                movement.pop("time", None)
                changed = True
    continuity = value.get("continuity_map")
    if isinstance(continuity, dict):
        for key in ("time", "timestamp", "target_minutes"):
            if key in continuity:
                continuity.pop(key, None)
                changed = True
        turns = continuity.get("retention_turns")
        if isinstance(turns, list):
            for turn in turns:
                if isinstance(turn, dict):
                    for key in ("time", "timestamp", "seconds"):
                        if key in turn:
                            turn.pop(key, None)
                            changed = True
    return changed


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
    """Pass only from explicit, inspectable audit rules.

    An LLM's score and bare pass/revise preference are subjective signals, so
    neither may block production. Only structured contract/source findings can.
    """
    return (
        bool(value.get("source_alignment"))
        and bool(value.get("outline_coverage"))
        and bool(value.get("title_alignment"))
        and not value.get("unsupported_claims")
        and not value.get("missing_outline_points")
    )


def normalize_audit_report(value: Any, auditor: str = "unknown") -> dict[str, Any]:
    """Normalize an auditor response before it can influence control flow.

    A syntactically valid JSON object is not necessarily an audit contract. A
    malformed report becomes a deterministic revise result, so DeepSeek and
    Gemini follow the same branch and no missing/null field is interpreted
    differently by the pipeline.
    """
    report = dict(value) if isinstance(value, dict) else {}
    report["auditor"] = str(report.get("auditor") or auditor)
    decision = str(report.get("decision") or "revise").strip().lower()
    report["decision"] = decision if decision in {"pass", "revise"} else "revise"
    # Accept old artifacts that still contain a score, but never preserve or
    # use it in the production audit contract.
    report.pop("overall_score", None)
    for field in ("source_alignment", "outline_coverage", "title_alignment", "language_alignment"):
        report[field] = report.get(field) is True
    for field in ("unsupported_claims", "missing_outline_points", "issues"):
        raw = report.get(field)
        if raw is None:
            report[field] = []
        elif isinstance(raw, list):
            report[field] = raw
        else:
            report[field] = [raw]
    if not isinstance(value, dict):
        report["issues"].append("Audit response phải là JSON object.")
    required = ("source_alignment", "outline_coverage", "title_alignment")
    if not isinstance(value, dict) or any(key not in value for key in required):
        report["issues"].append("Audit response thiếu field contract bắt buộc.")
    if report["issues"] and report["decision"] == "pass":
        report["decision"] = "revise"
    return report


def _luminance(hex_color: str) -> float:
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", hex_color):
        raise ValueError("Màu phải ở dạng #RRGGBB.")
    values = [int(hex_color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4 for value in values]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(first: str, second: str) -> float:
    high, low = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _normalize_packaging_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return re.sub(r"[\s\W_]", "", value)


def title_overlap_percent(title: str, thumbnail_text: str) -> float:
    """Measure lexical character overlap for diagnostics only.

    Shared topic/emotion words are allowed between title and thumbnail. This metric
    must not hard-fail a valid package by itself, especially for short Japanese
    overlays where a few shared kanji can produce a high percentage.
    """
    title_chars = set(_normalize_packaging_text(title))
    thumb_chars = set(_normalize_packaging_text(thumbnail_text))
    if not thumb_chars:
        return 0.0
    return len(title_chars & thumb_chars) / len(thumb_chars) * 100


def thumbnail_text_duplication(title: str, thumbnail_text: str) -> tuple[bool, str]:
    """Return hard-fail duplication only for genuine title copying.

    Short Japanese overlays such as 「嫌われた？」 may intentionally share a
    topic keyword with the title. Hard-fail only exact title duplication or a
    long contiguous substring (8+ normalized chars) that clearly copies title
    wording.
    """
    normalized_title = _normalize_packaging_text(title)
    normalized_thumb = _normalize_packaging_text(thumbnail_text)
    if not normalized_title or not normalized_thumb:
        return False, ""
    if normalized_title == normalized_thumb:
        return True, "Thumbnail text trùng toàn bộ title."
    if len(normalized_thumb) >= 8 and normalized_thumb in normalized_title:
        return True, "Thumbnail text sao chép một cụm dài từ title; hãy tạo emotional/self-recognition hook khác wording."
    return False, ""


def normalize_thumbnail_prompt(value: dict) -> None:
    """Complete literal thumbnail contract tokens without another model retry."""
    prompt = str(value.get("image_prompt", "")).strip()
    lowered = prompt.lower()
    additions = []
    if "16:9" not in lowered:
        additions.append("16:9 full bleed composition.")
    if "no text" not in lowered:
        additions.append("No text in base image.")
    if "flat illustrated" not in lowered:
        additions.append("Flat illustrated cartoon style.")
    if "thick black outline" not in lowered:
        additions.append("Thick black outline.")
    if "navy" not in lowered:
        additions.append("Navy #1A2332 background.")
    if "fictional" not in lowered:
        additions.append("Fictional anonymous character.")
    if "full-bleed" not in lowered and "full bleed" not in lowered:
        additions.append("Full-bleed scene across the entire 16:9 frame.")
    if "gradient" not in lowered:
        additions.append("Soft atmospheric gradient into the manual text zone; no hard split.")
    if "identity lock" not in lowered:
        additions.append("Identity lock: exact recurring mascot, unchanged face, outfit, proportions, and colors.")
    if "visual identity anchor" not in lowered:
        additions.append("Visual identity anchor: use the canonical mascot reference image when supported; match its face, outfit, colors, proportions, and thick outline exactly.")
    value.setdefault("character_reference", {
        "role": "canonical_mascot_visual_anchor",
        "preferred_image": "video-build/images/IMG-01.png",
        "fallback": "CHARACTER_BIBLE text lock",
        "instruction": "Use the reference for identity only; vary pose, expression, crop, and scene."
    })
    value["image_prompt"] = " ".join([prompt, *additions]).strip()


def validate_thumbnail(value: dict, title: str) -> dict[str, Any]:
    require_fields(value, ("concepts", "chosen_mode", "thumbnail_text", "text_color", "background_color", "image_prompt", "negative_prompt", "overlay_spec"), "thumbnail")
    text_count = len(value["thumbnail_text"])
    overlap = title_overlap_percent(title, value["thumbnail_text"])
    contrast = contrast_ratio(value["text_color"], value["background_color"])
    issues = []
    warnings = []
    if not 4 <= text_count <= 11:
        issues.append("Thumbnail text phải dài 4-11 ký tự.")

    duplicated, duplication_reason = thumbnail_text_duplication(title, value["thumbnail_text"])
    if duplicated:
        issues.append(duplication_reason)
    elif overlap > 35:
        warnings.append(
            "Lexical title/thumbnail overlap cao (%.1f%%), nhưng overlap keyword được phép; chỉ hard-fail khi thumbnail thực sự copy wording/promise của title."
            % overlap
        )

    if contrast < 7:
        issues.append("Contrast ratio thấp hơn 7:1.")
    prompt_lower = value["image_prompt"].lower()
    if "16:9" not in value["image_prompt"] or "no text" not in prompt_lower:
        issues.append("Thumbnail image prompt phải có 16:9 và no text.")
    if not all(token in prompt_lower for token in ("flat illustrated", "thick black outline", "navy")):
        issues.append("Thumbnail phải giữ flat illustrated cartoon style lock (thick black outline, navy background).")
    if "fictional" not in prompt_lower:
        issues.append("Thumbnail phải ghi rõ nhân vật là fictional để tránh likeness người thật.")
    return {
        "copy_chars": text_count,
        "title_overlap_pct": round(overlap, 2),
        "contrast_ratio": round(contrast, 2),
        "warnings": warnings,
        "issues": issues,
        "passed": not issues,
    }


def derive_visual_density_targets(contract: dict, plan: dict) -> dict[str, int]:
    """Derive minimum coverage from duration instead of a fixed image quota."""
    duration_text = str(contract.get("target_duration_minutes", "6-12"))
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
    # Unique-image ratio is dynamic. This is a soft planning hint, not a hard quota.
    unique_images = max(1, math.ceil(visual_events * 0.70))
    # Keep the recommendation compatible with the compact visual strategy
    # prompt. The minimum is the only hard floor; recommendations must not
    # silently turn into an 80-140 beat generation quota.
    recommended_events_min = max(visual_events, int(round(duration_minutes * 5.5)))
    recommended_events_max = max(recommended_events_min, int(round(duration_minutes * 7)))
    return {
        "duration_seconds_reference": duration_seconds,
        "minimum_visual_events": visual_events,
        "recommended_visual_events": [recommended_events_min, recommended_events_max],
        "minimum_unique_images_soft": unique_images,
        "unique_ratio_target": [0.70, 0.90],
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
        total_events = len(beats)
        unique_ratio = image_index / total_events if total_events else 0.0
        value["unique_image_ratio"] = round(unique_ratio, 3)
        # Dynamic visual policy: model decides which beats deserve fresh images.
        # Validator reports cost/continuity warnings but never hard-fails solely
        # because the unique-image ratio is high or low.
        if unique_ratio > 0.95:
            value.setdefault("qa_warnings", []).append(
                "Unique-image ratio rất cao (%.1f%%): kiểm tra transition/callback có thực sự cần ảnh mới không." % (unique_ratio * 100)
            )
        elif unique_ratio < 0.65:
            value.setdefault("qa_warnings", []).append(
                "Unique-image ratio khá thấp (%.1f%%): kiểm tra continuity và mức thay đổi visual giữa các beat." % (unique_ratio * 100)
            )
        elif unique_ratio < 0.70 or unique_ratio > 0.90:
            value.setdefault("qa_warnings", []).append(
                "Unique-image ratio ngoài vùng mục tiêu mềm 70-90%% (%.1f%%); đây chỉ là cảnh báo." % (unique_ratio * 100)
            )
        value["visual_cost_policy"] = {
            "mode": "dynamic",
            "unique_ratio_target": [0.70, 0.90],
            "unique_ratio_hard_fail": False,
            "decision_owner": "model_strategy",
        }
    if not value["density_check"] or not value["no_filler_check"]:
        raise ValueError("Image strategy density/no-filler gate chưa pass.")


def normalize_image_prompts(value: dict, strategy: dict | None = None) -> None:
    """Normalize provider output and deterministically complete missing beats.

    Large image-prompt responses are sometimes truncated by the provider. The
    strategy is already authoritative, so missing prompts/storyboard rows can
    be completed locally without another blind model retry.
    """
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
    image_by_beat = {
        str(beat["id"]): str(beat["image_id"])
        for beat in beats
    }
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


def select_video_candidates(
    images: list[dict],
    storyboard: list[dict],
    beats: list[dict] | None = None,
    min_count: int = 3,
    max_count: int = 8,
) -> list[str]:
    """Chọn ảnh NÊN gen image-to-video (6-8 clip/run) — heuristic thuần, không gọi model.

    Block vĩnh viễn: prompt chứa token TEXT_SCENE_BLOCKLIST (cảnh chữ). Còn lại
    score: hook (event đầu) +3, closer (event cuối) +3, +2 mỗi event ảnh xuất
    hiện (density), +1 beat đầu ảnh mode metaphor, +1 từ hành động. Sort
    (-score, image_id) → lấy max_count; nếu eligible < min_count thì trả hết
    eligible (không bao giờ lôi ảnh chữ vào).
    """
    blocklist = tuple(token.lower() for token in TEXT_SCENE_BLOCKLIST)
    action_words = tuple(word.lower() for word in ACTION_WORDS)
    beat_by_id = {str(beat.get("id")): beat for beat in (beats or [])}

    first_event_by_image: dict[str, dict] = {}
    density: dict[str, int] = {}
    order: list[str] = []
    for event in storyboard:
        image_id = event.get("image_id")
        if not image_id:
            continue
        if image_id not in density:
            order.append(str(image_id))
            density[str(image_id)] = 0
        density[str(image_id)] += 1
        first_event_by_image.setdefault(str(image_id), event)
    if not order:
        return []

    prompt_by_id = {str(image.get("image_id")): str(image.get("prompt", "")).lower() for image in images}
    eligible = []
    for image in images:
        image_id = str(image.get("image_id"))
        prompt = prompt_by_id.get(image_id, "")
        if any(token in prompt for token in blocklist):
            continue
        eligible.append(image_id)

    def _score(image_id: str) -> int:
        score = 0
        if image_id == order[0]:
            score += 3
        if image_id == order[-1]:
            score += 3
        score += 2 * density.get(image_id, 0)
        first_event = first_event_by_image.get(image_id)
        if first_event is not None:
            beat = beat_by_id.get(str(first_event.get("beat_id")))
            if beat and str(beat.get("mode")) == "metaphor":
                score += 1
        if any(word in prompt_by_id.get(image_id, "") for word in action_words):
            score += 1
        return score

    ranked = sorted(eligible, key=lambda image_id: (-_score(image_id), image_id))
    return ranked[:max_count]
