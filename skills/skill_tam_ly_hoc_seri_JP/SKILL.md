---
name: "skill_tam_ly_hoc_seri_JP"
description: "Điều phối series video tâm lý học tiếng Nhật theo dữ liệu thực tế; chọn topic thích nghi, kiểm tra khoảng cách với video trước và truyền LEARNING_CONTRACT xuyên suốt pipeline."
---

> ⚠️ BẮT BUỘC: Đọc `skills/CHANNEL_CONSTANTS.md` trước khi dùng skill này.
> Mọi giá trị global reference qua key `CONSTANTS.<key>`. Không hardcode số.
> Nếu không đọc được file đó, dừng lại — không tự đoán.

# SERI JP — ADAPTIVE CONTENT OS

> Phiên bản 4.0.0 — cập nhật 2026-08-01 (sau khi có CTR thật).
> Lưu ý 2026-08-17: `tam-ly-hoc-full-video-master-jp` hiện KHÔNG gọi skill này; mục 8 là dữ liệu lịch sử — policy hiện hành ở `skills/CHANNEL_CONSTANTS.md`.

Bạn là Content Strategist điều phối toàn bộ series. Không khóa cứng 12 video và không ép mọi chủ đề thành 25–30 phút.

## 1. NGUYÊN TẮC

- Giữ audience cốt lõi: người Nhật 35–65 tuổi, hướng nội/nhạy cảm, dễ kiệt sức vì giao tiếp và kỳ vọng xã hội.
- Giữ lời hứa kênh: giúp người xem hiểu cơ chế tâm lý để bớt tự trách và sống nhẹ hơn.
- Mỗi video phải có một tình huống đời sống cụ thể, một câu hỏi rõ và một payoff thực sự.
- **Pillar rộng vừa đủ, định vị video phải hẹp.** Pillar `人間関係で疲れる` được phép rộng để chứa nhiều tình huống, nhưng MỖI video phải hẹp về đúng một cảm xúc trung tâm và một câu lõi. Không chọn topic chỉ vì "nằm trong pillar".
- Series phải học từ dữ liệu video trước. Nếu có metrics, bắt buộc gọi/áp dụng `skill_tam_ly_hoc_performance_review_JP`.

## 1b. BRAND CONSISTENCY — NGUỒN CHUẨN (áp dụng cho MỌI skill sau)

Đây là bản sắc kênh, truyền xuống mọi bước (script → thumbnail → image → description). Mọi skill con phải tôn trọng; nếu lệch, sửa theo bản này.

```yaml
BRAND_BIBLE:
  mood: "thấu hiểu · nhẹ · KHÔNG phán xét"      # tông cảm xúc xuyên suốt, không đổi mạnh giữa các video
  promise_feeling: "được gọi đúng nỗi đau"        # cảm giác người xem phải có: kênh hiểu chính xác điều họ chưa nói ra
  voice: "trưởng thành, ấm, điềm tĩnh; xưng hô nhất quán; không giảng đạo, không cường điệu"
  mascot: "Kokoro Shizuku — mascot hỗ trợ mood, KHÔNG chiếm trọng tâm mọi khung"
  palette: "muted slate-blue/khaki/cream — 2D cartoon illustration (→ xem: CONSTANTS.image_style_lock); cream-mint chỉ dành cho Kokoro Shizuku khi mascot xuất hiện"
  emotional_rhythm: "nhận diện → căng nhẹ → hiểu → nhẹ nhõm; không giật cảm xúc, không kịch tính hoá"
```

**Quy tắc:**

- Giữ MỘT mood xuyên suốt cả kênh. Không đổi tông đột ngột giữa các video (không lúc chữa lành, lúc giật gân).
- Mascot, màu sắc, cách xưng hô, nhịp cảm xúc phải tương thích nhau và nhất quán qua các video.
- Mọi video phải để lại cảm giác `promise_feeling` — "được gọi đúng nỗi đau". Nếu một lựa chọn (title/thumbnail/hook) mạnh về click nhưng phá cảm giác này ⇒ loại.
- Khi có mâu thuẫn giữa "câu view" và "giữ mood", ưu tiên giữ mood — kênh sống bằng lòng tin, không bằng cú sốc.

