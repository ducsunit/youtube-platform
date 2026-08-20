"""competitor_context.py — Baked competitor analysis for PsychToons JP.

Refresh manually every 5-10 videos. Update `_LAST_UPDATED` when you do.
"""
from __future__ import annotations

# Last updated: 2026-08-18 (vidIQ channel data, 4 transcripts, metadata,
# thumbnail scoring, and 2 visual walkthroughs).
_LAST_UPDATED = "2026-08-18"

PSYCHTOONS_PATTERNS = """## Competitor: PsychToons JP (đối thủ chính)

- Quy mô: khoảng 42.6K subs, 103 video, tăng khoảng 16.9K subs và 1.07M views trong cửa sổ 30 ngày; nhịp đăng gần như hằng ngày.
- Hiệu suất không đều: video viral đạt 2.36M views ở 10:27; Discipline đạt khoảng 596K ở 14:45; các video gần đây khác chỉ 7–10K. Topic và packaging quan trọng hơn việc kéo dài video.
- Title pattern: `Psychology of People Who...`, `Why Smart People...`, `10 Signs...`, identity label + contrast/superlative. Không sao chép câu chữ; chỉ học promise rõ và tension mạnh.
- Hook: bắt đầu bằng hành vi người xem nhận ra trong 8–20 giây, phá hiểu lầm đạo đức, rồi chuyển nhanh sang một cơ chế tâm lý.
- Script: thường có một mechanism chính, 1–3 research anchors, ví dụ ngắn để nhận diện, sau đó là paradox/cost và reframe. Format list chỉ dùng khi mỗi sign vẫn nối được với cùng một model tâm lý.
- Visual: 2D flat cartoon, nhân vật lặp lại nhưng có cả nhân vật phụ, researcher, biểu đồ, ẩn dụ và split contrast. Nhịp visual thường 2–4 giây; không nên biến thành một nhân vật giống hệt trong mọi beat.
- Thumbnail: focal point và headline ngắn, nhưng bố cục thay đổi giữa centered, contrast và metaphor. Thumbnail heuristic scores mẫu chỉ 20–66/100, nên không copy layout một cách cứng nhắc.
- Description: hook/tóm tắt ngắn → research references → CTA → hashtags/disclaimer. Đây là khoảng trống lớn trong publish flow hiện tại.
- Ending: self-understanding, practical shift vừa đủ, CTA ngắn; không kết thúc bằng generic motivation.
- Format: phần lớn video dài 13–19 phút, nhưng video viral 10:27 xác nhận mục tiêu 9–11 phút là một giả thuyết hợp lệ cho kênh Nhật.
"""


# Editorial DNA abstracted from recent public PsychToons transcripts and visual walkthroughs (2026-08-18).
# This captures structure/rhythm only; it does not copy wording, examples, or proprietary text.
PSYCHTOONS_WRITING_DNA = """
- Cold open: begin inside the viewer's recognizable behavior; no long setup.
- In the first beat, name the common misread and flip it into a surprising psychological interpretation.
- Use one dominant mechanism; supporting research is a proof point, not a research lecture.
- Alternate concrete inner experience with explanation so the script feels like discovery, not a lesson.
- Keep momentum with a new implication, contrast, metaphor, or research consequence every 30-60 seconds instead of adding more sections.
- Reframes are occasional and earned; never repeat a signature line just to satisfy a quota.
- End on a quiet identity/self-understanding realization, then a short CTA.
- For Japan, localize the emotional wording and examples; do not translate international identity labels literally.
"""


def competitor_inject_text() -> str:
    """Return the competitor context block for injection into prompts."""
    return PSYCHTOONS_PATTERNS + "\n" + PSYCHTOONS_WRITING_DNA
