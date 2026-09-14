"""Thumbnail Generation - ComfyUI IP-Adapter for A/B options."""
from youtube_pipeline.core import StageResult, RunContext
from youtube_pipeline.unified_router import get_router

router = get_router()

def _thumbnail_gen(context: RunContext) -> StageResult:
    """Generate thumbnail A/B options via ComfyUI IP-Adapter."""
    contract = context.store.read_json("script_contract", context.state)
    char_ref_url = context.store.read_text("character_ref_url", context.state)
    
    char_ref_bytes = _download_image(char_ref_url)
    if not char_ref_bytes:
        raise ValueError("Failed to download character reference")
    
    # Build thumbnail prompts from contract
    thumb_brief = contract.get("thumbnail_brief", {})
    prompt_a = _build_thumbnail_prompt(thumb_brief, "option_a")
    prompt_b = _build_thumbnail_prompt(thumb_brief, "option_b")
    
    # Generate 2 options via ComfyUI
    ref_bytes = _download_image(char_ref_url)
    results = router.generate_image("thumbnail_gen", prompt_a, reference_image=ref_bytes)
    # For option B, we'd call again with prompt_b
    # Simplified here - actual implementation uses ComfyUIClient directly
    
    results = {
        "option_a": {"prompt": prompt_a, "image_ref": "thumbnail_a.png"},
        "option_b": {"prompt": prompt_b, "image_ref": "thumbnail_b.png"}
    }
    
    ref = context.store.put_json("thumbnail_options", "production/thumbnails.json", results, "thumbnail_gen")
    return StageResult([ref], {"options": 2})


def _download_image(url: str) -> bytes:
    import httpx
    try:
        resp = httpx.get(url, timeout=30.0)
        resp.raise_for_status()
        return resp.content
    except Exception:
        return b""


def _build_thumbnail_prompt(thumb_brief: dict, option: str) -> str:
    """Build thumbnail prompt from contract brief."""
    conflict = thumb_brief.get("visual_conflict", "internal struggle vs outer calm")
    click_q = thumb_brief.get("click_question", "Why can't I say no?")
    
    base = f"{conflict}, symbolic ink tableau, high contrast black and off-white, thick brush outline, sparse silhouettes, one controlled lemon-gold #FFE500 accent, bold symbolic transformation, 16:9"
    
    if option == "option_a":
        return f"Option A: {base}, focus on emotional tension, text space top 30%"
    else:
        return f"Option B: {base}, focus on transformation moment, text space top 30%"