"""Chia script thành sections theo số section của planning — KHÔNG chia chunk.

Kịch bản 9–11 phút (2.400–4.700 ký tự) gen được trong MỘT lần gọi MiniMax từ
`script/minimax-prompt.txt`; không còn file chunk để gen/ghép từng phần.

Sections chỉ là cơ cấu đánh dấu mốc cho bước Dựng video (cửa sổ giây theo tỉ
lệ ký tự, tên file audio cắt theo section, marks.tsv — web/CLI build_service
tính timeline động từ sections + storyboard). Số section khớp
chính xác số section trong planning.json (S1..SN) nên mọi beat/event đều map
được cửa sổ — không còn tình trạng bỏ sót event ở cuối script (lỗi cũ: 8
section planning nhưng chunker chỉ ra 5 chunk theo kích thước → 18 event rơi).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from math import ceil

from .metrics import non_whitespace_chars


@dataclass
class ScriptSection:
    index: int
    id: str
    text: str

    @property
    def chars(self) -> int:
        return non_whitespace_chars(self.text)

    @property
    def file(self) -> str:
        """Tên quy ước cho audio cắt theo section (sorted glob == thứ tự section)."""
        return "%02d_section-%02d.txt" % (self.index, self.index)


def _split_by_sentences(segment: str) -> list[str]:
    parts = [part for part in re.split(r"(?<=[。！？])", segment) if part]
    if len(parts) < 2:
        raise ValueError("Đoạn script không có ranh giới câu để chia.")
    return parts


def split_script_sections(
    script: str,
    section_count: int,
    cpm_min: int = 380,
    cpm_max: int = 400,
) -> tuple[list[ScriptSection], dict[str, int | float]]:
    """Chia script thành đúng `section_count` section (khớp planning.json).

    Trả về (sections, policy). Mọi section non-empty; ghép lại đúng script gốc.
    """
    if not script:
        raise ValueError("Script không được rỗng.")
    if section_count < 1:
        raise ValueError("section_count phải >= 1.")
    if cpm_min > cpm_max:
        raise ValueError("cpm_min phải <= cpm_max.")
    total = non_whitespace_chars(script)
    target = max(1, ceil(total / section_count))

    # Đoạn dài hơn hẳn target thì tách theo câu để có thể chia đủ section_count.
    units: list[str] = []
    for segment in re.split(r"(?<=\n\n)", script):
        if not segment:
            continue
        if non_whitespace_chars(segment) <= max(target * 1.5, 550):
            units.append(segment)
        else:
            units.extend(_split_by_sentences(segment))

    # Gom gần đúng theo target ký tự; unit chỉ có khoảng trắng luôn dính vào nhóm hiện tại.
    groups: list[str] = []
    current = ""
    for unit in units:
        if non_whitespace_chars(unit) == 0:
            current += unit
        elif current and non_whitespace_chars(current) > 0 and non_whitespace_chars(current + unit) > target:
            groups.append(current)
            current = unit
        else:
            current += unit
    if current:
        groups.append(current)

    # Về đúng section_count: thừa → gộp cặp liền nhau nhỏ nhất; thiếu → tách
    # section lớn nhất tại ranh giới câu (script 2.400+ ký tự luôn làm được).
    while len(groups) > section_count:
        merge_index = min(
            range(len(groups) - 1),
            key=lambda i: non_whitespace_chars(groups[i] + groups[i + 1]),
        )
        groups[merge_index] = groups[merge_index] + groups[merge_index + 1]
        del groups[merge_index + 1]
    while len(groups) < section_count:
        largest = max(range(len(groups)), key=lambda i: non_whitespace_chars(groups[i]))
        parts = _split_by_sentences(groups[largest])
        half = ceil(non_whitespace_chars(groups[largest]) / 2)
        first = ""
        for sentence in parts:
            first += sentence
            if non_whitespace_chars(first) >= half:
                break
        groups[largest:largest + 1] = [first, groups[largest][len(first):]]

    sections = [
        ScriptSection(index=index, id="S%d" % index, text=text)
        for index, text in enumerate(groups, start=1)
    ]
    validate_sections(script, sections, section_count)
    policy = {
        "script_chars": total,
        "section_count": section_count,
        "cpm_min": cpm_min,
        "cpm_max": cpm_max,
        "estimated_min_seconds": round(total / cpm_max * 60),
        "estimated_max_seconds": round(total / cpm_min * 60),
        "target_chars_per_section": target,
    }
    return sections, policy


def validate_sections(script: str, sections: list[ScriptSection], section_count: int) -> None:
    if len(sections) != section_count:
        raise ValueError("Số section %d khác yêu cầu %d." % (len(sections), section_count))
    if not all(section.text.strip() for section in sections):
        raise ValueError("Có section rỗng.")
    if "".join(section.text for section in sections) != script:
        raise ValueError("Ghép section không khôi phục đúng script gốc.")


# --- MiniMax pause tags (rule v9 — bộ lọc review kênh こころ包み) --------------
# Cú pháp <#x#> MiniMax T2A hỗ trợ; x là giây nghỉ, tối đa 2 chữ số thập phân.
# Quy tắc v7: không tag ở đầu/cuối văn bản, không 2 tag liền không có chữ giữa,
# ngắt paragraph để MiniMax tự xử lý. Pipeline chèn deterministic (không phụ
# thuộc model) nên strip(tags) == script luôn đúng.
PAUSE_BETWEEN_SECTIONS = 1.5  # giữa 2 phân đoạn lớn (ranh giới section)
PAUSE_BEFORE_OUTRO = 1.0      # trước section cuối (outro/CTA)
PAUSE_PARAGRAPH_BREAK = 0.6   # ngắt paragraph trong section — nghỉ lấy hơi

_TAG_PATTERN = re.compile(r"<#\d{1,2}(?:\.\d{1,2})?#>")


def strip_minimax_tags(text: str) -> str:
    """Bỏ mọi tag <#x#> — dùng cho gate 'minimax-prompt == script'."""
    return _TAG_PATTERN.sub("", text)


