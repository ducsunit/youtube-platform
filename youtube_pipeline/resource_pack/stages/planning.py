"""Planning Stage - Convert brief to planning.json with movements."""
from youtube_pipeline.resource_pack.prompts import planning_prompt, ANTI_STORY_RULES, CLAIM_VOCAB_BAN_VI
from youtube_pipeline.resource_pack.validation import validate_plan
from youtube_pipeline.core import StageResult, RunContext
from youtube_pipeline.unified_router import get_router

router = get_router()

def _planning(context: RunContext) -> StageResult:
    """Convert narrative brief to planning.json with 5-7 movements."""
    brief = context.store.read_json("psychology_brief", context.state)
    source_pack = context.store.read_json("source_pack", context.state)
    
    plan = router.generate_json("planning", planning_prompt(
        context.state.topic, brief, source_pack, context.store.read_json("performance_review", context.state)))
    
    validate_plan(plan, source_pack, brief)
    
    ref = context.store.put_json("planning", "script/planning.json", plan, "planning")
    return StageResult([ref], {
        "movements": len(plan.get("sections", [])),
        "mechanisms": len(brief.get("selected_mechanisms", [])),
        "hook_ready": bool(plan.get("hook_draft"))
    })