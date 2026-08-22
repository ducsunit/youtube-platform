# Kế hoạch cải thiện flow — bám đối thủ 思考の深淵 + tối giản pipeline

Ngày lập: 2026-08-21
Mục tiêu người dùng: pipeline sinh **trọn bộ tài nguyên video tự động** (script + thumbnail + image prompt + minimax prompt + publish sheet) chạy **một phát ra được**, bám đúng đối thủ, để chỉ việc gen TTS/ảnh và dựng.

---

## 0. Phát hiện nền tảng (từ dữ liệu vidIQ)

Kênh đối thủ thật: **思考の深淵** — `UCIjZpNXE1He_l5Al-6lvOjg`, mở 18/07/2026.
- 1 tháng: **2.180 sub, 315K view, 27 video**. Topics: Knowledge + **Religion**. Video **32–55 phút**.
- Công thức thắng (27 title thực tế):
  - 100% **ユング心理学 (Carl Jung) + tâm linh**: 魂の覚醒, 個性化 (individuation), シャドウ (shadow), 無意識, 自己統合, スピリチュアル.
  - **Gọi thẳng tên lý thuyết + tác giả** ("カール・ユング") ở gần như mọi title.
  - Title grammar: `【完全版】` / `【ユング心理学】` + câu hỏi provocative + chuỗi thuật ngữ lý thuyết.
  - Video nổ nhất: 掃除の心理 49K view (vph 46), "魂が目覚めると人が嫌いになる" 39K.

### Mâu thuẫn gốc rễ với code hiện tại

Hệ validation hiện tại được xây để **CẤM đúng thứ làm đối thủ thắng**:

| Cơ chế trong code | Vị trí | Hệ quả |
|---|---|---|
| `KNOWN_NAMED_FRAMEWORKS` cấm mọi framework không có trong source | `claim_ledger.py:17-25, 211-214` | Cấm gọi tên "Jung / individuation / shadow" |
| `source_catalog` chỉ có **15 nguồn học thuật, 0 nguồn Jung** | `resource_pack/source_catalog.py` | source_lock không thể khoá nguồn Jung |
| `causal_capability_violations` + `unsupported_source_claims` | `claim_ledger.py`, `validation.py` | Cấm diễn giải tâm lý vượt "mức nguồn" |
| `competitor_context.py` ghi "do not import spiritual certainty" | dòng 23 | Cấm ngôn ngữ tâm linh — thứ đối thủ dùng |

→ Model bị kẹt giữa "đề tài buộc nói về Jung/linh hồn" và "validator cấm nói" → mỗi topic đụng một validator khác → **lỗi trông ngẫu nhiên mỗi run** (đã xác nhận qua video-09/-v2/-v3: 3 stage chết khác nhau vì 3 lý do khác nhau).

**Kết luận: chỉ sửa độ ổn định là chưa đủ. Phải sửa cả ĐỊNH VỊ nội dung thì tài nguyên mới thật sự bám đối thủ.**

---

## 1. Nhóm A — Sửa định vị (gốc rễ, làm TRƯỚC)

### A1. Viết lại `competitor_context.py`
- Định vị mới: **Jungian深層心理 + tâm linh phản tỉnh**, video 32–55 phút.
- Title grammar: `【完全版】/【ユング心理学】` + provocative question + thuật ngữ (個性化/シャドウ/無意識).
- Bỏ dòng cấm "spiritual certainty"; thay bằng "ngôn ngữ tâm linh phản tỉnh, không hứa chữa lành/không diagnosis".
- Đây là file định hướng cả pipeline (inject vào topic_candidates, review, thumbnail).

### A2. Cho phép named framework khi LÀ concept đã khoá
- `claim_ledger.py:211-214`: không cấm mặc định framework nếu nó khớp `source_concept` của run.
- Thêm Jung/individuation/shadow vào danh sách "framework hợp lệ khi được khoá làm concept chính".

### A3. Mở rộng `source_catalog` cho nguồn Jung
- Thêm nguồn Jung đã xác minh (Collected Works, individuation, shadow, archetype) vào `APPROVED_SOURCE_CATALOG`.
- Không thì source_lock luôn fail cho mọi đề tài Jung.

### A4. Nới capability cho tâm lý học chiều sâu
- Thể loại này là **"diễn giải lý thuyết Jung"**, không phải "khẳng định neuroscience".
- Điều chỉnh `SENSITIVE_CLAIM_MARKERS` / `causal_capability_violations` để phân biệt "diễn giải symbolic theo Jung" (cho phép) vs "khẳng định khoa học thần kinh" (vẫn cấm).

