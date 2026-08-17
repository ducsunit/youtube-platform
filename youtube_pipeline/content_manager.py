"""content_manager.py — Runtime readers and writers for content/ files.

All functions fail silently: if a content file is unreadable the pipeline
continues with empty strings / empty lists, exactly like _load_skill().
Write-backs (mark_topic_in_progress / mark_topic_published) follow the same
rule — a broken write never kills the pipeline.
"""
from __future__ import annotations

import re
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

_CONTENT_DIR = Path(__file__).parent.parent / "content"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read(filename: str) -> str:
    try:
        return (_CONTENT_DIR / filename).read_text(encoding="utf-8")
    except OSError:
        return ""


def _write(filename: str, content: str) -> None:
    try:
        (_CONTENT_DIR / filename).write_text(content, encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# video-queue.md
# ---------------------------------------------------------------------------

def load_queued_topics() -> list[dict]:
    """Parse video-queue.md and return topics with status=queued."""
    text = _read("video-queue.md")
    if not text:
        return []

    topics: list[dict] = []
    # Match "### N. Title" blocks
    blocks = re.split(r"\n### \d+\.", text)
    for block in blocks[1:]:  # skip header before first ###
        lines = block.strip().splitlines()
        title_vn = lines[0].strip() if lines else ""
        entry: dict = {"title_vn": title_vn}
        for line in lines:
            line = line.strip().lstrip("- ")
            for key in ("working_title_jp", "mechanism", "backup_mechanism",
                        "cultural_frame", "central_emotion", "notes"):
                if line.startswith(f"**{key}:**"):
                    entry[key] = re.sub(r"\s*\(.*?\)", "", line.split(":**", 1)[1]).strip()
                    break
        # status is in the overview table, default queued
        entry.setdefault("mechanism", "")
        entry.setdefault("cultural_frame", "")
        entry["status"] = "queued"
        topics.append(entry)
    return topics


def recently_used_mechanisms(n: int = 3) -> list[str]:
    """Return the last n mechanisms from the diary table in video-queue.md."""
    text = _read("video-queue.md")
    if not text:
        return []
    # Find "## Nhật ký dùng" section
    diary_match = re.search(r"## Nhật ký dùng.*?\n((?:\|[^\n]+\n)+)", text, re.DOTALL)
    if not diary_match:
        return []
    rows = diary_match.group(1).strip().splitlines()
    mechanisms: list[str] = []
    for row in rows:
        cols = [c.strip() for c in row.strip("|").split("|")]
        if len(cols) >= 3 and cols[0] != "Ngày đăng" and "---" not in cols[0]:
            mech = cols[2].strip()
            if mech and mech != "—":
                mechanisms.append(mech)
    return mechanisms[-n:]


def queue_inject_text() -> str:
    """Return a formatted block for injection into topic_selection prompt."""
    topics = load_queued_topics()
    if not topics:
        return ""

    lines = ["## Hàng đợi video đã nghiên cứu (ưu tiên chọn từ đây)\n"]
    for i, t in enumerate(topics, 1):
        lines.append(f"{i}. {t['title_vn']}")
        if t.get("working_title_jp"):
            lines.append(f"   - title_jp: {t['working_title_jp']}")
        if t.get("mechanism"):
            lines.append(f"   - mechanism: {t['mechanism']}")
        if t.get("backup_mechanism"):
            lines.append(f"   - backup: {t['backup_mechanism']}")
        if t.get("cultural_frame"):
            lines.append(f"   - cultural_frame: {t['cultural_frame']}")

    used = recently_used_mechanisms()
    if used:
        lines.append(f"\nCơ chế đã dùng gần nhất ({len(used)} video): {', '.join(used)}")
    else:
        lines.append("\nCơ chế đã dùng gần nhất: (chưa có dữ liệu)")

    paused = _paused_mechanisms()
    if paused:
        lines.append(f"Cơ chế ⛔ tạm ngừng: {', '.join(paused)}")

    lines.append(
        "\nNếu topic được chọn không nằm trong hàng đợi, ghi rõ lý do trong selection_rationale."
    )
    return "\n".join(lines)


def _paused_mechanisms() -> list[str]:
    text = _read("mechanisms.md")
    return re.findall(r"## \d+\.\s*(.*?)\s*—\s*⛔", text)


# ---------------------------------------------------------------------------
# video-queue.md — structured readers (cho API/UI)
# ---------------------------------------------------------------------------

def _queue_details() -> dict[int, dict]:
    """Detail blocks (### N.) → {queue_no: {title_vn, title_jp, mechanism, ...}}."""
    text = _read("video-queue.md")
    result: dict[int, dict] = {}
    if not text:
        return result
    parts = re.split(r"\n### (\d+)\.", text)
    for i in range(1, len(parts) - 1, 2):
        body = parts[i + 1]
        title_vn = body.strip().splitlines()[0].strip() if body.strip() else ""
        entry: dict = {"title_vn": title_vn}
        for line in body.splitlines():
            line = line.strip().lstrip("- ")
            for key in ("working_title_jp", "mechanism", "backup_mechanism",
                        "cultural_frame", "central_emotion", "notes"):
                if line.startswith(f"**{key}:**"):
                    entry[key] = line.split(":**", 1)[1].strip()
                    break
        result[int(parts[i])] = entry
    return result


def queue_overview() -> list[dict]:
    """Parse bảng tổng quan + detail → list entry với status THẬT (UI/API đọc).

    Status lấy từ cột cuối bảng tổng quan (không hardcode "queued" như
    load_queued_topics — hàm kia chỉ phục vụ prompt injection).
    """
    text = _read("video-queue.md")
    if not text:
        return []
    overview_part = text.split("## Chi tiết", 1)[0]
    rows: list[dict] = []
    for line in overview_part.splitlines():
        cols = [c.strip() for c in line.strip("|").split("|")]
        if len(cols) < 2 or not cols[0].isdigit():
            continue
        rows.append({
            "queue_no": int(cols[0]),
            "hien_tuong": cols[1] if len(cols) > 1 else "",
            "primary_core": cols[2] if len(cols) > 2 else "",
            "mechanism": cols[3] if len(cols) > 3 else "",
            "backup_mechanism": cols[4] if len(cols) > 4 else "",
            "cultural_frame": cols[5] if len(cols) > 5 else "",
            "status": cols[6] if len(cols) > 6 else "queued",
        })
    details = _queue_details()
    for row in rows:
        detail = details.get(row["queue_no"]) or {}
        row.update({k: v for k, v in detail.items() if k not in row or not row[k]})
    return rows


def diary_entries() -> list[dict]:
    """Parse Nhật ký dùng → list {ngay, video, mechanism, frame, video_id}.

    Bỏ qua header, separator và dòng placeholder — chỉ trả entry thật.
    """
    text = _read("video-queue.md")
    if not text:
        return []
    diary_match = re.search(r"## Nhật ký dùng.*?\n((?:\|[^\n]+\n)+)", text, re.DOTALL)
    if not diary_match:
        return []
    rows: list[dict] = []
    for row in diary_match.group(1).strip().splitlines():
        cols = [c.strip() for c in row.strip("|").split("|")]
        if len(cols) < 2 or "---" in cols[0] or cols[0] == "Ngày đăng":
            continue
        if "(chưa có" in row or all(c in ("", "—") for c in cols):
            continue  # placeholder row
        rows.append({
            "ngay": cols[0],
            "video": cols[1] if len(cols) > 1 else "",
            "mechanism": cols[2] if len(cols) > 2 else "",
            "frame": cols[3] if len(cols) > 3 else "",
            "video_id": cols[4] if len(cols) > 4 else "",
        })
    return rows


def find_queue_entry(topic_name: str) -> dict | None:
    """Fuzzy-match topic → entry tổng quan kèm status thật, hoặc None."""
    matched = _find_queue_topic(topic_name)
    if matched is None:
        return None
    queue_no, _title = matched
    for row in queue_overview():
        if row["queue_no"] == queue_no:
            return row
    return None


# ---------------------------------------------------------------------------
# video-queue.md — write-back (checklist A3 + E1/E2)
# ---------------------------------------------------------------------------

# Diary canonical format — mechanism giữ nguyên ở cột 3 (col index 2) để
# recently_used_mechanisms() tiếp tục đọc đúng.
_DIARY_COLUMNS = "| Ngày đăng | Video (queue #) | Cơ chế đã dùng | Frame đã dùng | Video ID |"
_DIARY_SEPARATOR = "|---|---|---|---|---|"


def _normalize_title(s: str) -> str:
    return re.sub(r"[\W_]+", "", s.lower(), flags=re.UNICODE)


def _queue_candidates() -> list[tuple[int, dict[str, str]]]:
    """Collect (queue_no, {title_vn, title_jp, hien_tuong}) from video-queue.md."""
    text = _read("video-queue.md")
    if not text:
        return []

    overview_part = text.split("## Chi tiết", 1)[0]
    hien_tuong: dict[int, str] = {}
    for m in re.finditer(r"^\|\s*(\d+)\s*\|([^|]+)", overview_part, re.MULTILINE):
        hien_tuong[int(m.group(1))] = m.group(2).strip()

    result: list[tuple[int, dict[str, str]]] = []
    parts = re.split(r"\n### (\d+)\.", text)
    for i in range(1, len(parts) - 1, 2):
        body = parts[i + 1]
        title_vn = body.strip().splitlines()[0].strip() if body.strip() else ""
        title_jp = ""
        for line in body.splitlines():
            line = line.strip().lstrip("- ")
            if line.startswith("**working_title_jp:**"):
                title_jp = line.split(":**", 1)[1].strip()
                break
        result.append((int(parts[i]), {
            "title_vn": title_vn,
            "title_jp": title_jp,
            "hien_tuong": hien_tuong.get(int(parts[i]), ""),
        }))
    return result


def _find_queue_topic(topic_name: str) -> tuple[int, str] | None:
    """Fuzzy-match topic_name against queue entries.

    Topic do LLM chọn là văn bản tự do — so khớp cả title_vn, working_title_jp
    và cột "Hiện tượng" của bảng tổng quan. Trả (queue_no, title_vn), hoặc None
    khi không khớp đủ gần (topic ngoài queue → không đụng vào file).
    """
    if not topic_name:
        return None
    needle = _normalize_title(topic_name)
    if not needle:
        return None

    best: tuple[float, int, str] = (0.0, 0, "")
    for queue_no, fields in _queue_candidates():
        for key in ("title_vn", "title_jp", "hien_tuong"):
            candidate = _normalize_title(fields.get(key, ""))
            if not candidate:
                continue
            ratio = SequenceMatcher(None, needle, candidate).ratio()
            if needle in candidate or candidate in needle:
                ratio = max(ratio, 0.8)
            if ratio > best[0]:
                best = (ratio, queue_no, fields["title_vn"] or fields["hien_tuong"])
    if best[0] < 0.55:
        return None
    return best[1], best[2]


def _set_queue_status(text: str, queue_no: int, new_status: str, allowed_from: frozenset[str]) -> tuple[str, bool]:
    """Flip the Status cell (last column) of overview row `queue_no`."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        cols = [c.strip() for c in line.strip("|").split("|")]
        if len(cols) >= 2 and cols[0] == str(queue_no):
            parts = line.split("|")
            if len(parts) >= 3 and parts[-2].strip() in allowed_from:
                parts[-2] = f" {new_status} "
                lines[i] = "|".join(parts)
                return "\n".join(lines) + "\n", True
            return text, False
    return text, False


def _rebuild_diary(text: str, new_row: str | None) -> str:
    """Rebuild the Nhật ký dùng table: keep real rows, drop placeholders, append new_row.

    Giữ nguyên header hiện có (kể cả ghi chú trong ngoặc) và mọi text nằm sau
    bảng; chỉ viết lại phần bảng theo format chuẩn 5 cột.
    """
    header_m = re.search(r"^## Nhật ký dùng[^\n]*$", text, re.MULTILINE)
    if header_m:
        prefix = text[: header_m.start()].rstrip() + "\n\n"
        header_line = header_m.group(0)
        tail = text[header_m.end():]
    else:
        prefix = (text.rstrip() + "\n\n") if text.strip() else ""
        header_line = "## Nhật ký dùng"
        tail = ""

    existing_rows: list[str] = []
    suffix = ""
    table = re.search(r"\n((?:\|[^\n]+\n)+)", tail)
    if table:
        suffix = tail[table.end():]
        for row in table.group(1).strip().splitlines():
            cols = [c.strip() for c in row.strip("|").split("|")]
            if len(cols) < 2 or "---" in cols[0] or cols[0] == "Ngày đăng":
                continue
            if "(chưa có" in row or all(c in ("", "—") for c in cols):
                continue  # placeholder row
            existing_rows.append(row)
    if new_row:
        existing_rows.append(new_row)

    block = header_line + "\n\n" + _DIARY_COLUMNS + "\n" + _DIARY_SEPARATOR + "\n"
    if existing_rows:
        block += "\n".join(existing_rows) + "\n"
    return prefix + block + suffix


def mark_topic_in_progress(topic_name: str) -> int | None:
    """A3 — sau khi pipeline chọn topic: status queued → in_progress.

    Trả queue number nếu cập nhật được, None khi topic không khớp queue hoặc
    status đã chuyển (idempotent). Fail silent như mọi hàm khác.
    """
    matched = _find_queue_topic(topic_name)
    if matched is None:
        return None
    queue_no, _ = matched
    text = _read("video-queue.md")
    if not text:
        return None
    new_text, updated = _set_queue_status(text, queue_no, "in_progress", frozenset(("queued",)))
    if not updated:
        return None
    _write("video-queue.md", new_text)
    return queue_no


def mark_topic_published(topic_name: str, video_id: str = "", mechanism: str = "", frame: str = "") -> int | None:
    """E1/E2 — ghi Nhật ký dùng + status → published sau khi pack sẵn sàng đăng.

    Append dòng `Ngày | #N — title | mechanism | frame | video_id` vào bảng
    Nhật ký dùng (bỏ dòng placeholder nếu đây là lần đầu), rồi chuyển status
    queued/in_progress → published. Trả queue number, None khi không khớp queue.
    """
    matched = _find_queue_topic(topic_name)
    if matched is None:
        return None
    queue_no, title = matched
    text = _read("video-queue.md")
    if not text:
        return None

    new_text, _ = _set_queue_status(text, queue_no, "published", frozenset(("queued", "in_progress")))
    row = "| %s | #%d — %s | %s | %s | %s |" % (
        date.today().isoformat(),
        queue_no,
        title,
        mechanism.strip() or "—",
        frame.strip() or "—",
        video_id.strip() or "—",
    )
    _write("video-queue.md", _rebuild_diary(new_text, row))
    return queue_no


def set_diary_video_id(topic_name: str, video_id: str) -> int | None:
    """Điền video_id vào dòng nhật ký MỚI NHẤT của queue #N (sau khi đăng thật).

    Pipeline không upload nên ghi "—" ở bước pack; người dùng đăng xong gọi
    hàm này (qua UI) để điền ID thật. Trả queue_no nếu cập nhật được, None khi
    không khớp queue / chưa có nhật ký / chưa có dòng nào của topic đó.
    """
    matched = _find_queue_topic(topic_name)
    if matched is None:
        return None
    queue_no, _title = matched
    video_id = video_id.strip()
    if not video_id:
        return None
    text = _read("video-queue.md")
    if not text:
        return None

    header_m = re.search(r"^## Nhật ký dùng[^\n]*$", text, re.MULTILINE)
    if not header_m:
        return None
    tail = text[header_m.end():]
    table = re.search(r"\n((?:\|[^\n]+\n)+)", tail)
    if not table:
        return None

    rows = table.group(1).strip().splitlines()
    target_idx = None
    for idx, row in enumerate(rows):
        cols = [c.strip() for c in row.strip("|").split("|")]
        if len(cols) < 2 or "---" in cols[0] or cols[0] == "Ngày đăng":
            continue
        if "(chưa có" in row or all(c in ("", "—") for c in cols):
            continue
        if re.search(rf"#\s*{queue_no}\b", cols[1]):
            target_idx = idx  # lấy dòng cuối cùng khớp
    if target_idx is None:
        return None

    parts = rows[target_idx].split("|")
    if len(parts) < 3:
        return None
    parts[-2] = f" {video_id} "
    rows[target_idx] = "|".join(parts)

    table_start = header_m.end() + table.start()
    table_end = header_m.end() + table.end()
    new_text = text[:table_start] + "\n" + "\n".join(rows) + "\n" + text[table_end:]
    _write("video-queue.md", new_text)
    return queue_no


# ---------------------------------------------------------------------------
# mechanisms.md
# ---------------------------------------------------------------------------

def load_mechanisms() -> dict[str, dict]:
    """Return dict keyed by mechanism name (Japanese) with citation data."""
    text = _read("mechanisms.md")
    if not text:
        return {}

    result: dict[str, dict] = {}
    # Each mechanism block starts with "## N. Name"
    blocks = re.split(r"\n## \d+\.", text)
    for block in blocks[1:]:
        lines = block.strip().splitlines()
        if not lines:
            continue
        header = lines[0].strip()
        paused = "⛔" in header
        # Extract Japanese name (before space or parenthesis)
        name_match = re.match(r"([^\s(（⛔]+)", header)
        if not name_match:
            continue
        jp_name = name_match.group(1).strip()

        entry: dict = {"paused": paused, "raw_name": header}
        for line in lines:
            line = line.strip().lstrip("- ")
            if line.startswith("**Tác giả + năm:**"):
                entry["author_year"] = line.split(":**", 1)[1].strip()
            elif line.startswith("**Nguồn:**"):
                entry["source"] = line.split(":**", 1)[1].strip()
            elif line.startswith("**Góc hook"):
                entry["hook"] = line.split(":**", 1)[1].strip()
            elif line.startswith("**Ý tưởng lõi:**"):
                entry["core_idea"] = line.split(":**", 1)[1].strip()
        result[jp_name] = entry
    return result


def mechanism_citation_text(mechanism_name: str) -> str:
    """Return a ready-to-inject citation block for a given mechanism name.

    Matching is fuzzy: looks for the mechanism name as a substring of the key.
    Returns empty string if not found or mechanism is paused.
    """
    mechs = load_mechanisms()
    matched = None
    for key, data in mechs.items():
        if mechanism_name in key or key in mechanism_name:
            matched = (key, data)
            break
    if not matched:
        return ""
    jp_name, data = matched
    if data.get("paused"):
        return ""

    parts = [f"## Nghiên cứu có sẵn cho cơ chế: {jp_name}"]
    if data.get("author_year"):
        parts.append(f"- Tác giả + năm: {data['author_year']}")
    if data.get("source"):
        parts.append(f"- Nguồn: {data['source']}")
    if data.get("hook"):
        parts.append(f"- Góc hook: {data['hook']}")
    if data.get("core_idea"):
        parts.append(f"- Ý tưởng lõi: {data['core_idea']}")
    parts.append("Dùng trực tiếp — không cần tìm lại. Sách (ví dụ 『嫌われる勇気』) KHÔNG tính vào research_min_count.")
    return "\n".join(parts)


def mechanism_diversity_ok(mechanism_name: str, window: int = 3) -> bool:
    """Return True if mechanism is safe to use (not in last `window` videos)."""
    mechs = load_mechanisms()
    # Check paused flag
    for key, data in mechs.items():
        if mechanism_name in key or key in mechanism_name:
            if data.get("paused"):
                return False
    # Check diary
    recent = recently_used_mechanisms(window)
    for used in recent:
        if mechanism_name in used or used in mechanism_name:
            return False
    return True


# ---------------------------------------------------------------------------
# cultural-frames-jp.md
# ---------------------------------------------------------------------------

def load_cultural_frames() -> dict[str, dict]:
    """Return dict keyed by frame name (Japanese) with usage data."""
    text = _read("cultural-frames-jp.md")
    if not text:
        return {}

    result: dict[str, dict] = {}
    blocks = re.split(r"\n## \d+\.", text)
    for block in blocks[1:]:
        lines = block.strip().splitlines()
        if not lines:
            continue
        header = lines[0].strip()
        name_match = re.match(r"([^\s(（]+)", header)
        if not name_match:
            continue
        jp_name = name_match.group(1).strip()

        entry: dict = {"raw_name": header}
        for line in lines:
            line = line.strip().lstrip("- ")
            if line.startswith("**Khái niệm:**"):
                entry["concept"] = line.split(":**", 1)[1].strip()
            elif line.startswith("**Dùng ở bước nào"):
                entry["usage_step"] = line.split(":**", 1)[1].strip()
            elif line.startswith("**Pair tốt với cơ chế:**"):
                entry["pair_mechanisms"] = line.split(":**", 1)[1].strip()
        result[jp_name] = entry
    return result


def cultural_frame_text(frame_name: str) -> str:
    """Return a ready-to-inject frame block for injection into writing prompt."""
    frames = load_cultural_frames()
    matched = None
    for key, data in frames.items():
        if frame_name in key or key in frame_name:
            matched = (key, data)
            break
    if not matched:
        return ""
    jp_name, data = matched

    parts = [f"## Cultural frame cho video này: {jp_name}"]
    if data.get("concept"):
        parts.append(f"- Khái niệm: {data['concept']}")
    if data.get("usage_step"):
        parts.append(f"- Dùng ở bước: {data['usage_step']}")
    if data.get("pair_mechanisms"):
        parts.append(f"- Pair với cơ chế: {data['pair_mechanisms']}")
    parts.append(
        "type: cultural_frame — sách gốc KHÔNG tính vào research_min_count, chỉ là khung giải thích. "
        "Quy tắc: một video chỉ dùng tối đa 1 frame chính."
    )
    return "\n".join(parts)
