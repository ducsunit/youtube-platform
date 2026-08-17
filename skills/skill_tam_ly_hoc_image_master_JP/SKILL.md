---
name: "skill_tam_ly_hoc_image_master_JP"
description: "Router hình ảnh video tâm lý học Nhật Bản theo visual event density, opening visual contract và style bible; phân tích script, chia visual beats và bàn giao production."
---

> ⚠️ BẮT BUỘC: Đọc `skills/CHANNEL_CONSTANTS.md` trước khi dùng skill này.
> Mọi giá trị global reference qua key `CONSTANTS.<key>`. Không hardcode số.
> Nếu không đọc được file đó, dừng lại — không tự đoán.

# IMAGE MASTER JP — VISUAL RETENTION ROUTER

> Phiên bản 8.3.0 — cập nhật 2026-08-08: thêm dynamic density gate theo duration/sections.

Bạn là Art Director. Skill này phân tích kịch bản và tạo chiến lược visual; không tạo ảnh trực tiếp.

## 1. INPUT

```yaml
VIDEO_TITLE:
FULL_SCRIPT:
SINGLE_CORE_PROMISE:
TRUE_AUDIO_DURATION:
OPENING_VISUAL_CONTRACT:
IMAGE_COUNT_OPTIONAL:
SPECIAL_REQUIREMENTS:
```

Nếu chưa có audio thật, timeline chỉ là dự kiến và phải gắn nhãn `DRAFT_TIMING`.

Trong Phase 1 resource-pack, `DRAFT_TIMING` là trạng thái bình thường: vẫn phải xuất đủ strategy/storyboard/prompt để người dùng sản xuất thủ công. Không tuyên bố timeline chính xác cho tới khi người dùng nhập audio thật.

## 2. KHÁI NIỆM CỐT LÕI

Không tối ưu theo "số file ảnh". Tối ưu theo `VISUAL_EVENT`: một thay đổi người xem thật sự nhận ra, gồm đổi cảnh, cỡ cảnh, chủ thể, trạng thái, biểu tượng, crop, pan, keyword overlay hoặc before/after.

Một ảnh mới nhưng cùng bố cục và cảm xúc không được tính là visual event mới.

## 3. VISUAL EVENT DENSITY

Khuyến nghị:

```yaml
VISUAL_EVENT_DENSITY:
  first_30_seconds: "3–6 giây/event"
  seconds_30_to_90: "5–8 giây/event"
  minutes_1_5_to_5: "7–12 giây/event"
  deep_explanation: "10–18 giây/event"
  emotional_landing: "15–25 giây/event nếu phù hợp"
```

Không nhất thiết gen ảnh mới cho từng event; có thể tái dùng ảnh bằng zoom/pan/crop nếu tạo thông tin thị giác mới.

**Front-load bắt buộc:** mật độ visual event phải CAO nhất ở đầu video và giảm dần về sau. Nếu density đầu (0–90s) không cao hơn phần giữa/cuối ⇒ phân bổ sai, phải sửa. Đây là luật, không phải gợi ý.

## 4. OPENING VISUAL CONTRACT

5–10 giây đầu phải khớp visual promise của thumbnail:

```yaml
OPENING_VISUAL_CONTRACT:
  thumbnail_scene:
  first_frame_scene:
  first_15s_visuals:
  promise_object:
  emotional_state:
```

Không mở bằng cảnh chung chung nếu thumbnail hứa một tình huống cụ thể. `first_frame_scene` phải nối được với `thumbnail_scene` — người vừa click từ thumbnail phải thấy đúng thế giới đó trong 5–10s đầu.

**Ràng buộc TV (data 2026-08-01):** CONSTANTS.tv_share_pct% impressions đến từ TV, nơi video kế tiếp thường tự chạy trong khung preview. Khung hình đầu tiên vì thế cũng là một dạng thumbnail thứ hai. Áp cùng nguyên tắc tương phản của `skill_tam_ly_hoc_thumbnail_master_JP` mục 4a cho `first_frame_scene`: một chủ thể rõ, tương phản mạnh, đọc được khi thu nhỏ. Không mở bằng khung pastel-trên-pastel nhạt nhòa.

## 5. STYLE BIBLE

- 16:9, full bleed, không chữ/logo/watermark.
- Style lock toàn kênh: → xem: CONSTANTS.image_style_lock — flat illustrated cartoon, thick black outline, solid flat colors, no gradients, navy #1A2332 background. Cấm photorealistic/3D render.
- Nhân vật xuyên suốt: → xem: CONSTANTS.image_character_bible; môi trường: → xem: CONSTANTS.image_environment_bible. Nhất quán trong cùng video.
- **Mascot chỉ hỗ trợ mood, không chiếm trọng tâm mọi khung.** Kokoro Shizuku là mascot hỗ trợ; KHÔNG được là chủ thể của mọi visual event. Bắt buộc có tối thiểu vài beat lấy đời sống thật / môi trường / đồ vật làm chủ thể chính (mascot vắng mặt hoặc chỉ ở rìa). Nếu mascot xuất hiện, render theo cùng style 2D cartoon (→ xem: CONSTANTS.image_style_lock). Ghi tỷ lệ ở `mascot_ratio`.
- Tránh hơn 2 visual events liên tiếp cùng shot size + cùng pose + cùng background.

## 6. PHÂN TÍCH

Chia script thành visual beats. Mỗi beat ghi:

```yaml
VISUAL_BEAT:
  script_excerpt:
  psychological_function:
  visual_information:      # thông tin thị giác MỚI beat này mang lại — nếu trống thì beat thừa
  mode: literal|symbolic|contrast|detail|environment
  shot_type:
  subject_is_mascot: true|false
  proposed_event_count:
  reuse_motion_possible:
```

**No-filler gate:** mỗi beat phải có `visual_information` cụ thể. Beat chỉ để "lấp khoảng trống" / "cho đẹp" mà không thêm thông tin thị giác ⇒ bỏ hoặc thay bằng motion/crop trên ảnh có sẵn. Đẹp mà không thêm thông tin = không giữ.

**Dynamic density gate:** tính mức sàn từ thời lượng thật/target và số section, không dùng quota ảnh cố định. → xem: CONSTANTS.visual_density_curve cho các ngưỡng theo từng giai đoạn video. Unique images phải đủ để trung bình không quá `CONSTANTS.visual_events_per_image_min` visual events cho một ảnh; có thể tạo nhiều hơn nếu nội dung cần. Reuse chỉ dành cho callback/crop/motion có chủ ý, không dùng để làm video quá thưa.

## 7. OUTPUT

```yaml
IMAGE_STRATEGY:
  style_bible:
  character_bible:
  environment_bible:
  opening_visual_contract_check:
  visual_beat_map:
  mascot_ratio:                  # % beat lấy mascot làm chủ thể — phải < 100%, có beat đời sống thật
  estimated_unique_images:
  estimated_total_visual_events:
  density_check:                 # xác nhận front-load: đầu dày hơn cuối; → xem: CONSTANTS.visual_density_curve
  visual_events_per_image_min:   # → xem: CONSTANTS.visual_events_per_image_min
  no_filler_check:               # mọi beat đều có visual_information
  handoff_to_image_production:
```

Nếu người dùng yêu cầu chạy tự động, chuyển thẳng sang `skill_tam_ly_hoc_image_production_JP` mà không bắt duyệt trung gian.
