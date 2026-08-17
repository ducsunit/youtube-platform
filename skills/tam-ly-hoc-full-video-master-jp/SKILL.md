---
name: tam-ly-hoc-full-video-master-jp
description: Điều phối resource pack hoàn chỉnh cho video animated psychology tiếng Nhật 9–11 phút bằng psychology-first adaptive workflow; mechanism là spine, storytelling chỉ là micro-example.
---

> ⚠️ **BẮT BUỘC:** Đọc `skills/CHANNEL_CONSTANTS.md` trước khi dùng workflow này.

# FULL VIDEO RESOURCE MASTER JP — PSYCHOLOGY-FIRST

> ⚠️ Đọc `skills/CHANNEL_CONSTANTS.md` trước khi điều phối. Psychology là xương sống; viewer là trung tâm; không dựng plot/character arc.

Điều phối các skill con theo checkpoint. Dừng ở resource pack; người dùng chỉ cần gen audio/ảnh rồi bỏ vào đúng thư mục, video được ráp tự động.

Giữ phân vai model: dùng Gemini chỉ cho research, topic/source selection và review/audit; dùng DeepSeek cho mọi bước tạo nội dung, script, thumbnail prompt, image prompts và publish draft.

## Input

```yaml
YOUTUBE_DATA:
CHANNEL_POSITIONING:
RECENT_REASSURANCE_LINES: []
SPECIAL_REQUIREMENTS:
```

MiniMax profile bắt buộc: `CONSTANTS.tts_profile`; CPM dùng `CONSTANTS.cpm_range` / `CONSTANTS.cpm_measured`.

## Workflow

Chạy đúng thứ tự; không chạy downstream khi gate upstream fail:

1. Dùng `skill_tam_ly_hoc_performance_review_JP` tạo `PERFORMANCE_REVIEW` và một giả thuyết thử nghiệm.
2. Dùng Gemini tạo `TOPIC_RESEARCH`, 8–12 `TOPIC_CANDIDATES`, chấm điểm và chọn đúng một `SELECTED_TOPIC`; không nhận topic thủ công.
3. Tạo `TOPIC_SOURCE_CONTRACT` có nguồn xác minh, attribution được phép/cấm và editorial application.
4. Dùng Script Master tạo artifact `PSYCHOLOGY_BRIEF`: behavior/type, non-diagnostic identity, core question, main tension, 2–3 selected mechanisms, causal chain, inner process, route và optional-branch decisions. Gate fail nếu chưa khóa được causal spine.
5. Từ brief, khóa promise/title/hook/format trong `SCRIPT_CONTRACT`; dùng `CONSTANTS.duration_focus` và char/CPM constants.
6. Dùng Script Planning tạo adaptive 6–8 sections: recognition ngắn → misconception/reframe/question → mechanism blocks → optional branches có lý do → integration → self-understanding insight. Không exact 7-part, mandatory origin/childhood hoặc scene montage.
7. Dùng Script Production để DeepSeek viết direct-to-viewer script Nhật. Gemini review theo `review-rule-v9.md` (Psychology-First Review v9): audit causal spine, behavior→mechanism→inner process, story dominance, lecture/self-help, fact integrity và FORMAT_ALIGNMENT A–E (D/E bắt buộc revise); được phép đổi route khi story chi phối. DeepSeek hoàn thiện từ `revised_draft_clean` mà không thêm claim. Chạy deterministic + semantic anti-story gate; FAIL phải rewrite, không chỉ warning. Stage sections vẫn xuất script sạch, sections và một MiniMax prompt khớp 100%. Sau structure_check, stage `psychology_format_check` (thuần code, 0 LLM) đo 7 metrics 0–10 + gate gợi ý CHƯA calibrate — non-blocking, log để đối chiếu retention sau 10–20 video (Sprint 6). Sau đó stage `translate_script_vi` dịch script sang tiếng Việt (`script/script-vi.txt`) CHỈ để bạn đọc duyệt — không dùng cho TTS hay ghép audio.
8. Dùng `skill_tam_ly_hoc_thumbnail_master_JP` tạo thumbnail contract/prompt/overlay spec; squint test thật để `PENDING_USER`.
9. Dùng `skill_tam_ly_hoc_image_master_JP` tạo image strategy với `DRAFT_TIMING`.
10. Dùng `skill_tam_ly_hoc_image_production_JP` tạo storyboard và duy nhất `prompts-ALL.txt`; số visual events/ảnh unique được tính động từ duration + sections, reuse có chủ đích, không xuất file batch.
11. Timeline KHÔNG còn là stage pipeline — tính động khi Dựng video (build service build từ storyboard/strategy/sections/planning + audio thật trong `audio/`: FINAL_TIMING nếu đo được duration, ngược lại DRAFT_TIMING). Không viết tay bảng timeline.
12. Dùng `skill_tam_ly_hoc_description_master_JP` tạo description draft, pinned comment và source note; bỏ chapters khi chưa có audio.
13. Chạy resource-pack QA và xuất manifest/checklist thủ công — pipeline 22 stage dừng ở `resource_pack`.
14. Dựng video là bước NGOÀI pipeline (web tab "Dựng video" hoặc chạy tay): bỏ audio ghép vào `audio/` + ảnh đã gen (tên `IMG-xx`) vào `video-build/images/` → build service tính timeline, cắt audio theo section (1 file/section), sinh `prompts-build.py` + `marks.tsv` (không còn `script.txt` trong pack), copy SRT từ `subtitles/` nếu có → rồi gọi `youtube_pipeline/build-video.py` ráp `video-final.mp4`. Thiếu gì sẽ báo trong `video-build/build-report.json` (WAITING_AUDIO / WAITING_IMAGES + ID thiếu); đủ → bấm Dựng (hoặc `.venv/bin/python -m youtube_pipeline.build_service runs/<run_id> --prepare-only` rồi render). Skeleton `audio/`, `subtitles/`, `video-build/{audio,images,import,srt}` luôn được tạo sẵn. Kịch bản quyết định video qua pipeline — `script.txt` không còn là input của bước dựng.

