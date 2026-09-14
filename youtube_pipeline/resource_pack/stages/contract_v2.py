"""Contract v2 - Format lock for 8-10min problem-solving format."""
from youtube_pipeline.resource_pack.prompts import contract_v2_prompt
from youtube_pipeline.resource_pack.validation import validate_contract, normalize_contract_titles, normalize_contract_format_lock, normalize_title_hook_contract
from youtube_pipeline.core import StageResult, RunContext
from youtube_pipeline.unified_router import get_router

router = get_router()

def _contract_v2(context: RunContext) -> StageResult:
    """Lock format for 8-10min problem-solving: hook contract, tool slots, char targets."""
    topic = context.state.topic
    source_pack = context.store.read_json("source_pack", context.state)
    performance = context.store.read_json("performance_review", context.state)
    brief = context.store.read_json("psychology_brief", context.state)
    
    contract = router.generate_json("contract", contract_v2_prompt(topic, source_pack, performance, brief))
    
    # Validate and normalize
    validate_contract(contract)
    normalize_contract_titles(contract)
    normalize_contract_format_lock(contract)
    normalize_title_hook_contract(contract)
    
    ref = context.store.put_json("script_contract", "script/contract.json", contract, "contract_v2")
    return StageResult([ref], {
        "char_target": contract["target_char_min"],
        "hook_timing": contract["hook_contract"],
        "tool_slots": 3,
        "creative_calls": 1
    })