def normalize_text(text: str) -> str:
    """Chuẩn hoá whitespace để so sánh nội dung: collapse mọi run → 1 space, cắt 2 đầu.

    Model hay lệch \n ↔ space / dư space thừa — đó không phải lệch nội dung
    thật. Gate v7 dùng hàm này để chỉ chặn khi script THỰC SỰ khác nhau.
    """
    return " ".join(text.split())


# Fraction của script (theo ký tự) cho position ký hiệu S1..S8 — khớp nhịp
# section thực tế của planning 6-8 sections (intro ngắn, ending dài hơn).
_SECTION_FRACTIONS = {1: 0.06, 2: 0.20, 3: 0.34, 4: 0.48, 5: 0.62, 6: 0.76, 7: 0.90, 8: 0.95}
_REFRAME_POS_RE = re.compile(r"ではなく|じゃなくて?")
_SENTENCE_END_RE = re.compile(r"[。！？]")


def _resolve_symbolic_position(
    script: str,
    cursor: int,
    position: str | None,
    index: int,
    reframe_landings: list,
) -> int | None:
    """Resolve position ký hiệu của Gemini (vd "S1_recognition", "S2_reframe_landing1").

    Gemini đôi khi trả position thay vì anchor verbatim; thay vì bỏ tag hết
    (fallback deterministic), pipeline tự map:
    - "S<n>" → tỉ lệ ký tự theo _SECTION_FRACTIONS;
    - "landingN" → sau reframe "XではなくY" thứ N trong script;
    - "ending"/"outro" → ~90% script.
    Tag đặt SAU ranh giới câu gần nhất tại/ sau max(cursor, target). Trả None khi
    không còn ranh giới câu an toàn (tag ở cuối văn bản vi phạm rule v7) → bỏ tag.
    """
    if not isinstance(position, str) or not position.strip():
        raise ValueError("Mục %d thiếu anchor lẫn position." % index)
    text = position.strip().lower()
    target: int | None = None
    section_match = re.match(r"s(\d+)", text)
    if section_match:
        fraction = _SECTION_FRACTIONS.get(int(section_match.group(1)))
        if fraction is None:
            raise ValueError("Mục %d position S%d không được hỗ trợ (S1–S8)." % (index, int(section_match.group(1))))
        target = int(len(script) * fraction)
    landing_match = re.search(r"landing(\d+)", text)
    if landing_match:
        number = int(landing_match.group(1))
        if 1 <= number <= len(reframe_landings):
            target = reframe_landings[number - 1].end()
        # landing ngoài số khớp thực tế → giữ target theo section (nếu có)
    if target is None and ("ending" in text or "outro" in text):
        target = int(len(script) * 0.90)
    if target is None:
        raise ValueError(
            "Mục %d position %r không parse được — cần anchor verbatim hoặc S<n>/landingN/ending." % (index, position)
        )
    start = max(cursor, min(target, len(script)))
    match = _SENTENCE_END_RE.search(script[start:])
    if match is None:
        return None
    # match.end() >= 1 nên insert_at > cursor luôn — không bao giờ sinh 2 tag
    # liền kề (rule v7) từ resolve symbolic.
    return start + match.end()


