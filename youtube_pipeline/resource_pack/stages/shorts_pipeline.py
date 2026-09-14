"""Shorts Daily Pipeline - 60-90s vertical problem-solving."""
from youtube_pipeline.core import StageResult, RunContext
from youtube_pipeline.unified_router import get_router

import logging
logger = logging.getLogger(__name__)

router = get_router()

def _shorts_pipeline(context: RunContext) -> StageResult:
    """Generate one Shorts video (60-90s vertical) from long-form content."""
    long_script = context.store.read_text("script_draft", context.state)
    brief = context.store.read_json("psychology_brief", context.state)
    char_ref_url = context.store.read_text("character_ref_url", context.state)
    
    # 1. Pick topic from long-form (one tool or pain point)
    shorts_topic = _pick_shorts_topic(brief)
    
    # 2. Write shorts script (60-90s)
    shorts_script = router.generate_text("shorts_script", _shorts_script_prompt(shorts_topic, brief))
    
    # 3. Shot list (8-12 shots, vertical 9:16)
    shorts_shots = router.generate_json("shorts_shot_list", _shorts_shot_list_prompt(shorts_script))
    
    # 4. Generate vertical images (ComfyUI --ar 9:16)
    char_ref_bytes = _download_image(context.store.read_text("character_ref_url", context.state))
    images = {}
    for shot in shorts_shots["shots"]:
        if shot.get("type") in ("character_closeup", "character_medium"):
            img = _generate_vertical_with_ref(char_ref_bytes, shot["prompt"])
        else:
            img = router.generate_image("shorts_image", _build_vertical_prompt(shot))
        images[shot["shot_id"]] = img
    
    # 5. Animate vertical clips
    clips = {}
    for shot in shorts_shots["shots"]:
        img = images[shot["shot_id"]]
        clip = router.generate_video("shorts_animation", _build_vertical_anim_prompt(shot), image=img, duration=shot.get("duration", 5))
        clips[shot["shot_id"]] = clip
    
    # 6. Voiceover (Voicevox)
    vo_segments = {}
    for shot in shorts_shots["shots"]:
        text = shot.get("text", "")
        if text:
            vo_segments[shot["shot_id"]] = router.generate_audio("voiceover_gen", text, "speaker_8")
    
    # 7. Edit vertical video (CapCut template)
    final_video = _edit_vertical_short(clips, vo_segments, shorts_shots)
    
    # 8. Thumbnail (vertical 9:16)
    thumb = router.generate_image("thumbnail", _build_shorts_thumb_prompt(brief), reference_image=_download_image(context.store.read_text("character_ref_url", context.state)))
    
    # 9. Publish package
    publish_pack = router.generate_json("shorts_publish", _shorts_publish_prompt(shorts_script, brief))
    
    return StageResult([], {
        "shorts_script": shorts_script,
        "duration_sec": sum(s.get("duration", 5) for s in shorts_shots["shots"]),
        "publish_pack": publish_pack
    })


def _pick_shorts_topic(brief: dict) -> dict:
    """Pick one tool/pain point from brief for Shorts."""
    tools = brief.get("actionable_tools", [])
    if tools:
        return {"tool": tools[0], "pain": brief.get("core_pain", ""), "mechanism": brief.get("selected_mechanisms", [{}])[0].get("name", "")}
    return {"pain": brief.get("core_pain", ""), "mechanism": brief.get("selected_mechanisms", [{}])[0].get("name", "")}


def _shorts_script_prompt(topic: dict, brief: dict) -> str:
    return """Write a 60-90 second vertical Shorts script for Japanese audience.

Topic: {topic_tool}
Pain: {topic_pain}
Mechanism: {topic_mechanism}

Format (60-90s):
1. HOOK (0-3s): Visual + text - relatable pain moment
2. INSIGHT (3-15s): One-sentence mechanism reveal
3. TOOL (15-45s): One actionable script/template
4. MICRO-ACTION (45-60s): One tiny step to do today
5. CTA (60-75s): "Try this today" + follow for more

Japanese, natural spoken style, problem-solving tone. No intros/outros.
Target: 180-220 words Japanese.""".format(
        topic_tool=topic.get('tool', {}).get('name', topic.get('pain', '')),
        topic_pain=topic.get('pain', ''),
        topic_mechanism=topic.get('mechanism', '')
    )


def _shorts_shot_list_prompt(script: str) -> str:
    return """Break this Shorts script into 8-12 vertical shots (9:16).
Script: {script}

Return JSON:
{{
  "shots": [
    {{"shot_id": "S01", "type": "character_closeup", "prompt": "...", "duration": 3, "text": "...", "lip_sync": true}},
    ...
  ]
}}""".format(script=script)


def _build_vertical_prompt(shot: dict) -> str:
    return "{prompt}, vertical 9:16, chalk-line style, high contrast".format(prompt=shot.get('prompt', ''))


def _build_vertical_anim_prompt(shot: dict) -> str:
    return "{prompt}, vertical 9:16, subtle motion".format(prompt=shot.get('prompt', ''))


def _edit_vertical_short(clips, vo_segments, shots):
    # Use CapCut template or ffmpeg
    pass


def _build_shorts_thumb_prompt(brief: dict) -> str:
    return "{core_pain}, vertical 9:16, bold text, high contrast".format(core_pain=brief.get('core_pain', ''))


def _download_image(url: str) -> bytes:
    import httpx
    try:
        return httpx.get(url, timeout=30.0).content
    except:
        return b""