"""competitor_context.py — Baked competitor analysis for PsychToons JP.

Refresh manually every 5-10 videos. Update `_LAST_UPDATED` when you do.
"""
from __future__ import annotations

# Last updated: 2026-08-17 (nghiên cứu vidIQ: channel stats + 4 transcript —
# N95Tb2sDWVs 2.36M/10:27, CkP_8bkjf1E 548K/14:45, 7cEPncxxa_c 34K/15:28, POqCOvbJFbE 49K/11:42)
_LAST_UPDATED = "2026-08-17"

PSYCHTOONS_PATTERNS = """## Competitor: PsychToons JP (đối thủ chính)

- Quy mô: 40.2K subs (+14.5K/30 ngày), 103 video, nhịp đăng ~1/ngày → kênh này không đua tần suất; khác biệt bằng chiều sâu nghiên cứu
- Nhân vật: bald round-headed cartoon figure (đầu tròn hói to, da pale cream, mắt đen tròn có highlight trắng nhỏ, mí mắt nặng + 1 đường crease, lông mày đen mảnh cong, mũi cung nhỏ, miệng nét nhỏ, tỷ lệ chibi — đầu to thân mũm mĩm) mặc muted slate-blue crewneck + áo trắng cổ nhọn, quần khaki thẳng, giày canvas xanh trắng → kênh này DÙNG CÙNG archetype nhân vật cartoon này ở MỌI cảnh (nhân vật hư cấu, không tái tạo khuôn mặt người thật) — NGUỒN CHUẨN: CHARACTER_BIBLE trong youtube_pipeline/resource_prompts.py, mọi prompt nội suy từ đó
- Style đối thủ: 2D cartoon illustration, clean bold black outlines, flat soft shading, muted palette → kênh này GIỮ CÙNG ngôn ngữ cartoon phẳng, không quay lại photorealistic; style lock kênh đã chốt trong QA `validate_thumbnail`: flat illustrated cartoon, thick black outline, solid colors, no gradients, nền navy #1A2332
- Thumbnail: một nhân vật làm focal point duy nhất, một headline ngắn → giữ đúng công thức, chỉ đổi góc máy / crop / biểu cảm / hand pose (palette theo style lock kênh, không copy muted palette của đối thủ)
- Mechanism bão hòa: 課題の分離, 自己肯定感 — đã khai thác sâu, chọn góc chưa trùng
- Title pattern: "〜な人の特徴", "〜する方法" → overused, tránh dùng trực tiếp
- Cultural angle: "Japanese Wisdom" generic → kênh bản địa có lợi thế chiều sâu — đào sâu hơn
- Reframe signature: "Not X. It's Y. And there's a difference." lặp 3–5 lần/video (landing XではなくY + nêu tên sự khác biệt) → đã bake thành review rule v9 V-bis + metric `reframe_signature` (psychology_format_check)
- Ending: self-understanding, không quick fix / generic motivation → khớp CONSTANTS.ending_policy
- Format: video gần đây dài 13–19 phút (mega-viral 2.36M views dài 10:27) → kênh này giữ focus 9-11 phút với payoff nghiên cứu dày hơn; nâng `duration_standard` 13-15 phút chỉ khi retention cho phép
- Narration: voiceover neutral, không cá tính → kênh này cần giọng ấm, có chiều sâu cảm xúc
"""


def competitor_inject_text() -> str:
    """Return the competitor context block for injection into prompts."""
    return PSYCHTOONS_PATTERNS
