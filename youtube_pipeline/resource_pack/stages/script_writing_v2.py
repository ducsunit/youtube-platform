"""Script Writing v2 - Problem-solving format 8-10min."""
from youtube_pipeline.resource_pack.prompts import writing_v2_prompt
from youtube_pipeline.resource_pack.metrics import non_whitespace_chars, validate_japanese_script
from youtube_pipeline.core import StageResult, RunContext
from youtube_pipeline.unified_router import get_router

router = get_router()

def _script_writing_v2(context: RunContext) -> StageResult:
    """Write 4500-6500 chars problem-solving script with 3 tools."""
    contract = context.store.read_json("script_contract", context.state)
    shot_list = context.store.read_json("shot_list", context.state)
    source_pack = context.store.read_json("source_pack", context.state)
    brief = context.store.read_json("psychology_brief", context.state)
    
    script = router.generate_text("script_writing", writing_v2_prompt(contract, shot_list, source_pack, brief))
    
    # Validate
    validate_japanese_script(script)
    chars = non_whitespace_chars(script)
    target_min = contract.get("target_char_min", 4500)
    target_max = contract.get("target_char_max", 6500)
    
    if chars < target_min:
        raise ValueError(f"Script too short: {chars} chars, need {target_min}+")
    if chars > target_max:
        raise ValueError(f"Script too long: {chars} chars, max {target_max}")
    
    ref = context.store.put_text("script_draft", "script/script-draft.txt", script, "script_writing_v2")
    return StageResult([ref], {
        "raw_chars": chars,
        "target_min": target_min,
        "target_max": target_max,
        "status": "ok" if target_min <= chars <= target_max else "short"
    })