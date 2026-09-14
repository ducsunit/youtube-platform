"""Voiceover Generation - Voicevox primary, Edge-TTS fallback."""
from youtube_pipeline.core import StageResult, RunContext
from youtube_pipeline.unified_router import get_router

import logging
logger = logging.getLogger(__name__)

router = get_router()

def _voiceover_gen(context: RunContext) -> StageResult:
    """Generate voiceover per segment via Voicevox (primary) or Edge-TTS (fallback)."""
    shot_list = context.store.read_json("shot_list", context.state)
    script = context.store.read_text("script_draft", context.state)
    
    segments = {}
    for shot in shot_list["shots"]:
        seg_id = shot.get("audio_segment")
        if not seg_id:
            continue
        
        text = _extract_segment_text(script, shot)
        if not text.strip():
            continue
        
        # Try Voicevox first
        try:
            audio_bytes = router.generate_audio("voiceover_gen", text, "speaker_8")
        except Exception as e:
            logger.warning(f"Voicevox failed for {seg_id}: {e}, trying Edge-TTS")
            try:
                audio_bytes = router.generate_audio("voiceover_fallback", text, "female_gentle")
            except Exception as e2:
                logger.error(f"Both TTS failed for {seg_id}: {e2}")
                continue
        
        segments[seg_id] = audio_bytes
    
    # Save segments
    saved = {}
    for seg_id, audio_bytes in segments.items():
        ref = context.store.put_binary(f"vo_{seg_id}", f"production/voiceover/{seg_id}.wav", audio_bytes, "voiceover")
        saved[seg_id] = ref
    
    # Also save timing info
    timing = _calculate_timing(segments)
    
    ref = context.store.put_json("voiceover_segments", "production/voiceover.json", {
        "segments": saved,
        "timing": timing
    }, "voiceover")
    
    return StageResult([ref], {"segments": len(segments), "total_duration_sec": timing.get("total", 0)})


def _extract_segment_text(script: str, shot: dict) -> str:
    """Extract text for a shot's audio segment."""
    # Simplified - in practice, map script sections to shots
    start = shot.get("text_start", 0)
    end = shot.get("text_end", len(script))
    return script[start:end].strip()


def _calculate_timing(segments: dict) -> dict:
    # Simplified - estimate from byte count
    total = sum(len(a) for a in segments.values())
    return {"total": total // 1000, "segments": len(segments)}  # rough estimate