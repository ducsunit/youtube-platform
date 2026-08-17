# Checklist: Tích hợp Full Flow vào Pipeline Tự Động

> **Vấn đề gốc:** Pipeline hiện tại (22 stages) không đọc `skills/`, `content/`, hay kết quả nghiên cứu đối thủ.
> Toàn bộ kiến thức bị bake cứng trong `resource_prompts.py`. Video không cải thiện vì pipeline không học.
>
> **Mục tiêu:** Inject có chọn lọc vào từng stage — không phải tất cả mọi thứ vào mọi chỗ.

---

## Quyết định kiến trúc tổng thể

| Loại dữ liệu | Cách inject | Lý do |
|---|---|---|
| `content/video-queue.md` | **Runtime read** tại `topic_selection` | Thay đổi thường — không nên bake |
| `content/mechanisms.md` | **Runtime read** tại `topic_research` + `writing` | Cần lookup linh hoạt |
| `content/cultural-frames-jp.md` | **Runtime read** tại `writing` | Pair với mechanism → dynamic |
| Competitor analysis (PsychToons) | **Bake trong prompts** + refresh thủ công | Ít thay đổi, cần ổn định |
| "Nhật ký dùng" update | **Post-publish hook** | Sau khi publish mới có data |

---

## A. Inject `content/video-queue.md` → Stage `topic_selection`

**Mục đích:** Pipeline chọn topic từ queue đã nghiên cứu thay vì để Gemini tự generate.

### Thay đổi cần làm

- [ ] **A1.** Đọc `content/video-queue.md` trong `ResourceProvider._topic_selection_prompt()`
  - Parse các topic có `status: queued` → lấy topic đầu tiên (hoặc ưu tiên theo score)
  - Inject vào system prompt: "Ưu tiên chọn từ danh sách sau: [topic, mechanism, cultural_frame]"
  - Nếu queue rỗng → fallback về behavior hiện tại (Gemini tự propose)

- [ ] **A2.** Format chuẩn trong `video-queue.md` để parse được:
  ```markdown
  ## Topic: [tên topic]
  - mechanism: [tên cơ chế]
  - cultural_frame: [frame]
  - backup_mechanism: [backup]
  - status: queued | in_progress | published
  - priority: high | medium
  ```

- [ ] **A3.** Sau khi pipeline chọn topic → update `status: queued` → `status: in_progress`
  - Tạo helper `content_manager.py` với `mark_topic_in_progress(topic_name)`
  - Gọi sau khi `topic_selection` stage hoàn tất

- [ ] **A4.** Viết test:
  - `test_topic_selection_uses_queue_when_available()`
  - `test_topic_selection_fallback_when_queue_empty()`

**File cần sửa:** `youtube_pipeline/resource_provider.py` (hàm `_topic_selection_prompt`)
**File mới:** `youtube_pipeline/content_manager.py`

---

## B. Inject `content/mechanisms.md` → Stage `topic_research` + `writing`

**Mục đích:** Pipeline biết mechanism nào đã dùng (diversity gate) và có citation sẵn.

### Thay đổi cần làm

- [ ] **B1.** Tạo parser `content/mechanisms.md` → dict:
  ```python
  {
    "感情労働": {
      "author": "...", "year": "...", "source": "...",
      "hook": "...", "status": "available" | "paused",
      "recent_use_count": 0  # đọc từ Nhật ký
    },
    ...
  }
  ```

- [ ] **B2.** Diversity gate tại `topic_selection` / `topic_research`:
  - Đọc `mechanism_diversity_window: 3` từ `CHANNEL_CONSTANTS.md`
  - Parse "Nhật ký dùng" trong `video-queue.md` → lấy 3 mechanism gần nhất
  - Nếu mechanism của topic đang chọn trùng → cảnh báo hoặc đề xuất backup

- [ ] **B3.** Inject citation sẵn vào `writing` stage:
  - Khi script contract đã lock mechanism → lookup `mechanisms.md` → inject:
    ```
    Nghiên cứu đã có sẵn cho [mechanism]:
    - [Author] ([Year]) — [Source] — "[Hook câu trích dẫn]"
    Dùng trực tiếp, không cần tìm lại.
    ```
  - Đảm bảo `research_min_count ≥ 3` vẫn pass ngay cả khi inject từ file

