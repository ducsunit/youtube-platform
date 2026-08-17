---
name: "skill_tam_ly_hoc_image_production_JP"
description: "Sản xuất storyboard và prompt ảnh cho video tâm lý học Nhật Bản dựa trên visual beat, visual event density, continuity và timeline audio thật."
---

> ⚠️ BẮT BUỘC: Đọc `skills/CHANNEL_CONSTANTS.md` trước khi dùng skill này.
> Mọi giá trị global reference qua key `CONSTANTS.<key>`. Không hardcode số.
> Nếu không đọc được file đó, dừng lại — không tự đoán.

# IMAGE PRODUCTION JP — STORYBOARD & PROMPTS

> Phiên bản 2.6.0 — cập nhật 2026-08-08: chỉ xuất `prompts-ALL.txt`, bỏ prompt batch; density ảnh tính động theo duration/sections.

Nhận `IMAGE_STRATEGY` từ Image Master và full script.

## 0. DELIVERABLE — PROMPT, KHÔNG PHẢI ẢNH

Skill này giao storyboard và prompt dạng chữ. Người dùng gen ảnh bằng công cụ của họ.

CẤM tự render ảnh bằng PIL/Pillow/matplotlib/HTML-canvas, kể cả để minh hoạ bố cục hay "xem thử". Ảnh do Claude vẽ không phải ảnh sẽ gen ra, nên nó không kiểm tra được gì mà chỉ tốn thời gian và gây lẫn về việc file nào là thật.

Được phép tính bằng code các đại lượng không cần ảnh: đếm số prompt, cộng thời lượng beat, kiểm tỉ lệ mascot, kiểm mật độ front-load.

## 1. NGUYÊN TẮC

- Mỗi prompt phải phục vụ một visual beat cụ thể.
- Không gen nhiều ảnh chỉ khác rất ít.
- Ưu tiên variation có ý nghĩa: wide/medium/detail, literal/symbolic, outside/inside, before/after.
- Không chữ, không phụ đề, không watermark.
- Giữ consistency về nhân vật, trang phục, tóc, tuổi, căn phòng và palette.
- **Không ảnh lấp chỗ:** mỗi ảnh phải mang một thông tin thị giác mới. Ảnh chỉ để "có cái gì đó trên màn hình" ⇒ bỏ, thay bằng motion/crop trên ảnh trước.
- **Mascot chỉ hỗ trợ mood:** không để Kokoro là chủ thể của mọi khung. Giữ đúng `mascot_ratio` từ IMAGE_STRATEGY; các beat đời sống thật / môi trường / đồ vật phải để mascot vắng hoặc ở rìa.

## 2. PROMPT STRUCTURE

Mỗi prompt gồm:

1. Mục tiêu cảnh.
2. Chủ thể và hành động.
3. Biểu cảm/tư thế.
4. Bối cảnh Nhật Bản cụ thể.
5. Composition và shot type.
6. Ánh sáng.
7. Palette.
8. Style anchor.
9. Continuity lock.
10. Negative constraints.

Prompt viết bằng tiếng Anh tối ưu cho công cụ tạo ảnh; tên file và ghi chú bằng tiếng Việt/Nhật tùy pipeline.

## 2a. MỖI PROMPT PHẢI TỰ ĐỦ (bắt buộc)

Mỗi prompt là MỘT khối copy-paste được ngay. CẤM tách style/continuity/negative ra một block "GLOBAL" ở đầu file rồi để các prompt bên dưới tham chiếu tới nó.

```yaml
SELF_CONTAINED_PROMPT_RULES:
  style_anchor:      "viết đủ trong từng prompt (16:9/palette/Negative:) — style text lấy từ CONSTANTS.image_style_lock"
  character_lock:    "nếu có nhân vật: tuổi, tóc, mắt, trang phục, giới hạn biểu cảm — viết lại từng lần"
  setting_lock:      "nếu có bối cảnh quen: mô tả lại phòng/quán, không ghi 'same as above'"
  mascot_lock:       "nếu có mascot: mô tả lại hình dáng + ràng buộc 'nhỏ, ở rìa'"
  negative:          "viết đủ trong từng prompt, không trỏ tới negative dùng chung"
  forbidden_phrases: ["same as above", "as previous", "see global lock", "cùng như trên", "dùng lock ở đầu file"]
```

Boilerplate lặp giữa các prompt là **chủ ý**, không phải rác. Lặp trong file text không tốn gì; thiếu lock lúc gen thì mất continuity cả video và không sửa được sau khi đã gen.

Metadata (ID ảnh, beat, timestamp, mục tiêu, motion) đặt **ngoài** vùng copy, phía trên một dòng `PROMPT:`. Từ sau `PROMPT:` trở đi là phần người dùng bôi đen — không được lẫn ghi chú.

## 2b. SINH FILE PROMPT BẰNG SCRIPT, KHÔNG VIẾT TAY

Vì mục 2a bắt lặp toàn bộ lock ở mọi prompt, viết tay vài chục prompt chắc chắn sẽ quên lock ở đâu đó.

- Khai báo lock một lần thành hằng số (STYLE / CHARACTER_* / SETTING_* / MASCOT / NEG) trong `prompts-build.py`, rồi ghép bằng code.
- Mỗi row chỉ chứa phần RIÊNG của ảnh đó: `(img, beat, time, events, goal, motion, body, locks, extra_negative)`.
- Sửa prompt ⇒ sửa trong script rồi chạy lại, không sửa tay file .txt (sửa tay sẽ lệch với file tổng hợp).

## 3. TIMELINE

