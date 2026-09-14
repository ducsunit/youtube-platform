"""Psychology Brief v2 - Problem-solving format with 1 mechanism + 3 tools."""
from __future__ import annotations

from ..prompts import psychology_brief_v2_prompt, CLAIM_VOCAB_BAN_VI
from ..validation import validate_psychology_brief, validate_source_bounded_brief_causality
from youtube_pipeline.core import StageResult, RunContext
from youtube_pipeline.unified_router import get_router

router = get_router()

def _psychology_brief_v2(context: RunContext) -> StageResult:
    """Build psychology model for problem-solving format: 1 mechanism + 3 tools."""
    topic_context = _build_topic_context(context)
    brief = router.generate_json("psychology_brief", 
        psychology_brief_v2_prompt(topic_context, context.store.read_json("source_pack", context.state), 
        context.store.read_json("performance_review", context.state)))
    
    # Validate
    validate_psychology_brief(brief, context.store.read_json("source_pack", context.state))
    validate_source_bounded_brief_causality(brief, context.store.read_json("source_pack", context.state))
    
    ref = context.store.put_json("psychology_brief", "script/psychology-brief.json", brief, "psychology_brief_v2")
    return StageResult([ref], {
        "route": brief["route"],
        "mechanisms": len(brief["selected_mechanisms"]),
        "tools": len(brief.get("actionable_tools", [])),
        "creative_calls": 1
    })


def _build_topic_context(context: RunContext) -> str:
    """Build enriched topic context with psychological spine."""
    selected = context.store.read_json("selected_topic", context.state)
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