- [ ] **B4.** Mechanism ⛔ (tạm ngừng) phải bị lọc ra khỏi danh sách available:
  - Parse `⛔` flag trong `mechanisms.md` → exclude khỏi diversity check và injection

- [ ] **B5.** Viết test:
  - `test_mechanism_diversity_gate_blocks_overused()`
  - `test_citation_injection_from_mechanisms_md()`
  - `test_paused_mechanism_excluded()`

**File cần sửa:** `youtube_pipeline/resource_provider.py`
**File mới:** `youtube_pipeline/content_manager.py` (parser)

---

## C. Inject `content/cultural-frames-jp.md` → Stage `writing`

**Mục đích:** Mỗi video có cultural frame phù hợp được inject vào writing prompt.

### Thay đổi cần làm

- [ ] **C1.** Sau khi mechanism đã lock → lookup cultural frame trong `cultural-frames-jp.md`:
  - Mỗi mechanism có `Pair tốt với cơ chế` → tìm frame phù hợp
  - Inject vào writing prompt: frame name, vị trí gắn theo spine mới (reframe / mechanism block / insight landing / CTA), câu mẫu

- [ ] **C2.** Rule: mỗi video chỉ dùng tối đa 1 frame chính (enforce trong inject)
  - Parse field `Quy tắc: một video dùng tối đa 1 frame chính`
  - Nếu topic đã có frame trong queue → dùng frame đó, không tự chọn thêm

- [ ] **C3.** Sách gốc (甘えの構造, etc.) trong cultural frames KHÔNG tính vào `research_min_count`
  - Thêm tag `type: cultural_frame` trong injection để writing gate phân biệt

- [ ] **C4.** Viết test:
  - `test_cultural_frame_injected_matches_mechanism()`
  - `test_cultural_frame_book_not_counted_as_research()`

**File cần sửa:** `youtube_pipeline/resource_provider.py`

---

## D. Bake Competitor Analysis (PsychToons) vào Prompts

**Mục đích:** Pipeline biết PsychToons làm gì để ALIGN — giữ giống archetype nhân vật + style lock cartoon (đã xác nhận 2026-08-15), không copy 1-1 composition từng video.

### Thay đổi cần làm

- [x] **D1.** File `youtube_pipeline/competitor_context.py` (đã tạo, `_LAST_UPDATED = "2026-08-17"` — refresh sau nghiên cứu 4 transcript):
  ```python
  PSYCHTOONS_PATTERNS = """
  ## Competitor: PsychToons JP (đối thủ chính)
  - Quy mô: 40.2K subs (+14.5K/30 ngày), 103 video, nhịp đăng ~1/ngày → kênh này không đua tần suất; khác biệt bằng chiều sâu nghiên cứu
  - Nhân vật: bald round-headed cartoon figure ... (nhân vật hư cấu, không tái tạo khuôn mặt người thật) — NGUỒN CHUẨN: CHARACTER_BIBLE trong resource_prompts.py
  - Style: 2D cartoon illustration, clean bold black outlines ... GIỮ CÙNG style lock cartoon
  - Thumbnail: một nhân vật làm focal point duy nhất ... chỉ đổi góc máy / crop / biểu cảm / hand pose
  - Mechanism bão hòa: 課題の分離, 自己肯定感 → chọn góc chưa trùng (→ CONSTANTS.mechanism_diversity_window)
  - Reframe signature: "Not X. It's Y. And there's a difference." lặp 3–5 lần/video → bake thành review rule v9 V-bis + metric reframe_signature
  - Ending: self-understanding, không quick fix → khớp CONSTANTS.ending_policy
  - Format: video gần đây 13–19 phút → kênh này giữ focus 9-11 phút với payoff dày hơn
  """
  ```