## 2. INPUT

```yaml
CHANNEL_CONTEXT:
  channel_name:
  audience:
  recent_videos:
  performance_metrics:
  learning_contract:
  requested_topic:
  special_requirements:
```

**Nguồn topic mặc định:** lấy theo thứ tự từ `content/video-queue.md` (kho cơ chế: `content/mechanisms.md`; chất liệu văn hóa: `content/cultural-frames-jp.md`). Nếu có `requested_topic` từ người dùng thì ưu tiên topic đó nhưng vẫn chạy NICHE CORE GATE bình thường. Cơ chế gợi ý trong queue chỉ là gợi ý — chốt thật sau khi chạy gate `mechanism_diversity` (mục 9c) với lịch sử đăng thật.

Nếu đã có `LEARNING_CONTRACT`, dùng nguyên văn; không tự làm mềm các constraint.

## 3. NICHE CORE GATE — CỔNG LÕI NGÁCH (chạy TRƯỚC Topic Distance)

Ngách vận hành bằng HAI LAYER. Đừng trộn chúng: một cái để *quan sát*, một cái để *quyết định*.

**Layer 1 — 6 content clusters (chỉ để quan sát).** Dùng để nhìn phân bố topic (nhánh nào dày/mỏng) khi lên kế hoạch. KHÔNG dùng để gác cổng, KHÔNG quyết định pass/reject.

```yaml
CONTENT_CLUSTERS:   # chỉ mô tả phân bố, không phải bộ lọc
  - kiet_suc_sau_giao_tiep
  - ne_tranh_nhe_nhom
  - im_lang_khoang_trong
  - giao_tiep_digital
  - thoi_quen_mot_minh
  - nhai_lai_cam_xuc
```

**Layer 2 — 3 core filters (dùng để quyết định).** Đây là bộ lọc thật sự trả lời: topic mới có THUỘC ngách không.

```yaml
NICHE_CORES:
  kiet_suc:  "kiệt sức — dồn năng lượng cho tương tác rồi sụp (外で気を張る, 会ったあと疲れる, 家に帰ると動けない)"
  ne_tranh:  "né tránh & nhẹ nhõm khi thoát tương tác (予定キャンセルでホッと, 断れない, 返信を先延ばし)"
  nhai_lai:  "nhai lại — day dứt/tua lại một tương tác đã qua (一言を引きずる, 既読の言葉選び, 後悔)"
```

**Câu lõi bắt buộc.** Trước khi lọc, mỗi topic phải trả lời được đúng một câu:

> "Video này giúp người mệt vì quan hệ con người hiểu gì về chính mình?"

**Mapping rule (quy tắc quyết định):**

- Mỗi topic map **ít nhất 1 core** trong Layer 2 (tối đa 3 — không giới hạn cứng). Membership chỉ cần chạm ≥1 lõi là thuộc ngách.
- Phải chỉ ra đúng **1 `primary_core`** — lõi trục để định vị video. Đây là chỗ giữ định vị sắc, KHÔNG phải bằng cách hạn chế số core.
- Nếu **không map được core nào rõ ràng** ⇒ REJECT (kể cả khi nghe "có vẻ hợp pillar").
- Nếu **cluster (Layer 1) và core (Layer 2) lệch nhau, ưu tiên CORE để quyết định.** Cluster chỉ là nơi topic tình cờ rơi vào về mặt tình huống; core mới là cái xác định nó thuộc ngách.
- Cảm xúc trung tâm phải SẮC (một cụm cụ thể). Cảm xúc loãng/mơ hồ ⇒ REJECT.

Xuất kết quả gate:

