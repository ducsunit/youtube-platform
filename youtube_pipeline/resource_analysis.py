"""Compatibility exports for the canonical resource-pack analysis flow.

Do not add logic here: production analysis lives in ``resource_pack.analysis``.
``pre_rank_topic_candidates`` remains only for old integrations.
"""
from __future__ import annotations

from typing import Any

from .resource_pack.analysis import build_channel_snapshot, build_performance_review


def pre_rank_topic_candidates(candidates: dict, limit: int = 6) -> dict:
    """Legacy deterministic shortlist helper; not used by production selection."""
    rows = candidates.get("candidates", []) if isinstance(candidates, dict) else []

    def score(row: dict[str, Any]) -> float:
        fields = [str(row.get(key) or "").strip() for key in ("topic", "audience_moment", "core_pain", "angle", "promise")]
        return round(sum(bool(value) for value in fields) * 5 + min(20, len(fields[2])) + min(20, len(fields[4])), 2)

    selected = sorted((row for row in rows if isinstance(row, dict)), key=score, reverse=True)[:max(3, min(limit, len(rows)))]
    return {"candidates": selected, "pre_ranked": True, "pool_limit": len(selected), "original_count": len(rows)}
