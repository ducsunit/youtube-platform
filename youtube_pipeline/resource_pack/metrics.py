from __future__ import annotations

import re
from typing import Any, Dict

from .source_catalog import APPROVED_SOURCE_CATALOG


WHITESPACE_RE = re.compile(r"\s+")
JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff々〆ヶ]")
LATIN_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
# Advisory Japanese narration range for the unified editorial flow. Fifteen
# minutes is a review warning, never a quota that triggers filler.
SCRIPT_TARGET_MIN_CHARS = 2300
SCRIPT_TARGET_MAX_CHARS = 6000


def _source_citation_tokens() -> set[str]:
    """Collect English tokens that belong in source metadata, not narration."""
    fields = []
    for row in APPROVED_SOURCE_CATALOG:
        fields.extend([row.get("title", ""), row.get("citation_hint", "")])
        fields.extend(row.get("authors", []))
    return {token.lower() for value in fields for token in LATIN_TOKEN_RE.findall(str(value))}


SOURCE_CITATION_TOKENS = _source_citation_tokens()
SOURCE_CITATION_REPLACEMENTS = (
    ("Everyday temptations", "日常の誘惑"),
    ("Psychology of Habit", "習慣の心理学"),
    ("Dennis Runger", "デニス・ランガー"),
    ("Wendy Wood", "ウェンディ・ウッド"),
    ("self-control", "自己コントロール"),
)


def non_whitespace_chars(text: str) -> int:
    return len(WHITESPACE_RE.sub("", text))


def japanese_character_ratio(text: str) -> float:
    compact = WHITESPACE_RE.sub("", text)
    meaningful = [char for char in compact if char.isalnum()]
    if not meaningful:
        return 0.0
    japanese = sum(1 for char in meaningful if JAPANESE_RE.fullmatch(char))
    return japanese / len(meaningful)


def foreign_tokens(text: str, whitelist: set[str] | None = None) -> list[str]:
    allowed = whitelist or {"LINE", "SNS", "HSP", "AI", "YouTube"}
    return sorted({token for token in LATIN_TOKEN_RE.findall(text) if token not in allowed})


def scrub_source_citation_tokens(text: str) -> tuple[str, list[str]]:
    """Remove catalog citation words accidentally leaked into Japanese narration."""
    for source_phrase, japanese_phrase in SOURCE_CITATION_REPLACEMENTS:
        text = re.sub(re.escape(source_phrase), japanese_phrase, text, flags=re.IGNORECASE)
    removed = sorted({token for token in foreign_tokens(text) if token.lower() in SOURCE_CITATION_TOKENS})
    if not removed:
        return text, []
    removed_set = {token.lower() for token in removed}
    cleaned = LATIN_TOKEN_RE.sub(
        lambda match: "" if match.group(0).lower() in removed_set else match.group(0),
        text,
    )
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"[ \t]+([、。！？!?」』）])", r"\1", cleaned)
    return cleaned.strip(), removed


def japanese_script_metrics(
    script: str,
    cpm_min: int = 380,
    cpm_max: int = 400,
    target_min_chars: int = SCRIPT_TARGET_MIN_CHARS,
    target_max_chars: int = SCRIPT_TARGET_MAX_CHARS,
) -> Dict[str, Any]:
    count = non_whitespace_chars(script)
    if count < target_min_chars:
        length_status = "short_but_allowed"
    elif count > target_max_chars:
        length_status = "long"
    else:
        length_status = "within_guideline"
    return {
        "non_whitespace_chars": count,
        "japanese_character_ratio": round(japanese_character_ratio(script), 4),
        "reference_cpm_min": cpm_min,
        "reference_cpm_max": cpm_max,
        "estimated_duration_min_seconds": round(count / cpm_max * 60) if count else 0,
        "estimated_duration_max_seconds": round(count / cpm_min * 60) if count else 0,
        "target_min_chars": target_min_chars,
        "target_max_chars": target_max_chars,
        "target_char_gate_passed": target_min_chars <= count <= target_max_chars,
        "length_status": length_status,
        "length_is_advisory": True,
    }


def validate_japanese_script(script: str) -> Dict[str, Any]:
    metrics = japanese_script_metrics(script)
    issues = []
    # Length is a production guideline, not a blocking quota. A concise script
    # is valid when it completes the editorial argument without filler.
    if metrics["japanese_character_ratio"] < 0.80:
        issues.append("Tỷ lệ ký tự tiếng Nhật quá thấp.")
    invalid_tokens = foreign_tokens(script)
    if invalid_tokens:
        issues.append("Foreign tokens chưa whitelist: %s" % ", ".join(invalid_tokens))
    return {**metrics, "foreign_tokens": invalid_tokens, "issues": issues, "passed": not issues}


def build_pause_map(script: str) -> list[dict[str, Any]]:
    """Create non-spoken pause cues from Japanese punctuation and paragraph ends."""
    cues: list[dict[str, Any]] = []
    offset = 0
    for paragraph in script.split("\n\n"):
        if not paragraph:
            offset += 2
            continue
        for match in re.finditer(r"[^。！？!?]+[。！？!?]", paragraph):
            punctuation = match.group()[-1]
            seconds = 0.65 if punctuation in "！？!?" else 0.45
            end = offset + match.end()
            cues.append(
                {
                    "char_offset": end,
                    "pause_seconds": seconds,
                    "reason": "sentence_%s" % punctuation,
                    "text_preview": match.group()[-24:],
                }
            )
        paragraph_end = offset + len(paragraph)
        if not cues or cues[-1]["char_offset"] != paragraph_end:
            cues.append(
                {
                    "char_offset": paragraph_end,
                    "pause_seconds": 0.85,
                    "reason": "paragraph_break",
                    "text_preview": paragraph[-24:],
                }
            )
        offset = paragraph_end + 2
    return cues
