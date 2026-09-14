"""Video Edit - Assemble timeline via ffmpeg/CapCut."""
from youtube_pipeline.core import StageResult, RunContext
import subprocess
import json

def _video_edit(context: RunContext) -> StageResult:
    """Assemble final video from synced clips + voiceover."""
    shot_list = context.store.read_json("shot_list", context.state)
    synced_clips = context.store.read_json("synced_clips", context.state)
    voiceover = context.store.read_json("voiceover_segments", context.state)
    regular_clips = context.store.read_json("animation_clips", context.state)
    
    build_dir = context.store.root / "video-build"
    build_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Prepare inputs
    _prepare_edit_inputs(build_dir, shot_list, synced_clips, voiceover, regular_clips)
    
    # 2. Generate prompts-build.py for build-video.py
    _generate_prompts_build(build_dir, shot_list, synced_clips)
    
    # 3. Generate marks.tsv
    _generate_marks_tsv(build_dir, shot_list)
    
    # 4. Run build-video.py
    success, output = _run_build_video(build_dir)
    if not success:
        raise RuntimeError(f"Video build failed: {output}")
    
    # 5. Copy final video
    final_video = build_dir / "video-final.mp4"
    if not final_video.exists():
        raise FileNotFoundError("video-final.mp4 not generated")
    
    final_bytes = final_video.read_bytes()
    ref = context.store.put_binary("final_video", "production/video-final.mp4", final_bytes, "video_edit")
    
    return StageResult([ref], {"output": "video-final.mp4", "size_bytes": len(final_bytes)})


def _prepare_edit_inputs(build_dir, shot_list, synced_clips, voiceover, regular_clips):
    pass  # Implement based on your storage


def _generate_prompts_build(build_dir, shot_list, synced_clips):
    pass


def _generate_marks_tsv(build_dir, shot_list):
    lines = []
    for sec in shot_list:
        stem = sec.get("file", f"section-{sec['id']}")
        opening = sec.get("text", "")[:40]
        lines.append(f"{stem}\t{opening}")
    (build_dir / "marks.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_build_video(build_dir):
    import sys, subprocess
    result = subprocess.run([
        sys.executable, "-m", "youtube_pipeline.video.build", str(build_dir),
        "--animation", "zoom",
        "--transition", "0.5",
        "--resolution", "1280x720"
    ], capture_output=True, text=True, timeout=3600)
    return result.returncode == 0, result.stdout + result.stderr