```yaml
NICHE_CORE_RESULT:
  core_question_answer:      # câu trả lời cụ thể cho "hiểu gì về chính mình"
  cores_touched: []          # >=1 trong [kiet_suc, ne_tranh, nhai_lai]
  primary_core:              # đúng 1 lõi trục để định vị video
  observed_cluster:          # 1 trong 6 cluster — chỉ để ghi nhận phân bố
  central_emotion:           # một cụm cảm xúc sắc, không mơ hồ
  verdict: PASS|REJECT|DEFER
```

## 4. TOPIC DISTANCE GATE

So sánh topic mới với 3 video gần nhất theo 4 chiều:

1. `trigger_situation` — tình huống kích hoạt.
2. `central_emotion` — cảm xúc trung tâm.
3. `promised_explanation` — lời giải thích được hứa.
4. `thumbnail_conflict` — xung đột hình ảnh.

Topic mới phải có ít nhất 2 chiều mới. Nếu trùng từ 3/4 chiều trở lên, KHÔNG làm ngay — chọn một trong hai:

- **DROP:** bỏ hẳn nếu topic vốn yếu hoặc đã có video gần như y hệt.
- **DEFER:** giữ lại, đẩy ra sau ≥3 video để khoảng cách đủ xa rồi làm lại. Dùng khi topic tốt nhưng chỉ đang bị kẹt gần một video vừa đăng.

Ghi rõ `distance_verdict: OK | DROP | DEFER` (kèm lý do nếu DEFER) vào `SERIES_DECISION`.

## 5. NHỊP NHÁNH DÀY / NHÁNH MỎNG

- Mỗi tuần nên có ít nhất 1 topic thuộc **nhánh dày** (kiệt sức sau giao tiếp, né tránh & nhẹ nhõm) để giữ nhịp và giúp YouTube đóng đinh ngách.
- Chỉ thử **nhánh mỏng / mới** (giao tiếp digital, nhai lại, mở rộng ngoài 3 lõi) khi có lý do rõ ràng để mở rộng — ví dụ data cho thấy nhánh dày đã bão hòa hoặc có tín hiệu cầu từ search/comment.
- Cân bằng: giữ nhịp nhánh dày là mặc định; mở nhánh mỏng là quyết định có chủ đích, ghi lý do vào `SERIES_DECISION`.

## 6. TOPIC SCORE — 100 ĐIỂM

```yaml
TOPIC_SCORE:
  instant_recognition: 15
  concrete_life_scene: 15
  contradiction_or_tension: 15
  clear_question: 15
  two_non_overlapping_insights: 10
  practical_or_emotional_payoff: 10
  thumbnail_visual_potential: 10
  distance_from_recent_videos: 10
```

Không cộng điểm vì "có thể kéo dài 25–30 phút".

## 7. CHỌN FORMAT THEO CHẤT LIỆU

```yaml
FORMAT_MODES:
  focus:    # → xem: CONSTANTS.duration_focus — một hành vi, một cơ chế chính
  standard: # → xem: CONSTANTS.duration_standard — 2–3 cơ chế và ứng dụng (chỉ sau upgrade gate)
  # deep_dive: REMOVED — xem CONSTANTS.format_deep_dive
```

Upgrade gate standard: → xem: CONSTANTS.upgrade_gate_retention_30s_pct và CONSTANTS.upgrade_gate_consecutive_videos.
Chỉ dùng format standard sau khi đạt upgrade gate. Format deep_dive đã bị loại bỏ.

## 8. BASELINE CHO VIDEO TIẾP THEO (cập nhật 2026-08-01 — sau khi có CTR thật)

> **HISTORICAL — dữ liệu chốt 2026-08-01 (V1–V3).** Đọc để hiểu bối cảnh thí nghiệm packaging, không dùng làm policy hiện hành. Policy hiện hành ở `skills/CHANNEL_CONSTANTS.md` + `tam-ly-hoc-full-video-master-jp`. (Master hiện tại KHÔNG gọi skill seri này.)

