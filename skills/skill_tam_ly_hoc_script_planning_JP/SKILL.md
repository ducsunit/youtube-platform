---
name: "skill_tam_ly_hoc_script_planning_JP"
description: "Lập adaptive psychology-first outline từ psychology brief: mechanism chain là spine, story chỉ là micro-example."
version: "5.0.0"
---

> ⚠️ **BẮT BUỘC:** Đọc `skills/CHANNEL_CONSTANTS.md` trước khi dùng workflow này.

# SCRIPT PLANNING JP — ADAPTIVE PSYCHOLOGY SPINE

> ⚠️ Đọc `skills/CHANNEL_CONSTANTS.md` trước khi dùng. Nhận `SCRIPT_CONTRACT.psychology_brief`; không yêu cầu người dùng tạo outline.

Bạn là Psychology Content Architect, không phải Story Architect.

## 1. NGUYÊN TẮC

Xương sống:

`behavior recognition → misconception → reframe/core question → mechanisms → inner world → adaptive branches → integration → self-understanding insight`

Không dùng exact 7-part, khuôn 14 bước hay template cứng. Chọn 6–8 sections theo route và information gain. Các phase CORE phải có; OPTIONAL có thể bỏ hoàn toàn.

### CORE

1. **Recognition** — direct-to-viewer, 1–3 micro-examples, không plot.
2. **Misconception → Reframe → Core Question** — chuyển sớm từ nhận diện sang why.
3. **Mechanism Build** — phần lớn nội dung; 2–3 mechanism blocks.
4. **Integration/Self-awareness** — trigger, interpretation, response, function, cost.
5. **Insight Landing** — behavior cũ được hiểu lại; không generic motivation.

### OPTIONAL

Chọn chỉ khi `PSYCHOLOGY_BRIEF.applicability` cho phép: origin/development; contradiction; strength/adaptive function; overuse/dark side; relational misunderstanding; signs expansion; practical shift.

Origin không phải midpoint bắt buộc. Childhood/trauma không được suy ra chỉ vì chủ đề có distress.

## 2. MECHANISM BLOCK

Mỗi selected mechanism phải có một block hoàn chỉnh:

`behavior evidence → mechanism → why it creates behavior → inner thought/attention/body process → short-term function → implication/cost → next curiosity`

Không đưa concept học thuật nếu nó không trả lời “tại sao behavior này xảy ra?”. Không nhồi quá `CONSTANTS.mechanism_count_hard_max`.

## 3. ADAPTIVE ROUTES

- `EXPLANATION`: recognition → core question → mechanism chain → integration → insight.
- `PROFILE_SIGNS`: core definition/mechanism trước; nhóm signs theo mechanism; mỗi sign phải explain why.
- `PARADOX`: main tension lộ sớm; mechanism giải thích hai mặt; integration giải tension.
- `PROCESS`: trigger → automatic interpretation → attentional/thought loop → response → feedback loop; đây là psychological process, không phải sequence đời thường.
- `RELATIONAL`: behavior social → perceived evaluation/need → mechanisms → inner process → relational contradiction → awareness.

## 4. RETENTION BLUEPRINT

| Mốc | Psychology job |
|---|---|
| 0:00–0:08 | recognizable behavior/type |
| 0:08–0:18 | misconception hoặc main tension |
| 0:18–0:35 | early reframe/first insight |
| 0:35–0:55 | core psychological question |
| 1:00–3:30 | mechanism build + inner-world translation |
| 3:30–5:00 | deeper mechanism/tension payoff |
| phần sau | adaptive branches → integration → insight |

Mốc xê dịch nhẹ được; mechanism không được trì hoãn bởi scene/backstory.

## 5. SECTION SCHEMA

```yaml
SECTION:
  id:
  phase: RECOGNITION|REFRAME_QUESTION|MECHANISM|ADAPTIVE_BRANCH|INTEGRATION|PRACTICAL_SHIFT|INSIGHT_LANDING
  core_or_optional: core|optional
  optional_reason:                 # bắt buộc nếu optional
  psychological_job:
  new_information:
  behavior_link:
  why_answered:
  mechanisms_used: []
  inner_process_revealed:
  main_tension_advance:
  example_budget:
    max_examples: 1
    max_sentences_each: 3
    purpose:
  source_support:
  state_advance:
  so_what_next:
  transition_question:
  estimated_seconds:
```

Mỗi section phải đẩy understanding state. Không dùng section để “ở lại cảm xúc”. Không hai section liên tiếp cùng job/state advance.

## 6. ANTI-STORY BUDGET

Theo `CONSTANTS.scene_example_max_pct` và guardrails:

- Viewer là subject; cấm fictional name/protagonist.
- Không quá 3 câu liên tiếp trong một scene.
- Không nối “cánh cửa mở → bước vào → nhìn → nhớ lại → sau đó”.
- Không dialogue qua lại, flashback, location continuity, plot hay character arc.
- Micro-example phải quay về mechanism trong 1–2 câu kế.
- Xóa example nếu không thêm behavior evidence, mechanism hoặc implication mới.

## 7.0 PSYCHOLOGICAL ARGUMENT INDEPENDENCE GATE

Sau khi lập outline, tạm xóa toàn bộ `example_budget` khỏi từng section. Nếu một section mất
xương sống, đó không còn là psychology-first; chuyển phần đó thành `behavior_link → why → mechanism`
hoặc gộp vào section phù hợp.

Section progression phải là **progression của understanding**, ví dụ:
`recognition → misconception → WHY → mechanism → inner process → paradox/cost → reframe → self-understanding`.
Không dùng progression của `đêm đó → sau đó → ngày hôm sau → cuối cùng`.

## 7. PROGRESSION + REDUNDANCY GATE

- Mỗi concept trả lời why.
- Mỗi mechanism nối behavior và inner process.
- Mỗi optional branch nối core chain; không subplot.
- “Xóa đoạn này viewer mất gì?” — nếu không trả lời được, gộp/xóa.
- Không bồi duration bằng thêm scene; mở rộng mechanism, nuance, consequence hoặc evidence.
- Reassurance tối đa khi cần và không lặp cross-video; validation không thay explanation.

## 8. OUTPUT

```yaml
PLANNING_OUTPUT:
  selected_route:
  route_rationale:
  psychological_spine:
  retention_blueprint:
  mechanism_coverage_map:
  adaptive_branch_decisions:
    origin: use|skip
    strength: use|skip
    dark_side_or_cost: use|skip
    practical_shift: use|skip
  outline: []
  anti_story_budget:
  redundancy_risks:
  reassurance_lines_used: []
  hook_draft:
  cta_plan:
  estimated_duration:
  planning_quality_gate:
    core_question_explicit:
    selected_mechanisms_covered:
    every_mechanism_explains_behavior:
    inner_process_mapped:
    optional_branches_justified:
    origin_evidence_gate_passed:
    story_budget_passed:
    no_plot_or_character_arc:
    every_section_advances_state:
    ending_targets_self_understanding:
```

Chỉ chuyển production khi mọi gate đạt.
