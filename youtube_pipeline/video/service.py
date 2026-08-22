"""Service Dựng video (Flow 3) — tách khỏi pipeline, chỉ liên kết qua dữ liệu.

Pipeline dừng ở `resource_pack` (tài nguyên đã đủ). Người dùng tự gen TTS + ảnh
ngoài tool rồi bỏ vào:
- audio GHÉP (toàn bộ video) -> `runs/<run_id>/audio/`  (timeline đo duration thật)
- ảnh IMG-xx -> `runs/<run_id>/video-build/images/` (hoặc `import/` để tự đổi tên
  theo thứ tự mtime — cùng quy ước với helper `import_images` của pipeline)

Trang web "Dựng video" gọi service này: check còn thiếu gì -> chuẩn bị pack
(timeline FINAL, prompts-build.py, marks.tsv, cắt audio theo section)
-> chạy youtube_pipeline/video/engine.py để rap `video-build/video-final.mp4`.

Bất biến:
- KHÔNG sửa `run_state.json` (config_snapshot là lịch sử, server không ghi).
- KHÔNG sửa visuals/* của pipeline (timeline.md/timeline-meta.json thuộc cơ chế
  resume của stage `timeline` — service tự tính timeline trong bộ nhớ).
- Chỉ ghi vào `video-build/` (pack) — nơi build-video.py đọc.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

from .timeline import build_timeline, find_audio_file, probe_duration
from .logo_cleanup import clean_clips
from .build import (
    ANIM_MODES,
    build_marks_tsv,
    build_video_script,
    clip_status,
    import_images,
    missing_images,
    render_rows,
    render_video,
    split_audio_by_sections,
    tool_python,
)

# Mặc định giống VIDEO_BUILD_DEFAULTS của stage video_build cũ — người dùng có
# thể chọn lại từ web khi bấm Dựng video.
BUILD_DEFAULTS = {
    "motion": True,
    "animation": "zoom",
    "transition": 0.5,
    "resolution": [1280, 720],
    "render": True,
    "dry_run": False,
    "subtitles": False,
    "logo_cleanup": False,
    "logo_mode": "delogo",
}

# Style phụ đề mặc định — copy từ youtube_pipeline/video/engine.py (SUB_DEFAULTS + JP_FONTS);
# web đọc/ghi video-build/sub-style.json để build-video.py --subtitles tự đọc.
SUB_DEFAULTS = {
    "font": "Hiragino Kaku Gothic Pro",
    "fontsize": 44,
    "color": "#FFFFFF",
    "outline": 3,
    "outline_color": "#000000",
    "shadow": 1,
    "bold": False,
    "position": "bottom",
    "margin_v": 36,
}
JP_FONTS = ["Hiragino Kaku Gothic Pro", "Hiragino Maru Gothic ProN",
            "Hiragino Mincho ProN", "Hiragino Sans GB"]
_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

# Artifact nguồn cần có (đường dẫn trong run_dir) — do pipeline sinh ở stage
# planning / sections / image_strategy / storyboard. Kịch bản quyết định video
# qua pipeline (sửa artifact -> resume -> gen TTS lại -> Dựng), KHÔNG qua
# video-build/script.txt.
REQUIRED_ARTIFACTS = (
    ("planning", "script/planning.json"),
    ("sections", "script/sections.json"),
    ("image_strategy", "visuals/strategy.json"),
    ("storyboard", "visuals/storyboard.json"),
)


class BuildError(Exception):
    """Thiếu artifact nguồn — không thể dựng timeline."""


# ------------------------------------------------------------------- helpers


def _read_json(run_dir: Path, rel: str) -> dict:
    """Đọc JSON trong run_dir với guard path traversal (chỉ nằm trong run_dir)."""
    root = run_dir.resolve()
    path = (root / rel).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise BuildError("Thiếu artifact: %s" % rel)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError("Artifact hỏng: %s (%s)" % (rel, exc))
    if not isinstance(value, dict):
        raise BuildError("Artifact sai định dạng: %s" % rel)
    return value


def _load_sources(run_dir: Path) -> dict:
    """Đọc 4 artifact nguồn; BuildError nếu thiếu/hỏng — trả dict theo tên."""
    root = run_dir.resolve()
    sources: dict[str, Any] = {}
    for key, rel in REQUIRED_ARTIFACTS:
        if key == "storyboard":
            # storyboard.json là LIST các row (đúng shape build_timeline nhận).
            path = (root / rel).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise BuildError("Thiếu artifact: %s" % rel)
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise BuildError("Artifact hỏng: %s (%s)" % (rel, exc))
            if not isinstance(value, list):
                raise BuildError("Artifact sai định dạng (cần list): %s" % rel)
            sources[key] = value
        elif rel.endswith(".json"):
            sources[key] = _read_json(run_dir, rel)
    return sources


def _timeline_meta(run_dir: Path, sources: Optional[dict] = None) -> dict:
    """Timeline (FINAL nếu có audio thật) — tự tính, không đọc visuals/ của pipeline."""
    sources = sources if sources is not None else _load_sources(run_dir)
    audio_path = find_audio_file(run_dir / "audio")
    duration = probe_duration(audio_path) if audio_path is not None else None
    _markdown, meta = build_timeline(
        sources["storyboard"],
        sources["image_strategy"],
        sources["sections"],
        sources["planning"],
        duration=duration,
        audio_file=audio_path.name if audio_path is not None else None,
    )
    return meta


# ------------------------------------------------------------------- check


def check_assets(run_dir: Path) -> dict:
    """Trạng thái "còn thiếu gì" cho trang Dựng video — không spawn gì cả."""
    build_dir = run_dir / "video-build"
    result: dict[str, Any] = {
        "pipeline_ready": False,
        "missing_artifacts": [],
        "timeline_status": None,
        "audio": None,
        "audio_ready": False,
        "tts_chunks": {"available": False, "total": 0, "generated": 0, "chunks": [], "merge_output": None},
        "sections_count": None,
        "events_count": None,
        "unique_images": None,
        "images": {"present": 0, "missing": []},
        "images_ready": False,
        "pack_files": {"prompts_build": False, "marks_tsv": False},
        "pack_ready": False,
        "video_exists": (build_dir / "video-final.mp4").is_file(),
        "video_ready": False,
        "report": None,
        "missing_reason": None,
    }

    missing = [rel for _key, rel in REQUIRED_ARTIFACTS
               if not (run_dir.resolve() / rel).is_file()]
    if missing:
        result["missing_artifacts"] = missing
        result["missing_reason"] = "Run chưa qua pipeline đủ — thiếu: %s" % ", ".join(missing)
        result["report"] = _read_report(build_dir)
        return result

    try:
        meta = _timeline_meta(run_dir)
    except BuildError as exc:
        result["missing_reason"] = str(exc)
        result["report"] = _read_report(build_dir)
        return result

    result["pipeline_ready"] = True
    # Skeleton thư mục luôn có sẵn: người dùng biết chính xác chỗ bỏ audio/ảnh.
    for d in (run_dir / "audio", run_dir / "audio" / "chunks", run_dir / "subtitles",
              build_dir, build_dir / "audio", build_dir / "images",
              build_dir / "import", build_dir / "srt", build_dir / "clips"):
        d.mkdir(parents=True, exist_ok=True)
    result["timeline_status"] = meta["status"]
    # 2 file pack tự sinh khi bấm Dựng — hiển thị trạng thái checklist trên web.
    result["pack_files"] = {
        "prompts_build": (build_dir / "prompts-build.py").is_file(),
        "marks_tsv": (build_dir / "marks.tsv").is_file(),
    }
    result["sections_count"] = meta["section_count"]
    result["events_count"] = meta["event_count"]
    result["unique_images"] = meta["unique_images"]

    manifest_path = run_dir / "script" / "audio-chunks" / "manifest.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            rows = manifest.get("chunks") if isinstance(manifest, dict) else []
            if isinstance(rows, list):
                chunks = []
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    output = str(row.get("audio_output") or "")
                    ready = bool(output) and (run_dir / output).is_file()
                    chunks.append({
                        "id": str(row.get("id") or ""),
                        "file": str(row.get("file") or ""),
                        "path": str(row.get("path") or ""),
                        "chars": int(row.get("chars") or 0),
                        "audio_output": output,
                        "audio_ready": ready,
                    })
                result["tts_chunks"] = {
                    "available": bool(chunks),
                    "total": len(chunks),
                    "generated": sum(1 for row in chunks if row["audio_ready"]),
                    "chunks": chunks,
                    "merge_output": str(manifest.get("merge_output") or "audio/narration-merged.mp3"),
                }
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    audio = find_audio_file(run_dir / "audio")
    if audio is not None:
        result["audio"] = {
            "file": audio.name,
            "duration_seconds": meta.get("duration_seconds"),
            "measured_cpm": meta.get("measured_cpm"),
        }
        result["audio_ready"] = True

    events = meta.get("events", [])
    missing_imgs = missing_images(build_dir, events)
    present = meta["unique_images"] - len(missing_imgs) if meta["unique_images"] else 0
    result["images"] = {"present": max(present, 0), "missing": missing_imgs}
    result["images_ready"] = not missing_imgs
    result["clips"] = clip_status(build_dir, events)  # thông tin — không gate
    result["pack_ready"] = result["audio_ready"] and result["images_ready"]
    result["report"] = _read_report(build_dir)

    if not result["audio_ready"]:
        result["missing_reason"] = "Thiếu audio ghép — bỏ file vào runs/%s/audio/" % run_dir.name
    elif not result["images_ready"]:
        result["missing_reason"] = "Thiếu %d ảnh: %s — bỏ vào video-build/images/ với đúng tên" % (
            len(missing_imgs), ", ".join(missing_imgs[:8]) + ("…" if len(missing_imgs) > 8 else "")
        )
    elif result["video_exists"]:
        result["video_ready"] = True
        result["missing_reason"] = None
    else:
        result["missing_reason"] = None  # đủ tài nguyên — bấm Dựng video

    return result


def merge_tts_audio_chunks(run_dir: Path) -> dict:
    """Merge externally generated per-chunk narration into the normal audio input.

    The resource pack owns text chunks; external TTS owns the individual MP3s.
    This small bridge produces the one audio file expected by SRT and video
    build without changing any script or timeline artifact.
    """
    manifest_path = run_dir / "script" / "audio-chunks" / "manifest.json"
    if not manifest_path.is_file():
        raise BuildError("Chưa có TTS chunk manifest; hãy chạy Resource Pack trước.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError("TTS chunk manifest hỏng: %s" % exc) from exc
    rows = manifest.get("chunks") if isinstance(manifest, dict) else None
    if not isinstance(rows, list) or not rows:
        raise BuildError("TTS chunk manifest không có chunks.")
    audio_files = []
    for row in rows:
        if not isinstance(row, dict):
            raise BuildError("TTS chunk manifest có row không hợp lệ.")
        rel = str(row.get("audio_output") or "")
        path = (run_dir / rel).resolve()
        if not rel or not path.is_relative_to(run_dir.resolve()) or not path.is_file():
            raise BuildError("Thiếu audio TTS chunk: %s" % (rel or "unknown"))
        audio_files.append(path)
    if not shutil.which("ffmpeg"):
        raise BuildError("Chưa cài ffmpeg; không thể ghép audio chunks.")
    output = (run_dir / str(manifest.get("merge_output") or "audio/narration-merged.mp3")).resolve()
    if not output.is_relative_to(run_dir.resolve()):
        raise BuildError("merge_output ngoài run directory.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", prefix="tts-concat-", suffix=".txt", delete=False) as handle:
        concat_path = Path(handle.name)
        for audio in audio_files:
            handle.write("file '%s'\n" % str(audio).replace("'", "'\\''"))
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_path), "-vn", "-c:a", "libmp3lame", "-b:a", "192k", str(output)],
            capture_output=True,
            text=True,
            timeout=600,
        )
    finally:
        concat_path.unlink(missing_ok=True)
    if result.returncode != 0 or not output.is_file():
        raise BuildError("ffmpeg ghép TTS chunks thất bại: %s" % (result.stderr[-800:] or "unknown error"))
    return {"output": str(output.relative_to(run_dir)), "chunks": len(audio_files), "size_bytes": output.stat().st_size}


def _read_report(build_dir: Path) -> Optional[dict]:
    path = build_dir / "build-report.json"
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


# ------------------------------------------------------------------- build


def _write_report(build_dir: Path, report: dict) -> None:
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / "build-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# --------------------------------------------------------------- style phụ đề


def read_sub_style(run_dir: Path) -> dict:
    """Style phụ đề: defaults + video-build/sub-style.json (nếu có, file lỗi → mặc định).

    Giống hệt load_sub_style của build-video.py — file lỗi không raise, dùng mặc định.
    """
    style = dict(SUB_DEFAULTS)
    path = run_dir.resolve() / "video-build" / "sub-style.json"
    if path.is_file():
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                style.update({k: v for k, v in saved.items() if k in style})
        except (OSError, json.JSONDecodeError):
            pass
    return style


def write_sub_style(run_dir: Path, style: dict) -> dict:
    """Validate + ghi video-build/sub-style.json (build-video.py --subtitles tự đọc).

    ValueError khi field sai — route chuyển thành 400.
    """
    merged = dict(SUB_DEFAULTS)
    if not isinstance(style, dict):
        raise ValueError("style phải là object JSON")
    merged.update({k: v for k, v in style.items() if k in merged})

    if merged["font"] not in JP_FONTS:
        raise ValueError("font phải là một trong: %s" % ", ".join(JP_FONTS))
    for key, lo, hi in (("fontsize", 28, 80), ("outline", 0, 6),
                        ("shadow", 0, 5), ("margin_v", 0, 200)):
        value = merged[key]
        if not isinstance(value, (int, float)) or isinstance(value, bool) \
                or not (lo <= value <= hi):
            raise ValueError("%s phải là số trong %d–%d" % (key, lo, hi))
        merged[key] = int(value)
    for key in ("color", "outline_color"):
        if not isinstance(merged[key], str) or not _HEX_RE.match(merged[key]):
            raise ValueError("%s phải dạng #RRGGBB" % key)
    if not isinstance(merged["bold"], bool):
        raise ValueError("bold phải là boolean")
    if merged["position"] not in ("bottom", "top", "middle"):
        raise ValueError("position phải là bottom|top|middle")

    build_dir = run_dir.resolve() / "video-build"
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / "sub-style.json").write_text(
        json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return merged


# --------------------------------------------------------------- import ảnh

_IMPORT_MAP_LINE = re.compile(r"^\s+(IMG-\d+)\s+<-\s+(.+)$")
_MANIFEST_LINE = re.compile(r"^\s*(IMG-\d+)\s*\|\s*([^|#\n]+)")
_IMG_EXT = frozenset({".jpg", ".jpeg", ".png", ".webp"})


def _read_manifest(source_dir: Path) -> tuple[list[str], list[str]]:
    """Đọc IMPORT_MANIFEST.txt trong source_dir → (img_order_cli, warnings).

    IMPORT_MANIFEST.txt format: IMG-xx | filename.jpg | mô tả
    img_order_cli: list IMG-id theo thứ tự alphabetical của file ảnh trong source_dir.
    Trả ([], warnings) nếu không tìm thấy hoặc manifest rỗng.
    """
    manifest = source_dir / "IMPORT_MANIFEST.txt"
    if not manifest.is_file():
        return [], []

    img_to_file: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _MANIFEST_LINE.match(line)
        if m:
            img_to_file[m.group(1).strip()] = m.group(2).strip()

    if not img_to_file:
        return [], ["IMPORT_MANIFEST.txt không có dòng hợp lệ"]

    file_to_img = {fname: img for img, fname in img_to_file.items()}
    clean_files = sorted(
        p for p in source_dir.iterdir()
        if p.is_file() and p.suffix.lower() in _IMG_EXT
    )

    warnings: list[str] = []
    img_order_cli: list[str] = []
    unmatched: list[str] = []
    for cf in clean_files:
        img = file_to_img.get(cf.name)
        if img:
            img_order_cli.append(img)
        else:
            unmatched.append(cf.name)
    if unmatched:
        warnings.append(
            "%d file không có trong manifest: " % len(unmatched)
            + ", ".join(unmatched[:5]) + ("..." if len(unmatched) > 5 else "")
        )
    return img_order_cli, warnings


def _scene_hints(run_dir: Path) -> dict[str, str]:
    """IMG-id → mô tả scene ngắn (để đối chiếu tay khi sửa manifest).

    Ưu tiên visual_information của storyboard (mô tả nội dung), fallback prompt
    của prompt-pack. Bỏ phần style prefix ở đầu vì mọi ảnh giống nhau.
    """
    hints: dict[str, str] = {}
    visuals = run_dir.resolve() / "visuals"
    try:
        events = json.loads((visuals / "storyboard.json").read_text(encoding="utf-8"))
        for event in events if isinstance(events, list) else []:
            img = event.get("image_id")
            text = (event.get("visual_information") or "").strip()
            if img and text and img not in hints:
                hints[img] = text
    except (OSError, json.JSONDecodeError):
        pass
    try:
        pack = json.loads((visuals / "prompt-pack.json").read_text(encoding="utf-8"))
        for entry in pack.get("images", []) if isinstance(pack, dict) else []:
            img = entry.get("image_id")
            text = (entry.get("prompt") or "").strip()
            if img and text and img not in hints:
                hints[img] = text
    except (OSError, json.JSONDecodeError):
        pass
    # Bỏ style prefix (mọi ảnh chung 1 style) → lấy phần mô tả riêng của scene.
    cleaned: dict[str, str] = {}
    for img, text in hints.items():
        text = re.sub(r"^(16:9|2d cartoon illustration|cinematic photorealistic|flat illustrated|watercolor)[^.]*\.\s*", "",
                      text, count=1, flags=re.IGNORECASE)
        text = re.sub(r"^[^.]*(?:background|tungsten|chiaroscuro|no gradients|solid colors)[^.]*\.\s*", "",
                      text, count=1, flags=re.IGNORECASE)
        cleaned[img] = " ".join(text.split())[:110]
    return cleaned


def _write_manifest(
    source_dir: Path, run_dir: Path, mapping: list[dict]
) -> Optional[str]:
    """Ghi IMPORT_MANIFEST.txt (khung mapping để user đối chiếu + sửa tay).

    mapping: [{"img": "IMG-01", "file": "abc.jpg"}] — thứ tự đoán được từ preview.
    KHÔNG ghi đè nếu file đã tồn tại (mapping user đã sửa là nguồn sự thật).
    Trả tên file đã ghi, hoặc None nếu bỏ qua.
    """
    manifest = source_dir / "IMPORT_MANIFEST.txt"
    if manifest.exists() or not mapping:
        return None
    hints = _scene_hints(run_dir)
    lines = [
        "# IMPORT_MANIFEST — mapping ảnh -> IMG-xx cho run %s" % run_dir.name,
        "# Thứ tự dưới đây là ĐOÁN (theo timestamp/mtime tên file) — hãy đối chiếu",
        "# cột mô tả scene rồi sửa cột tên file cho khớp. Sửa xong gọi lại",
        "# import-images với apply=true; file này thắng mọi cách sort tự động.",
        "# Format: IMG-xx | tên_file.jpg | mô tả scene",
        "#",
    ]
    for item in mapping:
        img = item.get("img", "")
        lines.append("%s | %s | %s" % (img, item.get("file", ""), hints.get(img, "")))
    try:
        manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        return None
    return manifest.name


def _img_order_for_import(run_dir: Path) -> list[str]:
    """Thứ tự IMG cần có, tính từ storyboard — KHÔNG cần audio.

    Thứ tự IMG chỉ phụ thuộc storyboard/image_strategy; chỉ mốc thời gian mới cần
    thời lượng audio. Nhờ vậy đổi tên ảnh được ngay sau khi gen ảnh, không phải
    chờ TTS. Trả [] nếu run chưa đủ artifact → build-video.py tự đọc
    prompts-build.py như cũ và báo lỗi của nó.
    """
    try:
        meta = _timeline_meta(run_dir)
    except BuildError:
        return []
    order: list[str] = []
    for event in meta.get("events", []):
        img = event.get("image_id")
        if img and img not in order:
            order.append(img)
    return order


def import_pack_images(
    run_dir: Path,
    source_dir: str,
    insert: Optional[str] = None,
    apply: bool = False,
) -> dict:
    """Import ảnh đã gen vào video-build/images/.

    Thứ tự IMG được xác định theo:
    1. IMPORT_MANIFEST.txt trong source_dir (nếu có) — mapping tường minh
       `IMG-xx | filename.jpg | mô tả`, chính xác 100%. Sửa file này là sửa mapping.
    2. Mặc định: storyboard IMG order (thứ tự xuất hiện) + build-video.py tự sort
       file theo timestamp / số thứ tự / mtime. Thứ tự này chỉ là ĐOÁN — timestamp
       trong tên file thường chỉ có độ phân giải phút nên nhiều ảnh trùng khóa sort.

    Flow 2 bước cho ảnh không có số thứ tự trong tên:
    - apply=False lần đầu: ghi IMPORT_MANIFEST.txt vào source_dir kèm mô tả scene
      để user đối chiếu và sửa cột tên file.
    - apply=True sau khi sửa: manifest được dùng làm mapping chính thức.

    Trả {ok, mapping, extra, output, source, manifest_written?, warnings?, error?}.
    source: "manifest" (đọc từ file) | "auto" (đoán theo sort).
    """
    source = Path(source_dir).expanduser()
    build_dir = run_dir.resolve() / "video-build"
    build_dir.mkdir(parents=True, exist_ok=True)

    img_order = _img_order_for_import(run_dir)
    warnings: list[str] = []
    manifest_order: list[str] = []
    if source.is_dir():
        manifest_order, warnings = _read_manifest(source)

    command = [tool_python(), str(build_video_script()), str(build_dir),
               "--import-images", str(source)]
    # Manifest (mapping tường minh) thắng storyboard order.
    effective_order = manifest_order if manifest_order else img_order
    if effective_order:
        command += ["--img-order", ",".join(effective_order)]
    if insert:
        command += ["--insert", insert]
    if apply:
        command.append("--yes")
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return {"ok": False, "mapping": [], "extra": 0,
                "output": "", "error": "Import quá lâu (60s) — kiểm tra thư mục nguồn."}
    output = (result.stdout or "") + (result.stderr or "")
    mapping: list[dict] = []
    extra = 0
    for line in output.splitlines():
        match = _IMPORT_MAP_LINE.match(line)
        if match:
            mapping.append({"img": match.group(1), "file": match.group(2).strip()})
        elif "DƯ" in line or "DU" in line:
            found = re.search(r"(\d+)\s+anh D", line)
            if found:
                extra = int(found.group(1))
    if result.returncode != 0:
        return {"ok": False, "mapping": mapping, "extra": extra,
                "output": output, "error": (output or "").strip()[-2000:]}
    resp: dict = {"ok": True, "mapping": mapping, "extra": extra, "output": output}
    resp["source"] = "manifest" if manifest_order else "auto"
    # Chưa có manifest + đang xem trước -> ghi khung ra để user đối chiếu và sửa.
    # Không ghi khi apply (ảnh đã move, manifest vô nghĩa) hoặc khi đã có manifest.
    if not manifest_order and not apply and source.is_dir():
        written = _write_manifest(source, run_dir, mapping)
        if written:
            resp["manifest_written"] = written
            warnings.append(
                "Thứ tự trên là ĐOÁN theo tên file/mtime — mở %s trong thư mục ảnh, "
                "đối chiếu mô tả scene và sửa cột tên file, rồi gọi lại với apply=true."
                % written
            )
    if warnings:
        resp["warnings"] = warnings
    return resp


def build_pack(
    run_dir: Path,
    options: Optional[dict] = None,
    log: Optional[Callable[[str], None]] = None,
) -> dict:
    """Chuẩn bị pack + rap video. options: motion, transition, resolution, render.

    Trả về build-report (status: WAITING_AUDIO | SPLIT_FAILED | WAITING_IMAGES |
    PACK_READY | RENDERED | RENDER_FAILED). KHÔNG raise khi thiếu audio/ảnh —
    đó là trạng thái chờ, không phải lỗi. Raise BuildError khi run thiếu artifact
    nguồn (chưa qua pipeline đủ).
    """
    log = log or (lambda _message: None)
    opts = {**BUILD_DEFAULTS, **(options or {})}
    sources = _load_sources(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    build_dir = run_dir / "video-build"
    for d in (run_dir / "audio", run_dir / "subtitles",
              build_dir, build_dir / "audio", build_dir / "images",
              build_dir / "import", build_dir / "srt", build_dir / "clips"):
        d.mkdir(parents=True, exist_ok=True)

    report: dict = {
        "tool": str(build_video_script()),
        "service": "youtube_pipeline.build_service",
        "options": {k: opts[k] for k in (
        "motion", "animation", "transition", "resolution", "render", "dry_run", "subtitles", "logo_cleanup", "logo_mode")},
        "generated_at": _utc_now(),
        "status": "PACK_READY",
        "next_step": "",
    }

    audio_path = find_audio_file(run_dir / "audio")
    duration = probe_duration(audio_path) if audio_path is not None else None
    if audio_path is None:
        report["status"] = "WAITING_AUDIO"
        report["next_step"] = "Bỏ file audio ghép vào audio/ rồi bấm Dựng video lại."
        _write_report(build_dir, report)
        return report

    _markdown, meta = build_timeline(
        sources["storyboard"],
        sources["image_strategy"],
        sources["sections"],
        sources["planning"],
        duration=duration,
        audio_file=audio_path.name,
    )
    report["timeline_status"] = meta["status"]
    report["script_chars"] = meta.get("script_chars")
    report["section_count"] = meta.get("section_count")
    report["event_count"] = meta.get("event_count")
    report["unique_images"] = meta.get("unique_images")

    sections = meta.get("sections", [])
    events = meta.get("events", [])
    if not sections or not events:
        raise BuildError("Không dựng được timeline: sections/events rỗng — run thiếu dữ liệu section.")

    # 1) Text pack — tái sinh mỗi lần dựng.
    log("Sinh prompts-build.py + marks.tsv…")
    (build_dir / "prompts-build.py").write_text(render_rows(events, sections), encoding="utf-8")
    (build_dir / "marks.tsv").write_text(build_marks_tsv(sections), encoding="utf-8")
    report["prompts_build_rows"] = len(events)
    resources = ["prompts-build.py", "marks.tsv"]

    # 2) Cắt audio ghép theo mốc section -> audio/ (1 file = 1 section).
    # Dọn pack audio cũ trước — build-video.py yêu cầu đếm audio == section,
    # file thừa từ lần dựng trước sẽ làm FAIL đếm lệch (vd audio ghép bị copy vào).
    audio_out = build_dir / "audio"
    for old in audio_out.glob("*"):
        if old.is_file():
            try:
                old.unlink()
            except OSError:
                pass
    log("Cắt audio theo %d section (%s, %.1fs)…" % (len(sections), audio_path.name, duration or 0))
    try:
        splits = split_audio_by_sections(audio_path, audio_out, sections)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        report["status"] = "SPLIT_FAILED"
        report["error"] = "%s: %s" % (type(exc).__name__, exc)
        report["next_step"] = "Kiểm tra file audio ghép (hỏng/mã hóa lạ?) rồi bấm Dựng video lại."
        _write_report(build_dir, report)
        return report
    report["audio"] = {"file": audio_path.name, "duration_seconds": meta.get("duration_seconds")}
    report["audio_splits"] = splits
    drift = sum(abs((s.get("actual") or s["expected"]) - s["expected"]) for s in splits)
    report["split_drift_seconds"] = round(drift, 3)
    resources.append("audio/ (%d file)" % len(splits))
    log("Đã cắt %d file audio (drift %.3fs)." % (len(splits), report["split_drift_seconds"]))

    # 3) Import ảnh từ import/ nếu có (thứ tự mtime == thứ tự prompt).
    imported, import_log = import_images(build_dir)
    if imported:
        report["import"] = {"status": "ok", "log": import_log}
        log("Đã import ảnh từ import/.")

    # 4) SRT tùy chọn: subtitles/*.srt -> video-build/srt/ + root pack.
    srt_dir = run_dir / "subtitles"
    srt_files = sorted(srt_dir.glob("*.srt")) if srt_dir.is_dir() else []
    for srt_path in srt_files:
        shutil.copy2(srt_path, build_dir / "srt" / srt_path.name)
        shutil.copy2(srt_path, build_dir / srt_path.name)
    report["srt"] = {"files": [p.name for p in srt_files]} if srt_files else {"files": []}

    # 5) Thiếu ảnh -> WAITING_IMAGES (không dựng). Clip chỉ là lớp ưu tiên — thiếu
    #    clip KHÔNG chặn; status chỉ báo thông tin để web hiển thị.
    report["clips"] = clip_status(build_dir, events)
    missing = missing_images(build_dir, events)
    if missing:
        report["status"] = "WAITING_IMAGES"
        report["missing_images"] = missing
        report["missing_count"] = len(missing)
        report["resources"] = resources
        report["next_step"] = (
            "Gen %d ảnh từ visuals/prompts/prompts-ALL.txt rồi bỏ vào video-build/images/ "
            "với đúng tên IMG-xx (hoặc import/ để tự đổi tên), bấm Dựng video lại." % len(missing)
        )
        _write_report(build_dir, report)
        return report

    clips_note = ["clips/ (%d file)" % len(report["clips"]["present"])] if report["clips"]["present"] else []
    report["resources"] = resources + ["images/ (đầy đủ)"] + clips_note

    if opts.get("logo_cleanup") and report["clips"]["present"]:
        cleanup = clean_clips(build_dir, mode=opts.get("logo_mode", "delogo"), log=log)
        report["logo_cleanup"] = cleanup
        if cleanup["failed"]:
            report["status"] = "RENDER_FAILED"
            report["error"] = "Logo cleanup thất bại: %s" % cleanup["failed"]
            report["next_step"] = "Kiểm tra FFmpeg và vùng watermark, rồi chạy lại. Bản gốc nằm trong video-build/clips-original/."
            _write_report(build_dir, report)
            return report

    # 6) Chỉ chuẩn bị pack (render=false) — dừng ở PACK_READY.
    if not opts.get("render"):
        report["status"] = "PACK_READY"
        report["next_step"] = "Pack đầy đủ. Bấm ▶ Ráp video trên web để tạo video-final.mp4."
        _write_report(build_dir, report)
        return report

    # 7) Rap video bằng youtube_pipeline/video/engine.py (hoặc chạy --dry-run khi xem trước).
    log("Chạy build-video.py (%s) — dry-run có thể mất chục giây, rap thật vài phút…" % build_dir)
    ok, output = render_video(build_dir, opts)
    if not ok:
        report["status"] = "RENDER_FAILED"
        report["error"] = output[-2000:]
        report["next_step"] = "Xem log trên; sửa tài nguyên rồi bấm Dựng video lại."
        _write_report(build_dir, report)
        return report
    command_parts = ["build-video.py <video-build>",
                     "--animation %s" % opts["animation"],
                     "--transition %.1fs" % opts["transition"],
                     "--resolution %dx%d" % tuple(opts["resolution"])]
    if opts.get("dry_run"):
        command_parts.append("--dry-run")
    if opts.get("subtitles") and not opts.get("dry_run"):
        command_parts.append("--subtitles")
    report["render"] = {"command": " ".join(command_parts), "output": output[-500:]}
    if opts.get("dry_run"):
        report["status"] = "DRY_RUN_OK"
        report["next_step"] = "Dry-run OK — timeline hợp lệ. Bấm ▶ Ráp video để tạo video-final.mp4."
        _write_report(build_dir, report)
        log("Dry-run hoàn tất — chưa tạo video.")
        return report
    report["status"] = "RENDERED"
    report["next_step"] = "Xem video-build/video-final.mp4 — chỉnh animation/transition/resolution rồi Dựng lại nếu cần."
    _write_report(build_dir, report)
    log("Hoàn tất: %s" % (build_dir / "video-final.mp4"))
    return report


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


# -------------------------------------------------------------------- CLI job


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m youtube_pipeline.build_service",
        description="Dựng video cho một run (Flow 3) — chạy như subprocess job của API.",
    )
    parser.add_argument("run_dir", type=str, help="Thư mục run (runs/<run_id>)")
    parser.add_argument("--prepare-only", action="store_true",
                        help="Chỉ chuẩn bị pack, không rap video (PACK_READY).")
    parser.add_argument("--no-motion", action="store_true", help="Tắt hiệu ứng motion.")
    parser.add_argument("--animation", type=str, default=None,
                        choices=ANIM_MODES,
                        help="Mode animation: %s (mặc định zoom)." % "|".join(ANIM_MODES))
    parser.add_argument("--transition", type=float, default=BUILD_DEFAULTS["transition"],
                        help="Độ dài transition giây (mặc định %.1f)." % BUILD_DEFAULTS["transition"])
    parser.add_argument("--resolution", type=str, default="%dx%d" % tuple(BUILD_DEFAULTS["resolution"]),
                        help="Độ phân giải WxH (mặc định 1280x720).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Xem trước: chạy build-video.py --dry-run (kiểm tra timeline, không rap).")
    parser.add_argument("--subtitles", action="store_true",
                        help="Đốt phụ đề srt/ theo video-build/sub-style.json khi rap.")
    parser.add_argument("--logo-cleanup", action="store_true",
                        help="Xử lý watermark cố định ở góc phải dưới của clip.")
    parser.add_argument("--logo-mode", choices=("delogo", "blur"), default="delogo",
                        help="Cách xử lý watermark: delogo hoặc blur.")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """Entrypoint job — stdout là job log (fd kế thừa từ runner, không PIPE)."""
    args = build_parser().parse_args(argv)
    run_dir = Path(args.run_dir).expanduser().resolve()
    options: dict[str, Any] = {
        "motion": not args.no_motion,
        "animation": args.animation or BUILD_DEFAULTS["animation"],
        "transition": args.transition,
        "resolution": args.resolution,
        "render": not args.prepare_only,
        "dry_run": args.dry_run,
        "subtitles": args.subtitles,
        "logo_cleanup": args.logo_cleanup,
        "logo_mode": args.logo_mode,
    }
    try:
        resolution = tuple(int(part) for part in args.resolution.lower().split("x"))
        if len(resolution) != 2 or not all(64 <= v <= 4096 for v in resolution):
            print("resolution phải dạng WxH (64–4096): %s" % args.resolution, file=sys.stderr)
            return 2
        options["resolution"] = list(resolution)
    except ValueError:
        print("resolution phải dạng WxH: %s" % args.resolution, file=sys.stderr)
        return 2

    print("=== Dựng video — %s ===" % run_dir)
    print("Tool: %s" % build_video_script())
    print("Python: %s" % tool_python())
    try:
        report = build_pack(run_dir, options, log=lambda m: print("[build] %s" % m))
    except BuildError as exc:
        print("LỖI: %s" % exc, file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 — job phải exit khác 0, không nuốt lỗi
        import traceback

        traceback.print_exc()
        print("LỖI không lường trước: %s" % exc, file=sys.stderr)
        return 1
    print("Status: %s" % report["status"])
    if report.get("next_step"):
        print("Bước tiếp: %s" % report["next_step"])
    return 0 if report["status"] in (
        "RENDERED", "DRY_RUN_OK", "PACK_READY", "WAITING_AUDIO", "WAITING_IMAGES") else 1


if __name__ == "__main__":
    sys.exit(main())
