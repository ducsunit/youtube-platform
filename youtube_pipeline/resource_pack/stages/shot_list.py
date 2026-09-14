"""Shot List Stage - Script → 55 shots with type, prompt, duration, audio segment, lip_sync flag."""
from youtube_pipeline.resource_pack.prompts import shot_list_prompt
from youtube_pipeline.resource_pack.validation import validate_shot_list
from youtube_pipeline.core import StageResult, RunContext
from youtube_pipeline.unified_router import get_router

router = get_router()

def _shot_list(context: RunContext) -> StageResult:
    """Script → 55 shots with type, prompt, duration, audio_seg, lip_sync flag, animation_provider."""
    script = context.store.read_text("script_draft", context.state)
    brief = context.store.read_json("psychology_brief", context.state)
    contract = context.store.read_json("script_contract", context.state)
    
    shot_list = router.generate_json("shot_list", shot_list_prompt(script, brief, contract))
    
    validate_shot_list(shot_list)
    
    ref = context.store.put_json("shot_list", "production/shot_list.json", shot_list, "shot_list")
    return StageResult([ref], {
        "total_shots": len(shot_list.get("shots", [])),
        "total_duration_sec": sum(s.get("duration_sec", 0) for s in shot_list.get("shots", [])),
        "character_shots": len([s for s in shot_list.get("shots", []) if s.get("type") in ("character_closeup", "character_medium")]),
        "lip_sync_shots": len([s for s in shot_list.get("shots", []) if s.get("lip_sync")])
    })