def build_tts_ready(script: str, anchors: list[dict]) -> str:
    """Chèn tag <#x#> sau từng anchor do Gemini trả (deterministic).

    Ưu tiên anchor verbatim (đoạn text khớp 100% trong script); nếu Gemini chỉ
    trả position ký hiệu (S<n>/landingN/ending), resolve deterministic theo
    _resolve_symbolic_position. Pipeline tự chèn tag bằng code →
    strip_minimax_tags(kết quả) == script bảo đảm đúng, không thể drift như bản
    copy tts_ready mà model tự viết lại.
    """
    pieces = []
    cursor = 0
    reframe_landings = list(_REFRAME_POS_RE.finditer(script))
    for index, item in enumerate(anchors, start=1):
        tag = item.get("tag")
        if not isinstance(tag, str) or not _TAG_PATTERN.fullmatch(tag):
            raise ValueError("Mục %d tag không hợp lệ: %r" % (index, tag))
        anchor = item.get("anchor")
        if isinstance(anchor, str) and anchor:
            position = script.find(anchor, cursor)
            if position < 0:
                raise ValueError("Anchor %d không có trong script: %r" % (index, anchor[:40]))
            insert_at = position + len(anchor)
        else:
            insert_at = _resolve_symbolic_position(
                script, cursor, item.get("position"), index, reframe_landings
            )
            if insert_at is None:
                continue  # không còn ranh giới câu an toàn — bỏ tag (soft pause)
        pieces.append(script[cursor:insert_at])
        pieces.append(tag)
        cursor = insert_at
    pieces.append(script[cursor:])
    result = "".join(pieces)
    if strip_minimax_tags(result) != script:
        raise ValueError("Chèn anchor tag làm lệch script gốc.")
    return result


def insert_pause_tags(script: str, sections: list[ScriptSection]) -> str:
    """Chèn tag <#x#> vào script sạch theo mốc section (deterministic).

    Bảo đảm strip_minimax_tags(kết quả) == script — nội dung không đổi, chỉ
    thêm pause cue đúng quy tắc v7.
    """
    pieces = []
    for index, section in enumerate(sections):
        text = section.text
        if text.endswith("\n\n"):
            body, tail = text[:-2], "\n\n"
        else:
            body, tail = text, ""
        # Ngắt paragraph trong section: tag sau dấu ngắt câu, trước xuống dòng.
        body = body.replace("\n\n", "<#%.1f#>\n\n" % PAUSE_PARAGRAPH_BREAK)
        piece = body + tail
        if index > 0:
            tag = PAUSE_BEFORE_OUTRO if index == len(sections) - 1 else PAUSE_BETWEEN_SECTIONS
            piece = "<#%.1f#>" % tag + piece
        pieces.append(piece)
    result = "".join(pieces)
    if strip_minimax_tags(result) != script:
        raise ValueError("Chèn pause tag làm lệch script gốc.")
    return result