- [x] **D2.** Inject `PSYCHTOONS_PATTERNS` vào các stage (đã làm trong resource_prompts.py + resource_pipeline.py):
  - `topic_candidates`: "không lặp mechanism PsychToons đã khai thác gần đây"
  - `thumbnail_contract`: "COMPETITOR ALIGNMENT — giữ archetype nhân vật + style lock cartoon, chỉ đổi góc máy/crop/biểu cảm"
  - `writing` → `review`: "COMPETITOR HOOK CHECK — giữ nhân vật + style nhất quán"

- [ ] **D3.** Refresh thủ công `competitor_context.py` định kỳ (sau mỗi 5-10 video)
  - Thêm comment `# Last updated: YYYY-MM-DD` để track

- [x] **D4.** Test đã viết trong `tests/test_competitor_context.py`:
  - `test_thumbnail_prompt_includes_alignment_when_context_given` (assertIn "COMPETITOR ALIGNMENT")
  - `test_thumbnail_prompt_omits_context_when_empty` (PsychToons-style trong STYLE LOCK cố định)
  - `test_review_prompt_*` (assertIn "COMPETITOR HOOK CHECK")

**File mới:** `youtube_pipeline/competitor_context.py`
**File cần sửa:** `youtube_pipeline/resource_prompts.py` (inject constant)

---

## E. Post-Publish: Update "Nhật ký dùng"

**Mục đích:** Sau khi publish → ghi lại mechanism đã dùng để diversity gate hoạt động.

### Thay đổi cần làm

- [ ] **E1.** Stage `publish_draft` (hoặc `resource_pack`) → sau khi publish thành công:
  - Ghi vào `content/video-queue.md` mục "Nhật ký dùng":
    ```markdown
    ## Nhật ký dùng
    - YYYY-MM-DD | [topic] | mechanism: [tên] | cultural_frame: [tên] | video_id: [YT_ID]
    ```
  - Update status của topic: `in_progress` → `published`

- [ ] **E2.** Tạo `content_manager.mark_topic_published(topic_name, video_id, mechanism, frame)`
  - Append vào Nhật ký dùng
  - Update status trong video-queue.md

- [ ] **E3.** Diversity gate (mục B2) reads từ Nhật ký dùng này

- [ ] **E4.** Viết test:
  - `test_publish_updates_diary_and_status()`

**File cần sửa:** `youtube_pipeline/resource_provider.py` (stage `resource_pack`)
**File mới (hoặc cập nhật):** `youtube_pipeline/content_manager.py`

---

## Thứ tự thực hiện (ưu tiên)

| Bước | Task | Lý do ưu tiên |
|---|---|---|
| 1 | **D** — Competitor context bake | Nhanh nhất, impact ngay, không cần parse file |
| 2 | **A** — Video queue inject | Giải quyết "pipeline tự chọn topic ngẫu nhiên" |
| 3 | **B** — Mechanism diversity gate + citation | Prevents 課題の分離 overuse, citations tiết kiệm thời gian |
| 4 | **C** — Cultural frames inject | Depends on mechanism lock (phải làm sau B) |
| 5 | **E** — Post-publish diary update | Closes the loop, depends on A+B working |

---

## Files tổng kết cần tạo/sửa

| File | Action | Notes |
|---|---|---|
| `youtube_pipeline/competitor_context.py` | **TẠO MỚI** | Bake competitor patterns |
| `youtube_pipeline/content_manager.py` | **TẠO MỚI** | Parse + update content/ files |
| `youtube_pipeline/resource_provider.py` | **SỬA** | Inject vào 4 stages |
| `youtube_pipeline/resource_prompts.py` | **SỬA** | Inject competitor_context |
| `content/video-queue.md` | **SỬA** | Chuẩn hóa format + Nhật ký |
| `tests/test_content_manager.py` | **TẠO MỚI** | Tests cho content_manager |
| `tests/test_resource_pipeline.py` | **SỬA** | Thêm integration tests |

---

## Điều không thay đổi

- Pipeline vẫn chỉ đọc `youtube_data.json` cho performance data → không đổi
- 22 stages và thứ tự stages → không đổi  
- `_structure_check` 14 gates → không đổi
- Mọi inject là **additive** vào prompt — không thay thế logic hiện có
- Nếu `content/` file không đọc được → fallback về behavior hiện tại (không crash)
