"""Xuất build pack cho youtube_pipeline/build-video.py và tự ráp video-final.mp4.

Module video_build dùng meta của stage timeline (sections + events với cửa sổ giây
thật theo tỉ lệ ký tự) làm nguồn duy nhất:
- prompts-build.py: row đầy đủ cho MỌI event (kể cả reuse) — biên cumulative được
  round 1 lần nên các cửa sổ liền mạch tuyệt đối, và xử lý được reuse liên tiếp
  (cơ chế REUSE_BEATS của tool vỡ khi 2 beat reuse cạnh nhau).
- marks.tsv: câu mở đầu từng section (chế độ map theo thời gian không dùng nội dung
  câu, chỉ cần số dòng == số file audio).
- audio/: cắt file audio ghép tại đúng mốc section → mỗi file có duration ≈ cửa
  sổ est → scale mỗi event ≈ 1.0, nằm trong dải 0.7–1.35 của tool.
- images/: ảnh IMG-xx do người dùng gen. Có thể bỏ vào video-build/import/ để web
  tự import theo thứ tự mtime (thứ tự gen == thứ tự prompt), hoặc đặt thẳng tên
  IMG-xx vào images/. Thiếu ảnh → status WAITING_IMAGES, không dừng pipeline.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
CLIP_EXTENSIONS = (".mp4", ".mov", ".webm")

# Các mode animation build-video.py nhận (engine đặt ngay trong package — bản
# copy ổn định, không import chéo).
ANIM_MODES = ("none", "zoom", "zoom-out", "pan-h", "pan-v", "auto")
# Preset hiệu ứng nhiễu cho build-video.py --fx (grain/glitch/vhs/auto).
FX_MODES = ("none", "grain", "glitch", "vhs", "auto")
FX_GRAIN_MIN, FX_GRAIN_MAX, FX_GRAIN_DEFAULT = 2, 30, 8


def build_video_script() -> Path:
    """Engine ráp video — đặt ngay trong package, cạnh module này."""
    return Path(__file__).resolve().parent / "build-video.py"


def tool_python() -> str:
    """build-video.py chỉ dùng stdlib → chạy bằng interpreter hiện tại."""
    return sys.executable


def _fmt_sec(seconds: float) -> str:
    seconds = max(0.0, seconds)
    return "%d:%02d" % (int(seconds // 60), int(seconds % 60))


def _first_sentence(text: str) -> str:
    """Câu mở đầu (tới dấu câu kết thúc). Fallback: 40 ký tự đầu."""
    match = re.search(r"[^。？!！]*[。？!！]", text)
    if match and match.group(0).strip():
        return match.group(0).strip()
    return text.strip()[:40]


def build_marks_tsv(sections: list[dict]) -> str:
    """marks.tsv: '<NN_section-0K><TAB><câu mở đầu>' mỗi dòng, đúng thứ tự sections.

    Stem lấy từ trường "file" của section (cùng quy ước tên với split_audio_by_sections
    để sorted glob == thứ tự section); câu mở đầu lấy từ text của chính section.
    """
    lines = []
    for sec in sections:
        file_stem = sec.get("file", "")
        stem = file_stem[:-4] if file_stem.endswith(".txt") else "section-%s" % sec.get("id", "")
        opening = _first_sentence(sec.get("text", ""))
        lines.append("%s\t%s" % (stem, opening))
    return "\n".join(lines) + "\n"


def render_rows(events: list[dict], sections: list[dict]) -> str:
    """Nội dung prompts-build.py cho build-video.py.

    Cửa sổ event = chia đều trong cửa sổ section (đúng như build_timeline), biên
    cumulative được round 1 lần → các cửa sổ liền mạch (tool gate gap ±0.01s).
    REUSE_BEATS để {} vì mọi beat đều có row riêng (reuse liên tiếp không phá).
    """
    bounds = {s["id"]: (float(s["start_s"]), float(s["end_s"])) for s in sections}
    by_section: dict[str, list[dict]] = {}
    for event in events:
        by_section.setdefault(event.get("section"), []).append(event)

    rows: list[tuple[dict, int, int]] = []
    for sec, evs in by_section.items():
        start, end = bounds[sec]
        count = len(evs)
        for index, event in enumerate(evs):
            b0 = start + (end - start) * index / count
            b1 = end if index + 1 == count else start + (end - start) * (index + 1) / count
            rows.append((event, int(round(b0)), int(round(b1))))
    rows.sort(key=lambda item: (item[1], str(item[0].get("event_id", ""))))

    lines = [
        "# AUTO-GENERATED bởi stage video_build — đừng sửa tay; resume pipeline để tái sinh.",
        "BEATS = [",
    ]
    for index, (event, w0, w1) in enumerate(rows, 1):
        lines.append(
            '    ("%s","%s","%s-%s",%d),'
            % (event["image_id"], event["beat_id"], _fmt_sec(w0), _fmt_sec(w1), index)
        )
    lines.append("]")
    lines.append("REUSE_BEATS = {}  # mọi beat có row riêng — reuse liên tiếp không vỡ contiguity")
    return "\n".join(lines) + "\n"


def images_digest(build_dir: Path) -> str | None:
    """Digest trạng thái ảnh (images/ + import/) — tham gia fingerprint stage.

    Người dùng bỏ ảnh vào → digest đổi → resume chạy lại stage video_build.
    """
    entries: list[tuple[str, int, int]] = []
    for directory in (build_dir / "images", build_dir / "import"):
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
                stat = path.stat()
                entries.append((str(path), stat.st_size, stat.st_mtime_ns))
    if not entries:
        return None
    entries.sort()
    digest = hashlib.sha256()
    for name, size, mtime in entries:
        digest.update(repr((name, size, mtime)).encode("utf-8"))
    return digest.hexdigest()


def find_image(build_dir: Path, image_id: str) -> Path | None:
    for ext in IMAGE_EXTENSIONS:
        path = build_dir / "images" / (image_id + ext)
        if path.is_file():
            return path
    return None


def find_clip(build_dir: Path, image_id: str) -> Path | None:
    """Clip image-to-video: video-build/clips/IMG-xx.mp4 — engine ưu tiên hơn ảnh."""
    for ext in CLIP_EXTENSIONS:
        path = build_dir / "clips" / (image_id + ext)
        if path.is_file():
            return path
    return None


def missing_images(build_dir: Path, events: list[dict]) -> list[str]:
    """Danh sách IMG-id chưa có file trong images/ (theo thứ tự xuất hiện đầu tiên)."""
    needed: list[str] = []
    seen: set[str] = set()
    for event in events:
        image_id = event.get("image_id")
        if image_id and image_id not in seen:
            seen.add(image_id)
            needed.append(image_id)
    return [image_id for image_id in needed if find_image(build_dir, image_id) is None]


def clip_status(build_dir: Path, events: list[dict]) -> dict[str, list[str]]:
    """Trạng thái clip image-to-video — chỉ thông tin, KHÔNG gate build.

    present/missing theo thứ tự xuất hiện đầu tiên (cùng pattern missing_images).
    """
    needed: list[str] = []
    seen: set[str] = set()
    for event in events:
        image_id = event.get("image_id")
        if image_id and image_id not in seen:
            seen.add(image_id)
            needed.append(image_id)
    present = [image_id for image_id in needed if find_clip(build_dir, image_id) is not None]
    missing = [image_id for image_id in needed if image_id not in present]
    return {"present": present, "missing": missing}


def split_audio_by_sections(merged: Path, out_dir: Path, sections: list[dict]) -> list[dict]:
    """Cắt audio ghép tại mốc section (giây thật) → 1 file/section.

    File đặt tên theo tên section (01_section-01.mp3) để sorted glob == thứ tự section.
    Trả về danh sách {file, section, expected, actual} đo lại bằng ffprobe.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    for sec in sections:
        file_stem = sec.get("file", "")
        name = "%s.mp3" % file_stem[:-4] if file_stem.endswith(".txt") else "section-%s.mp3" % sec["id"]
        start = float(sec["start_s"])
        duration = float(sec["end_s"]) - start
        if duration <= 0:
            continue
        output = out_dir / name
        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error",
                "-ss", "%.3f" % start, "-t", "%.3f" % duration,
                "-i", str(merged), "-c", "copy", str(output),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=600,
        )
        actual = None
        probe = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(output),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if probe.returncode == 0:
            try:
                actual = round(float(probe.stdout.strip()), 3)
            except ValueError:
                actual = None
        results.append({"file": name, "section": sec["id"], "expected": round(duration, 3), "actual": actual})
    return results


