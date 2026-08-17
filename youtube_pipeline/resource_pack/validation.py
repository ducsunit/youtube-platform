from __future__ import annotations

import math
import re
import unicodedata
from typing import Any

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
    if not 1 <= len(selected) <= 3:
        raise ValueError("Chỉ chọn 1-3 psychological mechanisms cho một video.")
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
    # Japanese dialogue quotes: a long chain is usually a scene, one quoted thought is fine.
    if text.count("「") >= 8:
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

# Blocking semantic review gate. LLM review supplies these scores; deterministic
# metrics remain diagnostic because lexical density alone cannot define format.
PSYCHOLOGY_REVIEW_GATE = {
    "psychology_spine_min": 7.0,
    "mechanism_depth_min": 7.0,
    "insight_density_min": 6.0,
    "recognition_min": 6.0,
    "story_dominance_max": 3.0,
    "example_dependency_max": 3.0,
    "reframe_signature_min": 2,
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


def psychology_review_gate_verdict(review: dict) -> tuple[bool, list[str]]:
    """Blocking semantic gate for the target A/B psychology-first format.

    Scores come from the LLM reviewer because deterministic lexical metrics cannot
    reliably distinguish a psychology explanation from a story with psychology
    commentary. Missing scorecard fields fail closed.
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
    """Detect a scene-led opening that has not pivoted to psychology quickly enough."""
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
    weights = {
        "channel_fit": 25,
        "audience_pain": 20,
        "packaging_potential": 20,
        "retention_8_10m": 15,
        "source_strength": 10,
        "novelty": 10,
    }
    scores = value["scores"]
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
    if not any(term in content_center for term in ("behavior", "pattern", "kiểu người", "psychological")):
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
    if int(value["target_char_min"]) != 2400 or int(value["target_char_max"]) != 4700:
        raise ValueError("Target ký tự Phase 1 phải là 2400-4700 theo 9-11 phút và 380-400 CPM (calibrated).")


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
    if not 6 <= len(sections) <= 8:
        raise ValueError("Planning phải có 6-8 sections.")
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
        mechanisms_seen.update(str(item) for item in section["mechanisms_used"])
    gates = (
        "first_insight_before_35s", "first_major_payoff_before_5m",
        "no_duplicate_sections", "every_section_advances_state",
        "psychology_is_spine", "no_plot_or_character_arc", "ending_creates_self_understanding",
    )
    if not all(bool(value["planning_quality_gate"].get(key)) for key in gates):
        raise ValueError("Planning psychology-first quality gate chưa pass.")

    total_example_budget = sum(int(section["example_budget"]) for section in sections)
    if total_example_budget > 6:
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
        opening = hook[:140]
        scene_first = any(marker in opening for marker in HOOK_SCENE_START_MARKERS_JA)
        psychology_first = any(marker in opening for marker in HOOK_PSYCHOLOGY_MARKERS_JA)
        if scene_first and not psychology_first:
            raise ValueError(
                "Hook đang scene-first: phải giới thiệu psychological pattern/question trước, "
                "sau đó mới dùng situation làm recognition."
            )

    if psychology_brief is not None:
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


def audit_passes(value: dict, minimum_score: int = 90) -> bool:
    # language_alignment KHÔNG còn là fail condition: script tiếng Nhật là thiết
    # kế chủ đạo của kênh còn contract/plan/title viết tiếng Việt — auditor dễ
    # đánh dấu false chỉ vì khác ngôn ngữ, làm chết chuỗi repair vô nghĩa.
    #
    # issues[] cũng KHÔNG còn là fail condition: auditor thường viết nhận xét
    # "không cần sửa" vào đây (vd "hơi chung chung, nhưng không gây hiểu lầm"),
    # và một note vô hại như vậy từng làm chết cả run dù chính auditor kết luận
    # pass. Chốt chặn thật là decision + các list có cấu trúc bên dưới.
    return (
        value.get("decision") == "pass"
        and normalize_audit_score(value) >= minimum_score
        and bool(value.get("source_alignment"))
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
    duration_text = str(contract.get("target_duration_minutes", "9-11"))
    numbers = [int(item) for item in re.findall(r"\d+", duration_text)]
    if len(numbers) >= 2:
        duration_minutes = (numbers[0] + numbers[1]) / 2
    elif numbers:
        duration_minutes = float(numbers[0])
    else:
        duration_minutes = 9.0
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
    return {
        "duration_seconds_reference": duration_seconds,
        "minimum_visual_events": visual_events,
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


def normalize_image_prompts(value: dict) -> None:
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
