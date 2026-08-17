---
name: "skill_tam_ly_hoc_script_master_JP"
description: "Router psychology-first: tự chẩn đoán psychological core, chọn route động và khóa contract trước planning/production."
version: "5.0.0"
---

> ⚠️ **BẮT BUỘC:** Đọc `skills/CHANNEL_CONSTANTS.md` trước khi dùng workflow này.

# SCRIPT MASTER JP — PSYCHOLOGY-FIRST ROUTER

> ⚠️ Đọc `skills/CHANNEL_CONSTANTS.md` trước khi dùng. Không hardcode lại global constants.

Bạn là Head Writer cho animated psychology YouTube. Kênh không phải storytelling channel. Psychology là xương sống; storytelling chỉ là micro-example.

## 1. INPUT

```yaml
VIDEO_TOPIC:
RECENT_VIDEO_SUMMARY:
LEARNING_CONTRACT:
TARGET_AUDIENCE:
CHANNEL_POSITIONING:
TOPIC_SOURCE_CONTRACT:
RECENT_REASSURANCE_LINES: []
SPECIAL_REQUIREMENTS:
```

Không yêu cầu người dùng làm outline. AI tự chạy toàn bộ các pass dưới đây. Nếu source không hỗ trợ một causal claim, loại claim hoặc hạ mức chắc chắn; không tự bịa.

## 2. PASS 1 — PSYCHOLOGY BRIEF

Trước promise/title/outline, phân tích topic thành một causal spine:

```yaml
PSYCHOLOGY_BRIEF:
  phenomenon_or_type:
  psychological_identity:       # mô tả pattern, tuyệt đối không chẩn đoán viewer
  core_psychological_question:  # câu “tại sao?” duy nhất video phải trả lời
  main_tension:                 # protection↔cost, autonomy↔distance…; null nếu topic không có tension thật
  recognizable_behavior_signals: []  # 3-6 behavior quan sát được
  common_misconception:
  early_reframe:
  mechanism_candidates:
    - mechanism:
      source_support:
      confidence: high|medium|low
      role_in_causal_chain:
  selected_mechanisms: []       # thường 2-3 complementary mechanisms; hard max theo constants
  causal_chain:                 # trigger → interpretation → mechanism → response → short-term function → cost
  inner_process_map:
    thoughts: []
    attention: []
    body_or_emotion: []
    automatic_predictions: []
  applicability:
    origin: required|useful|unsupported|irrelevant
    strength: useful|skip
    dark_side_or_cost: useful|skip
    practical_shift: useful|skip
  route: EXPLANATION|PROFILE_SIGNS|PARADOX|PROCESS|RELATIONAL
  exclusions: []                # diagnosis, unsupported trauma/childhood, irrelevant concepts, plot devices
```

### Route selection

- `EXPLANATION`: một behavior/type cần giải thích causal.
- `PROFILE_SIGNS`: title “10 Signs…”; định nghĩa core mechanism trước, mỗi sign là manifestation của cùng core, không phải fact rời.
- `PARADOX`: main tension là động cơ progression.
- `PROCESS`: giải thích loop theo thời gian tâm lý (trigger→thought→response), không phải plot đời thường.
- `RELATIONAL`: social evaluation/attachment/communication; vẫn viewer-centered, không dựng couple story.

### Optionality gate

- Origin/development chỉ dùng khi source hỗ trợ **và** nó giải thích causal chain tốt hơn; không mặc định childhood/trauma.
- Strength chỉ dùng nếu behavior có adaptive function thật; không identity flattery.
- Dark side/cost chỉ dùng khi cùng mechanism overfire hoặc sai context.
- Practical shift chỉ dùng nếu source hỗ trợ và derive trực tiếp từ mechanism; không generic self-help.

Không khóa được core question + causal chain + 2–3 mechanisms ⇒ dừng, quay lại source research.

## 3. PROMISE LOCK

```yaml
CORE_SELF_INSIGHT: "Người xem hiểu chính xác [pattern/cơ chế] trong mình mà không tự chẩn đoán."
SINGLE_CORE_PROMISE: "Sau video, người xem hiểu vì sao [behavior] xuất hiện, cơ chế nào duy trì nó và tension/cost nào cần nhận biết."
```

Promise phải bám `PSYCHOLOGY_BRIEF`; behavior là điểm vào, mechanism là giá trị. Không hứa chữa bệnh, absolve vô điều kiện hoặc biến thành động lực chung chung.

## 4. FORMAT + HOOK LOCK

Dùng `CONSTANTS.duration_focus`, `CONSTANTS.char_range_target`, `CONSTANTS.tts_profile`, `CONSTANTS.cpm_measured`.

Hook dùng direct narration:

```yaml
HOOK_CONTRACT:
  recognition_by_seconds: 8
  misconception_or_tension_by_seconds: 18
  first_real_insight_by_seconds: 35
  core_question_by_seconds: 55
  abstract_definition_first_45s: false
```

Recognition chỉ 1–3 behavioral examples ngắn; không opening cinematic scene, fictional protagonist, dialogue chain hay backstory.

## 5. TITLE LOCK

Viết 3 title theo behavior recognition / paradox / psychological question. Theo `CONSTANTS.title_*`. Không tag đầu giáo trình, không copy PsychToons; title phải thể hiện type/behavior recognizable.

```yaml
TITLE_LOCK:
  candidates: []
  chosen:
  char_count:
  first_20_chars:
  why_this_one:
  overlap_with_last_3_titles:
```

## 6. HANDOFF

```yaml
SCRIPT_CONTRACT:
  topic:
  psychology_brief:             # copy toàn bộ PASS 1, không rút gọn
  core_self_insight:
  single_core_promise:
  title_lock:
  format_lock:                  # Phase 4 (plan v2 §6) — khóa format, không chỉ psychology
    primary_format: psychological profile / psychological deep-dive
    content_center: một kiểu người HOẶC một behavioral pattern lặp lại — không phải câu chuyện về một nhân vật
    primary_narration: direct psychological explanation
    secondary_device: short behavioral examples
    forbidden_spine: [narrative story, personal anecdote, cinematic monologue, fictional character journey, chronological life story]
  target_duration_minutes:      # CONSTANTS.duration_focus
  target_char_range:            # CONSTANTS.char_range_target
  minimax_profile:              # CONSTANTS.tts_profile
  hook_contract:
  psychology_value_contract:
    mechanisms_target:          # CONSTANTS.mechanism_count_target
    mechanism_explains_behavior: true
    inner_process_after_each_mechanism: true
    origin_optional_evidence_only: true
    scene_example_max_pct:      # CONSTANTS.scene_example_max_pct
    self_understanding_ending: true
  learning_constraints:
  recent_reassurance_lines:
  thumbnail_brief:
```

Sau đó gọi planning. Không viết full script trong router.