- Nếu có `TRUE_AUDIO_DURATION` và timestamps: dùng mốc thật.
- Nếu chưa có audio: gắn `DRAFT_TIMING` và không tuyên bố chính xác.
- 0–90 giây phải có mật độ visual event cao hơn phần sau (front-load bắt buộc, khớp density_check của strategy).
- Ghi rõ event nào là ảnh mới, event nào là motion/crop từ ảnh cũ.

## 4. STORYBOARD OUTPUT

| ID | Time | Script beat | Visual mode | New image? | Mascot? | Visual info mới | Motion/crop | Prompt | Continuity note |
|---|---|---|---|---|---|---|---|---|---|

Cột `Visual info mới` bắt buộc điền — nếu trống thì hàng đó là filler, phải xử.
Cột `Mascot?` để kiểm tỷ lệ mascot không vượt ngưỡng chiến lược.
Cột `New image?` ghi `♻️ reuse IMG-xx` cho beat tái dùng ảnh — beat đó KHÔNG có prompt riêng.

## 4a. FILE PROMPT TỔNG HỢP — THUẦN PROMPT, KHÔNG GÌ KHÁC

```yaml
FINAL_MERGED_PROMPT_FILE:
  path: "prompts/prompts-ALL.txt"
  when: "ngay sau khi toàn bộ prompt pack PASS validator"
  source: "sinh trực tiếp từ prompt pack đã validate"
  content_rule: "CHI chua than prompt. Moi prompt mot khoi, cach nhau MOT dong trong."
  forbidden_in_file:
    - "header, title, timing, dong 'cach dung'"
    - "muc luc / danh sach batch"
    - "dong ID kieu 'P-01 · IMG-01 · B01'"
    - "dong 'muc tieu' / 'motion' / 'PROMPT:'"
    - "duong ke '====' hoac '----'"
  checks_by_code:
    - "so khoi == tong so anh unique cua ca video"
    - "khong khoi nao chua metadata/ke/ID (quet bang danh sach tu cam)"
    - "moi khoi la MOT doan lien tuc, khong xuong dong giua prompt"
    - "moi khoi van du Style/Composition/Negative (mục 2a khong duoc noi long)"
    - "noi dung tung khoi khop image tương ứng trong prompt-pack.json"
```

Lý do: file tổng hợp dùng để gen hàng loạt hoặc đưa vào công cụ batch. Bất kỳ ký tự nào không phải prompt đều là rác người dùng phải tự lọc, và khi lọc bằng tay sẽ có lúc cắt nhầm vào lock.

Phase 1 chỉ xuất `prompts-ALL.txt`; metadata ID–beat–timestamp nằm trong storyboard và `prompt-pack.json`. Không tạo hoặc giữ `prompts-batch-N.txt`, tránh artifact thừa và lệch phiên bản.

## 5. QUALITY GATE

- First frame khớp thumbnail.
- Không quá 2 event liên tiếp cùng shot/pose/background.
- Không dùng biểu tượng trừu tượng quá 2 lần liên tiếp.
- Mỗi hình phải đọc được không cần lời thoại, nhưng không được kể sai ý.
- Tránh aesthetic đẹp nhưng không thêm thông tin (no-filler).
- Mascot không chiếm trọng tâm mọi khung — có beat đời sống thật.
- Mật độ đầu video cao hơn cuối.
- **Mỗi prompt tự đủ** theo mục 2a: có style + character/setting/mascot lock + composition + negative viết thẳng trong khối; không chứa cụm tham chiếu ngoài.
- **Chống phình số lượng ảnh (gate bằng code):** tổng unique images phải bám `estimated_unique_images` của strategy. Kiểm bằng tỉ lệ `visual_events / unique_images` — nếu tụt về gần 1.0 nghĩa là đang gen mỗi beat một ảnh. Ngưỡng chặn: tỉ lệ < CONSTANTS.visual_events_per_image_min ⇒ FAIL, phải tìm beat để reuse.
  - Chỗ reuse tự nhiên nhất: beat `loop`/`repetition` (lặp lại phải là *cùng một ảnh* thì mới đọc ra nghĩa lặp), beat `crop`/`detail` của một ảnh đã có, beat `callback` khung cũ.
  - Khi định reuse, thêm sẵn chi tiết cần crop vào prompt của ảnh gốc (ví dụ ảnh "ba chiếc túi" phải có sẵn ba cái nhãn để beat sau crop vào).
  - Beat reuse phải trỏ tới ảnh có thật trong danh sách ảnh mới — kiểm bằng code.
- **Có `prompts-ALL.txt`** theo mục 4a, thuần prompt và khớp `prompt-pack.json`; không còn file batch.

## 6. FINAL OUTPUT

Xuất:

```yaml
IMAGE_PRODUCTION_SUMMARY:
  unique_images:
  total_visual_events:
  events_per_image:          # so voi estimated cua strategy — canh bao neu < 1.30
  reused_image_beats:        # beat nao dung lai anh nao, va bang cach nao (loop/crop/callback)
  opening_match:
  mascot_ratio_actual:       # khớp trần của IMAGE_STRATEGY, < 100%
  front_load_ok:             # đầu dày hơn cuối
  no_filler_confirmed:       # mọi ảnh có visual info mới
  timeline_status:
  continuity_status:
  prompt_count:
  self_contained_confirmed:  # mọi prompt copy một khối là gen được
  merged_prompt_file:        # prompts/prompts-ALL.txt — thuần prompt, đã đối chiếu prompt-pack.json
```

Sau đó xuất storyboard đầy đủ. Prompt nằm ở các file .txt, không dán lại toàn bộ vào chat.