Không gọi `skill_tam_ly_hoc_seri_JP`.

## Required gates

- Source có URL và không giả quote/endorsement.
- `PSYCHOLOGY_BRIEF` khóa một core question, main tension khi phù hợp, 2–3 selected mechanisms, causal chain và inner process trước outline.
- Planning dùng adaptive route; core phases đủ, optional branches có lý do/source; origin/childhood/trauma không mặc định.
- Script là tiếng Nhật, duration/char range theo `CONSTANTS.duration_focus`, `char_range_target`, `char_range_absolute`, `cpm_range`.
- Recognition/insight/core question theo `CONSTANTS.hook_contract`; mechanism không bị trì hoãn bởi scene/backstory.
- Mỗi mechanism giải thích behavior + why + inner process; ending tạo self-understanding.
- Viewer-centered direct narration; không fictional protagonist, plot, character arc, dialogue chain hoặc scene continuity; micro-example và total scene ratio theo constants.
- Dual fact/psychology/anti-story audit pass; semantic fail kích rewrite hoặc dừng.
- Reviewer không được bịa claim; final script do DeepSeek tạo trên nền `revised_draft_clean` hoặc giữ draft đã pass.
- Script có nhịp nghỉ tự nhiên bằng dấu câu/paragraph; `script.txt` sạch, tag `<#x#>` chỉ trong `minimax-prompt.txt`; xuất `pause-map.json` riêng.
- Sections khớp planning (S1..SN): số section == planning.json, ghép lại đúng script, `strip_minimax_tags(minimax-prompt.txt)` == `script.txt` (gen MiniMax 1 lần, không chia chunk).
- Chiều dài tối thiểu: `non_whitespace_chars(script)` ≥ `389 × phút mục tiêu` (pipeline đếm lại bằng code, ghi đè số của Gemini vào `char_report.verified_chars_by_code`).
- Thumbnail copy 4–8 ký tự, hard max 11, overlap title ≤35%, contrast ≥7:1.
- Số ảnh được tính động theo nội dung: mỗi beat `new_image=true` có đúng một prompt; beat reuse dùng đúng image ID đã gán.
- Storyboard có đúng một event cho mỗi visual beat; `events/image` chỉ là metric tham khảo, không phải quota cố định.
- Mọi prompt self-contained và có `16:9`, watercolor style, `Negative:`.
- Không bịa timeline/chapters.

