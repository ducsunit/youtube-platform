"""Animation Generation - Kling/Hailuo/Runway."""
from youtube_pipeline.core import StageResult, RunContext
from youtube_pipeline.unified_router import get_router

import logging
logger = logging.getLogger(__name__)

router = get_router()

def _animation_gen(context: RunContext) -> StageResult:
    """Animate 55 images to video clips via Kling/Hailuo."""
    shot_list = context.store.read_json("shot_list", context.state)
    images = context.store.read_json("generated_images", context.state)
    
    clips = {}
    for shot in shot_list["shots"]:
        shot_id = shot["shot_id"]
        img_ref = images.get(shot_id)
        if not img_ref:
            continue
        
        img_bytes = _download_image(img_ref)
        if not img_bytes:
            continue
        
        prompt = _build_animation_prompt(shot)
        params = _get_animation_params(shot)
        
        try:
            clip_bytes = router.generate_video("animation_gen", prompt, image=img_bytes, **params)
            clips[shot_id] = clip_bytes
        except Exception as e:
            logger.warning(f"Animation failed for {shot_id}: {e}")
            clips[shot_id] = b""
    
    # Save clips
    saved = {}
    for shot_id, clip_bytes in clips.items():
        if clip_bytes:
            ref = context.store.put_binary(f"clip_{shot_id}", f"production/clips/{shot_id}.mp4", clip_bytes, "animation")
            saved[shot_id] = ref
    
    ref = context.store.put_json("animation_clips", "production/clips.json", saved, "animation")
    return StageResult([ref], {
        "total_clips": len(clips),
        "successful": len([c for c in clips.values() if c]),
        "failed": len([c for c in clips.values() if not c])
    })


def _build_animation_prompt(shot: dict) -> str:
    motion = shot.get("motion", "subtle breathing, slight head movement")
    return f"{shot.get('visual_information', '')}, {motion}, smooth, cinematic"


def _get_animation_params(shot: dict) -> dict:
    return {
        "duration": shot.get("duration_sec", 5),
        "mode": "std" if shot.get("type") in ("character_closeup", "character_medium") else "creative"
    }