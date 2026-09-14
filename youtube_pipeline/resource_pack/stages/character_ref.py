"""Character Reference Generation - ComfyUI IP-Adapter FaceID."""
from youtube_pipeline.core import StageResult, RunContext
from youtube_pipeline.unified_router import get_router

router = get_router()

def _character_ref_gen(context: RunContext) -> StageResult:
    """Generate master character reference using ComfyUI + IP-Adapter FaceID."""
    brief = context.store.read_json("psychology_brief", context.state)
    contract = context.store.read_json("script_contract", context.state)
    
    # Get reference image (uploaded by user or from assets)
    ref_image_bytes = _get_reference_image(context)
    if not ref_image_bytes:
        raise ValueError("No reference image provided for character generation")
    
    # Build prompt from contract/brief
    prompt = _build_character_prompt(contract, brief)
    
    # Generate via router (ComfyUI)
    image_bytes = router.generate_image("character_ref_gen", prompt, reference_image=ref_image_bytes)
    
    # Save and get URL
    ref = context.store.put_binary("character_ref", "production/character_ref.png", image_bytes, "character_ref")
    
    # Upload to get URL (implement based on your storage)
    char_ref_url = _upload_and_get_url(image_bytes, "character_ref.png")
    
    # Save URL for downstream stages
    context.store.put_text("character_ref_url", "production/character_ref_url.txt", char_ref_url, "character_ref")
    
    return StageResult([ref], {"character_ref_url": char_ref_url, "size_bytes": len(image_bytes)})


def _get_reference_image(context: RunContext) -> bytes:
    """Get reference image from user upload or assets."""
    # Check for uploaded reference
    try:
        return context.store.read_binary("user_reference_image", context.state)
    except:
        pass
    # Fallback: check assets folder
    try:
        return context.store.read_binary("assets/reference_image.png", context.state)
    except:
        return b""


def _build_character_prompt(contract: dict, brief: dict) -> str:
    """Build character generation prompt from contract/brief."""
    base = (
        "chalk-line figure, anonymous adult Japanese silhouette, simple off-white ink lines, "
        "round unfeatured head, restrained dot eyes, slim neutral body, black charcoal clothing blocks, "
        "white background, high contrast, 16:9, masterpiece, best quality"
    )
    # Add psychological identity if available
    identity = brief.get("psychological_identity", "")
    if identity:
        base += f", expressing {identity}"
    return base


def _upload_and_get_url(image_bytes: bytes, filename: str) -> str:
    """Upload to storage and return public URL. Implement based on your storage (S3, GCS, etc.)."""
    # Placeholder - implement based on your storage
    return f"https://storage.yourdomain.com/{filename}"