**Đọc trước:** nút thắt hiện hành là `PACKAGING` (title + thumbnail), KHÔNG phải topic. Chi tiết ở `skill_tam_ly_hoc_performance_review_JP` mục 6. Hệ quả với skill này: **đừng tìm cách cứu kênh bằng cách chọn topic hay hơn.** V1 và V2 đã được YouTube cấp ~5.400 impressions suggested; topic không phải chỗ hỏng — người ta không bấm vào.

- Giữ nguyên hướng topic: chọn tình huống cụ thể khác nhưng cùng audience, không lặp "mệt sau khi gặp người".
- Ưu tiên topic: `外では平気なのに、家に帰ると何もできなくなる理由` (lưu ý: V3 đã dùng góc này — nếu làm lại phải đổi tình huống kích hoạt).
- Format: `focus` — → xem CONSTANTS.duration_focus (standard chỉ sau upgrade gate).
- Hook: nhận diện ≤8s, contradiction ≤18s, insight đầu ≤35s, open loop ≤55s.
- **Ràng buộc mới:** video kế tiếp chỉ được thay đổi MỘT biến — title + thumbnail theo chuẩn TV-first. Giữ nguyên độ dài, hook contract, cấu trúc. Đổi nhiều thứ cùng lúc thì lại không biết cái gì có tác dụng.
- **Impressions chỉ sinh ra khi ĐĂNG — đừng chờ.** Số liệu: V1 nhận 2.762/3.515 impressions (79%) ngay trong ngày đăng; V2 nhận 1.434/2.083 (69%). Video cũ sau đó chỉ nhỏ giọt ~80 imp/ngày cho cả kênh. Cỡ mẫu cần để biết một thumbnail có thật sự tốt hơn (2,8% → 4,5%) là ~1.900 impressions ⇒ chỉ cú seed ngày đăng mới cấp đủ. Sửa thumbnail video cũ KHÔNG phải là thí nghiệm khả thi: mất 25-38 ngày mới đọc được kết quả.
- **Cú seed đang teo:** 2.762 → 1.434 → 92 qua ba video. Khoảng nghỉ dài làm seed nhỏ thêm, tức là mỗi tuần trì hoãn thì thí nghiệm kế tiếp lại kém tin cậy hơn. Nhịp đăng đều là điều kiện để HỌC, không chỉ để tăng trưởng.

## 9. PIPELINE CHUẨN

```text
PERFORMANCE_REVIEW
→ SERI/TOPIC_STRATEGY
→ SCRIPT_MASTER
→ SCRIPT_PLANNING
→ SCRIPT_PRODUCTION
→ THUMBNAIL
→ IMAGE_MASTER
→ IMAGE_PRODUCTION
→ DESCRIPTION
→ PUBLISH
→ PERFORMANCE_REVIEW
```

## 9b. PRODUCTION GUARDRAILS — CỔNG THỨ TỰ (bắt buộc)

Không được làm bước sau khi bước trước chưa xong. Đây là cổng chặn, không phải gợi ý:

- **Không viết script khi chưa chốt `SINGLE_CORE_PROMISE`.** Promise chưa khoá ⇒ không planning, không production.
- **Không làm thumbnail khi chưa biết hook.** Thumbnail phải nối với `OPENING_HOOK_EXCERPT`; chưa có hook thật ⇒ chưa làm thumbnail.
- **Không làm hình khi chưa xong cấu trúc retention.** Image chỉ chạy sau khi `PLANNING_OUTPUT` (retention blueprint + information gain map) đã đạt gate.
- **Cấm auto-chain:** chạy MỘT skill MỘT LẦN, sau mỗi bước DỪNG chờ xác nhận, trừ khi người dùng nói rõ muốn chạy liền cả pipeline trong lượt đó.

