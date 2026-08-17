from __future__ import annotations

import re
from typing import Any, Dict, Optional

from .models import AuditReport


def target_duration_seconds(target_duration: str) -> Optional[int]:
    normalized = target_duration.lower().replace(",", ".")
    minute_match = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:phút|phut|minutes?|mins?)\b", normalized
    )
    if minute_match:
        return round(float(minute_match.group(1)) * 60)
    second_match = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:giây|giay|seconds?|secs?|s)\b", normalized
    )
    if second_match:
        return round(float(second_match.group(1)))
    return None


def deterministic_duration_check(
    target_duration: str,
    final_script: str,
    tolerance: float,
    words_per_minute: int = 150,
) -> Dict[str, Any]:
    word_count = len(final_script.split())
    actual_seconds = round(word_count / words_per_minute * 60) if word_count else 0
    target_seconds = target_duration_seconds(target_duration)
    if target_seconds is None:
        return {
            "passed": True,
            "status": "not_parsed",
            "target_duration": target_duration,
            "estimated_speaking_seconds": actual_seconds,
            "message": "Không trích xuất được số giây mục tiêu; hai auditor vẫn phải kiểm tra.",
        }
    difference_ratio = abs(actual_seconds - target_seconds) / target_seconds
    return {
        "passed": difference_ratio <= tolerance,
        "status": "checked",
        "target_duration": target_duration,
        "target_seconds": target_seconds,
        "estimated_speaking_seconds": actual_seconds,
        "difference_ratio": round(difference_ratio, 4),
        "tolerance": tolerance,
        "word_count": word_count,
    }


def evaluate_quality_gate(
    deepseek_audit: AuditReport,
    gemini_audit: AuditReport,
    duration_check: Dict[str, Any],
    minimum_score: int,
) -> Dict[str, Any]:
    failures = []
    if not deepseek_audit.passes(minimum_score):
        failures.append("DeepSeek Auditor không đạt quality gate.")
    if not gemini_audit.passes(minimum_score):
        failures.append("Gemini Auditor không đạt quality gate.")
    if not duration_check["passed"]:
        failures.append("Thời lượng ước tính nằm ngoài sai số cho phép.")
    return {
        "passed": not failures,
        "minimum_score": minimum_score,
        "failures": failures,
        "deepseek_audit": deepseek_audit.to_dict(),
        "gemini_audit": gemini_audit.to_dict(),
        "deterministic_duration_check": duration_check,
    }
