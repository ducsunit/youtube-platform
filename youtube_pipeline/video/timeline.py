"""Bảng timeline cho resource pack — sinh tự động ngay sau stage image_prompts.

Hai trạng thái:
- FINAL_TIMING: có file audio thật trong runs/<run_id>/audio/ → đo duration bằng ffprobe,
  phân bổ section theo tỉ lệ ký tự trên tổng duration thật, tính CPM đo được.
- DRAFT_TIMING: chưa có audio → tổng dự kiến từ sections.section_policy.estimated_max_seconds
  (tính theo CPM tối thiểu của profile MiniMax 380–400).

Sections lấy từ script/sections.json (stage `sections`): số section khớp planning.json
(S1..SN) nên mọi beat/event đều map được cửa sổ. Cả hai chế độ đều không bịa mốc:
event chia đều trong cửa sổ section của beat nó.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

AUDIO_EXTENSIONS = (".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg")
CALIBRATED_CPM_MIN = 380
CALIBRATED_CPM_MAX = 400
FALLBACK_CPM = 380


def find_audio_file(audio_dir: Path) -> Path | None:
    """File audio ghép trong thư mục audio (lấy file to nhất theo dung lượng)."""
    if not audio_dir.is_dir():
        return None
    candidates = [p for ext in AUDIO_EXTENSIONS for p in audio_dir.glob("*" + ext)]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_size)


def probe_duration(path: Path) -> float | None:
    """Duration giây bằng ffprobe; None nếu ffprobe thiếu hoặc đo lỗi."""
    if not shutil.which("ffprobe"):
        return None
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return None
        return float(result.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _fmt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    minutes, secs = divmod(int(round(seconds)), 60)
    return "%d:%04.1f" % (minutes, secs)


def build_timeline(
    storyboard: list[dict],
    strategy: dict,
    sections_manifest: dict,
    planning: dict,
    duration: float | None = None,
    audio_file: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Trả về (markdown timeline, meta). duration=None → DRAFT_TIMING.

    sections_manifest = script/sections.json: sections [{id, chars, file}]
    (số section khớp planning; `file` là tên quy ước cho audio cắt theo section).
    """
    rows = list(storyboard)
    beats_by_id = {b.get("id"): b for b in strategy.get("visual_beats", [])}
    sections = [s for s in planning.get("sections", []) if s.get("id")]
    functions = {s["id"]: s.get("segment_function", "") for s in sections}

    section_ids: list[str] = []
    chars_by_section: dict[str, int] = {}
    file_by_section: dict[str, str] = {}
    text_by_section: dict[str, str] = {}
    for row in sections_manifest.get("sections", []):
        sec = row.get("id")
        if sec is None:
            continue
        if sec not in section_ids:
            section_ids.append(sec)
        chars_by_section[sec] = chars_by_section.get(sec, 0) + int(row.get("chars", 0))
        if row.get("file"):
            file_by_section[sec] = row["file"]
        if row.get("text"):
            text_by_section[sec] = row["text"]
    total_chars = sum(chars_by_section.values()) or int(sections_manifest.get("total_chars", 0))

    warnings: list[str] = []
    if duration is not None and duration > 0:
        total = float(duration)
        status = "FINAL_TIMING"
        measured_cpm = total_chars / duration * 60
        if not (CALIBRATED_CPM_MIN <= measured_cpm <= CALIBRATED_CPM_MAX):
            warnings.append(
                "CPM thật %.1f nằm ngoài dải %d–%d — kiểm tra silence/music đầu cuối hoặc tốc độ đọc."
                % (measured_cpm, CALIBRATED_CPM_MIN, CALIBRATED_CPM_MAX)
            )
    else:
        policy = sections_manifest.get("section_policy", {})
        total = float(policy.get("estimated_max_seconds") or (total_chars / FALLBACK_CPM * 60))
        status = "DRAFT_TIMING"
        measured_cpm = None

    # Cửa sổ section: tỉ lệ ký tự × tổng duration.
    windows: dict[str, tuple[float, float]] = {}
    cursor = 0.0
    for sec in section_ids:
        share = (chars_by_section.get(sec, 0) / total_chars) if total_chars else 0.0
        end = cursor + total * share
        windows[sec] = (cursor, end)
        cursor = end

    # Gom event theo section của beat, chia đều trong cửa sổ.
    def section_for_beat(beat_id: Any) -> str | None:
        beat = beats_by_id.get(beat_id)
        if beat is None:
            return None
        return beat.get("script_section")

    per_section_events: dict[str, list[dict]] = {}
    unmatched = 0
    for row in rows:
        sec = section_for_beat(row.get("beat_id"))
        if sec is None or sec not in windows:
            unmatched += 1
            continue
        per_section_events.setdefault(sec, []).append(row)
    if unmatched:
        warnings.append("%d event không map được section (bỏ qua)." % unmatched)

    timed: list[dict] = []
    for sec, events in per_section_events.items():
        start, end = windows[sec]
        span = end - start
        count = len(events)
        for index, row in enumerate(events):
            event_start = start + span * index / count
            event_end = start + span * (index + 1) / count if index + 1 < count else end
            timed.append({**row, "t_start": event_start, "t_end": event_end, "t_sec": sec})
    timed.sort(key=lambda r: (r["t_start"], str(r.get("event_id", ""))))

    for sec in section_ids:
        if not per_section_events.get(sec):
            warnings.append(
                "Section %s không có visual event — giữ ảnh cuối bằng motion/hold (như end card CTA)." % sec
            )

    unique_images = len({row.get("image_id") for row in rows if row.get("image_id")})
    # Cửa sổ giây thật cho bước Dựng video (build_service): cắt audio theo mốc
    # section và sinh prompts-build.py từ đúng cửa sổ này (scale ≈ 1.0 khi ráp).
    meta_sections = [
        {
            "id": sec,
            "file": file_by_section.get(sec, ""),
            "function": functions.get(sec, ""),
            "chars": chars_by_section.get(sec, 0),
            "text": text_by_section.get(sec, ""),
            "start_s": round(start, 3),
            "end_s": round(end, 3),
        }
        for sec in section_ids
        for start, end in [windows[sec]]
    ]
    meta_events = [
        {
            "event_id": row.get("event_id"),
            "beat_id": row.get("beat_id"),
            "image_id": row.get("image_id"),
            "new_image": bool(row.get("new_image")),
            "start_s": round(row["t_start"], 3),
            "end_s": round(row["t_end"], 3),
            "section": row["t_sec"],
        }
        for row in timed
    ]
    meta: dict[str, Any] = {
        "status": status,
        "script_chars": total_chars,
        "calibrated_cpm_min": CALIBRATED_CPM_MIN,
        "calibrated_cpm_max": CALIBRATED_CPM_MAX,
        "section_count": len(section_ids),
        "event_count": len(timed),
        "unique_images": unique_images,
        "sections": meta_sections,
        "events": meta_events,
        "warnings": warnings,
    }
    if status == "FINAL_TIMING":
        meta.update(
            {
                "audio_file": audio_file,
                "duration_seconds": round(total, 3),
                "measured_cpm": round(measured_cpm, 1),
            }
        )
    else:
        meta["estimated_seconds"] = round(total)

    lines: list[str] = []
    if status == "FINAL_TIMING":
        lines.append("# BẢNG TIMELINE — FINAL_TIMING (audio thật)")
        lines.append("")
        lines.append("| Hạng mục | Giá trị | Ghi chú |")
        lines.append("|---|---|---|")
        lines.append("| Audio | %s · %s (%ss) | đo bằng ffprobe |" % (audio_file, _fmt_time(total), round(total, 3)))
        lines.append("| Script | %d ký tự (non-whitespace) | sections.json |" % total_chars)
        lines.append("| CPM thật | %.1f | dải chuẩn %d–%d |" % (measured_cpm, CALIBRATED_CPM_MIN, CALIBRATED_CPM_MAX))
        lines.append("| Ảnh unique | %d | %d events → %.2f event/ảnh |" % (unique_images, len(timed), len(timed) / unique_images if unique_images else 0))
    else:
        lines.append("# BẢNG TIMELINE — DRAFT_TIMING (chưa có audio)")
        lines.append("")
        lines.append("| Hạng mục | Giá trị | Ghi chú |")
        lines.append("|---|---|---|")
        lines.append("| Tổng dự kiến | ~%ss (~%s) | theo CPM %d của section_policy |" % (round(total), _fmt_time(total), FALLBACK_CPM))
        lines.append("| Script | %d ký tự (non-whitespace) | sections.json |" % total_chars)
        lines.append("| CPM tham chiếu | %d–%d | MiniMax profile |" % (CALIBRATED_CPM_MIN, CALIBRATED_CPM_MAX))
        lines.append("| Ảnh unique | %d | %d events → %.2f event/ảnh |" % (unique_images, len(timed), len(timed) / unique_images if unique_images else 0))
        lines.append("")
        lines.append("> Bỏ file audio ghép vào `audio/` rồi chạy lại pipeline (resume) → timeline tự chuyển FINAL_TIMING.")

    lines.extend(["", "## Cửa sổ section (tỉ lệ ký tự)", ""])
    lines.append("| Section | File | Chức năng | Ký tự | Cửa sổ | Thời lượng |")
    lines.append("|---|---|---|---|---|---|")
    for sec in section_ids:
        start, end = windows[sec]
        lines.append(
            "| %s | %s | %s | %d | %s–%s | %.1fs |"
            % (sec, file_by_section.get(sec, ""), functions.get(sec, ""), chars_by_section.get(sec, 0), _fmt_time(start), _fmt_time(end), end - start)
        )

    lines.extend(["", "## Timeline events (%d)" % len(timed), ""])
    lines.append("| ID | Time | Beat | Ảnh | Motion / visual information |")
    lines.append("|---|---|---|---|---|")
    for row in timed:
        reuse = "" if row.get("new_image") else "♻️ "
        lines.append(
            "| %s | %s–%s | %s | %s%s | %s |"
            % (
                row.get("event_id", ""),
                _fmt_time(row["t_start"]),
                _fmt_time(row["t_end"]),
                row.get("beat_id", ""),
                reuse,
                row.get("image_id", ""),
                (row.get("motion") or "") + " — " + (row.get("visual_information") or "") if row.get("visual_information") else (row.get("motion") or ""),
            )
        )

    if warnings:
        lines.extend(["", "## Cảnh báo", ""])
        for warning in warnings:
            lines.append("- %s" % warning)

    lines.append("")
    return "\n".join(lines), meta