Các phép đo ký tự, title length, contrast, section round-trip và prompt count phải chạy bằng code; không để LLM tự khai PASS.

## Output

```text
runs/<run_id>/
├── research/
├── script/
│   ├── script.txt           # script sạch cuối (strip tag) — bản đối chiếu, không phải input dựng video
│   ├── script-vi.txt        # bản dịch tiếng Việt (stage translate_script_vi) CHỈ để đọc duyệt — không dùng cho TTS
│   ├── sections.json        # mốc section khớp planning (S1..SN) cho timeline/video_build
│   ├── psychology-format-check.json  # 7 metrics 0–10 + gate gợi ý chưa calibrate (Sprint 6)
│   ├── review-report.json   # review v9 + char_report (pipeline đếm lại bằng code)
│   ├── pause-map.json       # điểm nghỉ tham khảo khi gen/dựng
│   └── minimax-prompt.txt   # toàn bộ script — gen MiniMax 1 lần từ file này
├── audio/            # bỏ 1 file audio GHÉP toàn bộ video vào đây (timeline tính động lúc Dựng → FINAL_TIMING nếu đo được)
├── thumbnail/
├── visuals/
│   └── prompts/      # prompts-ALL.txt — gen ảnh theo đúng thứ tự này
├── publish/
├── qa/
├── video-build/      # pack sinh khi bấm Dựng (web) hoặc chạy build_service --prepare-only
│   ├── prompts-build.py   # mọi event kể cả reuse — từ timeline tính động
│   ├── marks.tsv
│   ├── audio/             # cắt theo mốc section (1 file/section)
│   ├── images/            # IMG-xx đầy đủ — bỏ ảnh đã gen vào đây (hoặc Import ảnh trên web)
│   ├── import/            # thư mục trung gian cho Import ảnh (--import-images)
│   ├── srt/               # copy từ subtitles/ — chỗ build-video.py --subtitles burn
│   └── build-report.json  # WAITING_AUDIO/WAITING_IMAGES/PACK_READY + thiếu gì
├── subtitles/             # bỏ *.srt vào đây (tùy chọn) — build_service copy vào pack
├── resource_manifest.json
└── run_state.json
```

Resource pack chỉ hoàn thành khi manifest không thiếu artifact. Bàn giao checklist:

1. Đọc `script/review-report.json`: score_report (3 mục /10 → /100), `char_report` (pipeline đếm lại bằng code — `verified_chars_by_code` ≥ ngưỡng tối thiểu), tts_ready/restructure map — duyệt bản tái cấu trúc rule v9 trước khi gen.
1b. Đọc `script/psychology-format-check.json`: 7 metrics 0–10 (psychological_identity, behavioral_density, mechanism_depth, self_recognition, insight_density, reframe_signature, narrative_contamination) + gate gợi ý CHƯA calibrate — ghi lại giá trị + generic_selfhelp findings để đối chiếu intro_retention/average_view_duration sau publish (Sprint 6).
2. Gen MiniMax MỘT lần từ `script/minimax-prompt.txt` (bản có tag `<#x#>`) với profile đã khóa (không chia chunk, không ghép); `script.txt` sạch dùng làm bản đối chiếu.
3. Đo duration/CPM thật; bỏ 1 file audio ghép toàn bộ video vào `audio/` (không cần resume — timeline tính động lúc Dựng; có audio → FINAL_TIMING).
4. Gen thumbnail/ảnh từ prompt pack.
5. Bỏ ảnh đã gen (đúng thứ tự `prompts-ALL.txt`, tên `IMG-xx`) vào `video-build/images/`; thiếu gì sẽ báo trên web tab Dựng video / trong `video-build/build-report.json` (WAITING_AUDIO / WAITING_IMAGES + ID thiếu). Đủ → bấm Dựng video trên web, hoặc chạy tay: `.venv/bin/python -m youtube_pipeline.build_service runs/<run_id> --prepare-only` rồi render (`--animation … --transition … --resolution … [--subtitles] [--dry-run]`) — engine `youtube_pipeline/build-video.py` ráp `video-final.mp4`. SRT tùy chọn từ `subtitles/`. Không tự ráp.

## Out of scope Phase 1

- Gọi MiniMax API.
- Gen ảnh thật.
- Render thumbnail thật.
- Forced alignment/SRT final.
- Upload YouTube.
