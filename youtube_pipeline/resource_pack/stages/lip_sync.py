"""Lip-Sync Generation - Hedra/LivePortrait."""
from youtube_pipeline.core import StageResult, RunContext
from youtube_pipeline.unified_router import get_router

router = get_router()

def _lip_sync_gen(context: RunContext) -> StageResult:
    """Sync character clips to voiceover via Hedra/LivePortrait."""
    shot_list = context.store.read_json("shot_list", context.state)
    clips = context.store.read_json("animation_clips", context.state)
    voiceover = context.store.read_json("voiceover_segments", context.state)
    
    synced = {}
    for shot in shot_list["shots"]:
        shot_id = shot["shot_id"]
        if not shot.get("lip_sync"):
            continue
        
        clip_ref = clips.get(shot_id)
        audio_seg = shot.get("audio_segment")
        audio_ref = voiceover.get("segments", {}).get(audio_seg)
        
        if not clip_ref or not audio_ref:
            continue
        
        clip_bytes = _download_image(clip_ref)
        audio_bytes = _download_image(audio_ref)
        
        if not clip_bytes or not audio_bytes:
            continue
        
        try:
            synced_bytes = router.lip_sync("lip_sync_gen", clip_bytes, audio_bytes)
            synced[shot_id] = synced_bytes
        except Exception as e:
            logger.warning(f"Lip-sync failed for {shot_id}: {e}")
            synced[shot_id] = b""
    
    # Save synced clips
    saved = {}
    for shot_id, clip_bytes in synced.items():
        if clip_bytes:
            ref = context.store.put_binary(f"synced_{shot_id}", f"production/synced_clips/{shot_id}.mp4", clip_bytes, "lip_sync")
            saved[shot_id] = ref
    
    ref = context.store.put_json("synced_clips", "production/synced_clips.json", saved, "lip_sync")
    return StageResult([ref], {
        "total_synced": len(synced),
        "successful": len([c for c in synced.values() if c])
    })


def _download_image(url: str) -> bytes:
    import httpx
    try:
        resp = httpx.get(url, timeout=60.0)
        resp.raise_for_status()
        return resp.content
    except Exception:
        return b""