## 9c. PRE-PUBLISH CHECKLIST — MỖI VIDEO PHẢI QUA TRƯỚC KHI ĐĂNG

Không xuất bản nếu title, thumbnail, opening và script CHƯA cùng một hướng. Chạy checklist:

```yaml
PRE_PUBLISH_CHECKLIST:
  promise_locked:              # SINGLE_CORE_PROMISE rõ, hẹp, khớp niche core
  alignment_4way:              # title ↔ thumbnail ↔ opening ↔ script CÙNG một promise/hướng
  hook_contract_passed:        # nhận diện ≤8s, nghịch lý ≤18s, insight ≤35s, open loop ≤55s
  title_from_lock:             # title đúng TITLE_LOCK.chosen, ≤28 ký tự, không tag đầu, không đuôi giáo trình
  title_first20_works:         # 20 ký tự đầu tự nó kéo được click (phần sau bị TV cắt)
  thumbnail_tv_readable:       # qua SQUINT TEST 128×72 + tương phản ≥7:1 (thumbnail skill mục 4a)
  thumbnail_contrast_anchor:   # có ít nhất 1 trong 3 điểm neo tương phản (thumbnail skill mục 8)
  title_thumbnail_complement:  # bổ sung nhau, overlap ≤35% (không nói cùng ý)
  brand_consistency:           # khớp BRAND_BIBLE (mood, mascot, palette, promise_feeling)
  audio_timestamps_real:       # chapters/timeline theo audio thật, không DRAFT khi đăng
  next_video_link:             # đã dán link video kế (nếu có) vào mô tả
  channel_name_correct:        # đúng tên kênh tại thời điểm đăng
  thumbnail_history_logged:    # đã ghi THUMBNAIL_HISTORY_ENTRY để đối chiếu CTR sau 7 ngày
  no_self_watch:               # KHÔNG tự xem video mình khi đang đăng nhập tài khoản kênh
  caption_uploaded:            # → xem: CONSTANTS.caption_upload_required — phải upload trước khi đăng
  publish_time_correct:        # đăng đúng CONSTANTS.publish_time_utc UTC = CONSTANTS.publish_time_jst JST
  mechanism_diversity:         # không dùng cùng cơ chế trong CONSTANTS.mechanism_diversity_window video liên tiếp
```

Bất kỳ dòng nào FAIL ⇒ chưa đăng, quay lại sửa.

**Về `no_self_watch`:** data 2026-08-01 cho thấy 26–100% views của mỗi video là traffic tự-gây (nguồn YT_CHANNEL/PLAYLIST, 6–9 giây/view). Nó kéo tụt average view duration — chính chỉ số YouTube dùng để quyết định có phát tán tiếp không. Muốn kiểm tra video sau khi đăng thì dùng chế độ ẩn danh hoặc tài khoản khác.

## 10. OUTPUT

```yaml
SERIES_DECISION:
  selected_topic:
  japanese_working_title:
  audience_moment:
  central_question:
  single_core_promise:
  niche_core_result:        # từ mục 3: core_question_answer, cores_touched, primary_core, central_emotion, verdict
  cluster_and_density:      # nhánh dày hay mỏng; nếu mỏng, ghi lý do mở rộng
  topic_distance_result:    # 4 chiều + distance_verdict: OK|DROP|DEFER (lý do nếu DEFER)
  topic_score:
  format_mode:
  target_duration_minutes:  # → xem: CONSTANTS.duration_focus hoặc CONSTANTS.duration_standard
  test_hypothesis:
  brand_consistency_check:  # topic/tông này có khớp BRAND_BIBLE (mood, mascot, promise_feeling) không
  required_learning_constraints: []
  mechanism_used:           # cơ chế tâm lý dùng trong video này — theo dõi để enforce mechanism_diversity
  handoff_to_script_master:
```

Không yêu cầu người dùng duyệt từng bước nếu họ đã yêu cầu chạy tự động từ đầu đến cuối.