---

## 2. Nhóm B — Độ ổn định (mỗi run chạy được)

### B1. Gate topic↔source tại `topic_selection`
- Loại candidate mismatch NGAY ở stage 5, thay vì chết ở stage 8–11.
- Nếu topic cần capability mà source pack không có → tự chọn candidate khác.

### B2. `translate_script_vi` → non-blocking
- Bản dịch VI chỉ là QA đọc cho người, **không phải tài nguyên dựng**.
- Timeout/lỗi → ghi warning, KHÔNG giết resource pack. (video-09 chết oan vì bước này.)

### B3. Corrective pass cho lỗi causal-capability ở `narrative_brief`
- Hiện `prediction_error_*` fail thẳng "no blind retry".
- Cấp đúng 1 pass sửa có mục tiêu (giống pass source-boundary đã có `pipeline.py:434-452`).

---

## 3. Nhóm C — Nhất quán hình ảnh

### C1. Xoá nhánh khoá-hình legacy
- `resource_validation.py:663-703` còn ép **navy #1A2332 + flat cartoon** (sai đối thủ).
- Chỉ giữ nhánh chalk/ink charcoal ở `resource_pack/validation.py`.

### C2. Xác nhận char_max advisory
- video-09 ra 18202 char (~46 phút) — đúng dải đối thủ 32–55′ nhưng suýt bị max=18000 chặn.
- `metrics.py:80-97` đã hạ max thành advisory — nâng `target_char_max` cho khớp, tránh tự mâu thuẫn.

---

## 4. Tối giản flow: 20 stage → ~12 stage

Nhiều stage là di sản (từng tách brief/contract/planning rồi gộp thành `narrative_brief` nhưng chưa dọn xung quanh). Gộp:

| Hiện tại (20) | Gộp thành (~12) | Lý do |
|---|---|---|
| topic_research + topic_candidates + topic_selection | **topic_pick** | 3 model call cho 1 việc |
| source_lock + claim_ledger | **source_lock** | claim_ledger thuần code, derive từ source_pack |
| narrative_brief | giữ | đã gộp tốt |
| writing | giữ | |
| script_audit + script_qa + structure_check + psychology_format_check | **script_gate** | 3/4 thuần code (0 LLM); 1 gate + tối đa 1 repair |
| translate_script_vi | tách khỏi luồng bắt buộc (B2) | QA phụ |
| sections | giữ | |
| thumbnail_contract | giữ | |
| image_strategy + image_prompts | **images** | strategy chỉ feed prompts; bỏ 1 lần validate lặp |
| publish_draft | giữ | |
| resource_pack | giữ | |
| ingest + performance | giữ (bỏ khi manual topic) | |

**Kết quả: ~12 stage, số model call ~11 → ~6.** Mỗi run nhanh hơn, ít điểm chết hơn.

---

## 5. Thứ tự thực thi đề xuất

1. **Nhóm A** (định vị) — gốc rễ, không sửa thì tài nguyên vẫn sai hướng.
2. **Nhóm B** (ổn định) — trả lại "chạy một phát ra tài nguyên".
3. **Nhóm C** (hình ảnh) — dọn dẹp, ít rủi ro.
4. **Tối giản flow** (mục 4) — làm cuối, sau khi A/B/C đã xanh test, vì đụng nhiều stage cùng lúc.

## 6. Kiểm thử

- Cập nhật/không phá `tests/` liên quan: `test_psychology_first_flow`, `test_claim_ledger`, `test_competitor_context`, `test_skill_constants`, `test_resource_pipeline`.
- Chạy `pytest` sau mỗi nhóm; một Run Live demo cho mỗi cột mốc A→B→C.
- Tiêu chí done: 3 run live liên tiếp với 3 topic Jung khác nhau đều ra đủ resource pack, không stage nào chết vì validator định vị.

## 7. Rủi ro & lưu ý

- A2/A3/A4 nới validator: phải giữ ranh giới an toàn (không diagnosis, không trauma cause với người thật, không neuroscience bịa). Chỉ nới cho "diễn giải symbolic Jung", không mở toang.
- Đổi định vị Jung → các test bake nội dung cũ (PsychToons) sẽ phải cập nhật, không phải xoá mù.
- `docs/PSYCHTOONS_*.md` là tài liệu lịch sử gây nhầm — nên thêm ghi chú trỏ về plan này (không xoá vội).
