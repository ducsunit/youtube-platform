from __future__ import annotations

import re
from typing import Any, Dict


WHITESPACE_RE = re.compile(r"\s+")
JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff々〆ヶ]")
LATIN_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
SCRIPT_TARGET_MIN_CHARS = 2400
SCRIPT_TARGET_MAX_CHARS = 4700


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


def japanese_script_metrics(
    script: str,
    cpm_min: int = 380,
    cpm_max: int = 400,
    target_min_chars: int = SCRIPT_TARGET_MIN_CHARS,
    target_max_chars: int = SCRIPT_TARGET_MAX_CHARS,
) -> Dict[str, Any]:
    count = non_whitespace_chars(script)
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
    }


def validate_japanese_script(script: str) -> Dict[str, Any]:
    metrics = japanese_script_metrics(script)
    issues = []
    if not metrics["target_char_gate_passed"]:
        issues.append("Script phải nằm trong 2.400–4.700 ký tự không tính whitespace cho duration 9-11 phút.")
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