def import_images(build_dir: Path) -> tuple[bool, str]:
    """Import ảnh từ video-build/import/ theo thứ tự mtime (thứ tự gen == thứ tự prompt).

    Chạy đúng mode --import-images của tool (đổi tên + di chuyển vào images/).
    Không có ảnh trong import/ → (False, ""). Lỗi → (False, log cuối).
    """
    import_dir = build_dir / "import"
    if not import_dir.is_dir():
        return False, ""
    files = [p for p in import_dir.iterdir()
             if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
    if not files:
        return False, ""
    result = subprocess.run(
        [tool_python(), str(build_video_script()), str(build_dir),
         "--import-images", str(import_dir), "--yes"],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        return False, (result.stdout or "")[-2000:]
    return True, (result.stdout or "").strip()


def render_video(build_dir: Path, options: dict[str, Any]) -> tuple[bool, str]:
    """Ráp video bằng build-video.py. options: motion/animation, transition (giây),
    resolution [w, h], dry_run, subtitles."""
    command = [tool_python(), str(build_video_script()), str(build_dir)]
    animation = options.get("animation")
    if animation:
        command += ["--animation", animation]
    elif options.get("motion"):
        command.append("--motion")
    fx = options.get("fx")
    if fx and fx != "none":
        command += ["--fx", str(fx)]
        intensity = options.get("fx_intensity")
        if intensity is not None:
            command += ["--grain", str(int(intensity))]
    if options.get("transition"):
        command += ["--transition", str(options["transition"])]
    if options.get("resolution"):
        command += ["--resolution", "%dx%d" % tuple(options["resolution"])]
    hw = options.get("hw", "auto")
    if hw and hw != "auto":
        command += ["--hw", str(hw)]
    jobs_n = options.get("build_jobs")
    if jobs_n:
        command += ["--jobs", str(int(jobs_n))]
    dry_run = bool(options.get("dry_run"))
    if dry_run:
        command.append("--dry-run")
    # Phụ đề chỉ khi rap thật — giống GUI: không đốt phụ đề khi xem trước.
    if options.get("subtitles") and not dry_run:
        command.append("--subtitles")
    # KHÔNG timeout: video dài (45+ phút × burn sub) cần hàng giờ; kill tuỳ ý
    # qua tab Jobs nền. Timeout cứng 60' trước đây từng giết job giữa burn.
    try:
        result = subprocess.run(command)
        output = ""
    except KeyboardInterrupt:
        return False, "build-video.py bị dừng thủ công."
    # dry-run KHÔNG tạo video-final.mp4 — thành công là returncode 0.
    ok = result.returncode == 0 and (dry_run or (build_dir / "video-final.mp4").is_file())
    if not ok:
        output = "build-video.py exit code %d — chi tiết trong job log." % result.returncode
    return ok, output
