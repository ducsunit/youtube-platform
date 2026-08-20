"""Remove a fixed provider watermark from generated clips.

The original clips are moved to ``clips-original`` before the cleaned file is
written back to ``clips``. This keeps the operation reversible and lets the
existing video builder continue to prefer the cleaned clips automatically.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable


DEFAULT_REGION = {"x": 1120, "y": 570, "width": 120, "height": 75}


def _filter(region: dict[str, int], mode: str) -> str:
    x, y = region["x"], region["y"]
    w, h = region["width"], region["height"]
    if mode == "blur":
        # A small blurred patch is less destructive on detailed backgrounds.
        return (
            f"split[base][patch];[patch]crop={w}:{h}:{x}:{y},boxblur=20:2[blur];"
            f"[base][blur]overlay={x}:{y}"
        )
    if mode != "delogo":
        raise ValueError("logo cleanup mode phải là delogo hoặc blur")
    return f"delogo=x={x}:y={y}:w={w}:h={h}:show=0"


def clean_clips(
    build_dir: Path,
    region: dict[str, int] | None = None,
    mode: str = "delogo",
    log: Callable[[str], None] | None = None,
) -> dict:
    """Clean all MP4 clips in ``build_dir/clips`` and return a report."""
    log = log or (lambda _message: None)
    region = {**DEFAULT_REGION, **(region or {})}
    if any(int(region[key]) < 0 for key in ("x", "y")) or any(int(region[key]) <= 0 for key in ("width", "height")):
        raise ValueError("logo cleanup region không hợp lệ")
    clips_dir = build_dir / "clips"
    backup_dir = build_dir / "clips-original"
    backup_dir.mkdir(parents=True, exist_ok=True)
    cleaned: list[str] = []
    failed: list[dict[str, str]] = []
    for source in sorted(clips_dir.glob("*.mp4")):
        backup = backup_dir / source.name
        temporary = source.with_suffix(".logo-cleanup.mp4")
        try:
            if not backup.exists():
                shutil.copy2(source, backup)
            command = [
                "ffmpeg", "-y", "-i", str(source), "-vf", _filter(region, mode),
                "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "18", "-c:a", "copy", str(temporary),
            ]
            log("LOGO_CLEANUP start clip=%s mode=%s region=%s" % (source.name, mode, region))
            subprocess.run(command, check=True, capture_output=True, text=True)
            temporary.replace(source)
            cleaned.append(source.name)
            log("LOGO_CLEANUP success clip=%s" % source.name)
        except (OSError, subprocess.CalledProcessError, ValueError) as exc:
            temporary.unlink(missing_ok=True)
            failed.append({"clip": source.name, "error": str(exc)})
            log("LOGO_CLEANUP failed clip=%s error=%s" % (source.name, exc))
    return {"mode": mode, "region": region, "cleaned": cleaned, "failed": failed, "backup_dir": str(backup_dir)}
