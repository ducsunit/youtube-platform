## CURRENT IMPLEMENTATION STATUS — 2026-08-17

The original V2 plan is the design authority, but the runtime has now added a **blocking semantic
review gate** because deterministic story markers cannot reliably identify a story whose paragraphs
contain psychological commentary.

The current runtime contract is:

```text
Psychology Brief
→ Script Contract
→ Psychological Argument Planning
→ Writing
→ Gemini Semantic Format Review
→ Dual Source/Consistency Audit
→ Deterministic Structure Check
→ Psychology Format Metrics
→ Translation / Sections / Packaging
```

The review stage must return `psychology_scorecard` and `format_alignment`. A script is not considered
format-correct merely because `structure_check` passes.

Blocking semantic thresholds:

```yaml
psychology_spine: >= 7
mechanism_depth: >= 7
insight_density: >= 6
recognition: >= 6
story_dominance: <= 3
example_dependency: <= 3
reframe_signature_count: >= 2
```

These thresholds are **format gates**, not YouTube-performance claims. Performance calibration remains
a separate concern using published analytics.

# Psychology-First Content Engine V2
## Plan cập nhật flow script theo format psychological profile / deep-dive

---

## 1. Mục tiêu

Chuyển content engine từ:

```text
TOPIC
 ↓
PSYCHOLOGY
 ↓
STORY / EXPERIENCE
 ↓
EXPLANATION
 ↓
LESSON
```

sang:

```text
TOPIC
 ↓
PSYCHOLOGICAL PROFILE
 ↓
BEHAVIORAL PATTERNS
 ↓
MISCONCEPTION
 ↓
PSYCHOLOGICAL MECHANISMS
 ↓
INNER COGNITIVE PROCESS
 ↓
PARADOX / CONTRADICTION
 ↓
STRENGTH + OVERUSE
 ↓
RELATIONAL EFFECT
 ↓
REFRAME
 ↓
INSIGHT
```

### Nguyên tắc cốt lõi

> Không phải "làm script ít storytelling hơn", mà là khiến AI ngừng tư duy bằng story ngay từ psychology brief → planning → writing.

Video phải là **psychological analysis về một kiểu người / hành vi / pattern**, không phải câu chuyện về một nhân vật.

---

# 2. Kiến trúc 19 stage hiện tại

Giữ nguyên orchestration:

```text
ingest
→ performance
→ topic_research
→ topic_candidates
→ topic_selection
→ source_lock
→ psychology_brief
→ script_contract
→ planning
→ writing
→ review
→ consistency
→ script_qa
→ structure_check
→ translate_script_vi
→ sections
→ publish_draft
→ resource_pack
```

Không rewrite toàn bộ pipeline.

Chỉ thay đổi semantic content engine và bổ sung format validation.

---

# 3. Phase 1 — Research Pipeline

Giữ nguyên:

```text
ingest
→ performance
→ topic_research
→ topic_candidates
→ topic_selection
→ source_lock
```

## Mục tiêu

Research pipeline trả lời:

> "Nên làm video gì và dựa trên nguồn nào?"

Không cần sửa nếu source locking và topic selection đang hoạt động tốt.

## Output

```text
topic
source_pack
performance_context
competitor_signals
```

---

# 4. Phase 2 — Psychology Blueprint

## Stage

```text
psychology_brief
```

## Thay đổi

Giữ các field hiện tại nhưng mở rộng artifact thành:

```text
PSYCHOLOGY BLUEPRINT

1. psychological_identity
2. behavioral_signature
3. core_question
4. common_misconception
5. psychological_reframe
6. psychological_tension
7. selected_mechanisms[1..3]
8. causal_chain
9. inner_process_map
10. strength
11. overuse
12. relational_dynamic
13. psychological_progression
14. evidence_claims
15. exclusions
```

---

## 4.1 psychological_identity

Xác định rõ:

> Video đang phân tích kiểu người / psychological pattern nào?

Ví dụ:

```text
People who constantly worry about what others think of them.
```

Không viết chung chung:

```text
People who are insecure.
```

---

## 4.2 behavioral_signature

Phải mô tả **behavior**, không chỉ emotion.

Ví dụ:

```text
- monitors facial expressions
- replays conversations
- interprets short replies negatively
- anticipates rejection
- modifies behavior to avoid negative evaluation
- seeks reassurance
```

Không chỉ:

```text
- feels anxious
- feels insecure
```

---

## 4.3 common_misconception

Xác định cách hiểu phổ biến nhưng chưa đủ sâu.

Ví dụ:

```text
Common misconception:
They are simply insecure.

Deeper interpretation:
They may excessively monitor social feedback
and use other people's reactions to regulate their sense of safety.
```

---

## 4.4 psychological_reframe

Phải có một cách nhìn mới:

```text
What looks like insecurity
may actually be excessive self-monitoring.
```

Reframe là thành phần rất quan trọng để tạo "aha moment".

---

## 4.5 selected_mechanisms

Chọn khoảng 1–3 mechanism chính.

Ví dụ:

```text
- fear of negative evaluation
- self-monitoring
- rejection sensitivity
```

Không nhồi quá nhiều thuật ngữ.

---

## 4.6 causal_chain

Mô tả quan hệ nhân quả:

```text
social uncertainty
→ heightened monitoring
→ ambiguous signal detected
→ negative interpretation
→ self-blame
→ reassurance seeking
→ temporary relief
→ stronger monitoring
```

---

## 4.7 inner_process_map

Mô tả diễn biến nhận thức bên trong:

```text
External signal
→ interpretation
→ emotional response
→ prediction
→ self-evaluation
→ behavior
→ reinforcement
```

---

## 4.8 strength / overuse

Luôn kiểm tra:

```text
What is the adaptive strength?
How does it become maladaptive when overused?
```

Ví dụ:

```text
Strength:
social awareness

Overuse:
hypervigilance / excessive self-monitoring
```

---

## 4.9 relational_dynamic

Phân tích pattern ảnh hưởng tới quan hệ như thế nào.

Ví dụ:

```text
They may over-read silence,
seek reassurance,
or change their behavior to maintain harmony.
```

---

# 5. Phase 3 — Psychological Progression

Thêm artifact:

```text
psychological_progression
```

Đây là **script spine**, khác với causal_chain.

## Mục đích

Causal chain:

```text
A → B → C
```

Psychological progression:

> Người xem sẽ lần lượt khám phá điều gì?

Ví dụ:

```text
1. Recognize yourself
2. Recognize the behavioral pattern
3. Question the common explanation
4. Discover mechanism #1
5. Discover mechanism #2
6. Understand the inner process
7. Discover the contradiction
8. Understand the strength
9. See how the strength becomes harmful
10. Reframe the behavior
11. Final psychological insight
```

---

# 6. Phase 4 — Script Contract

## Stage

```text
script_contract
```

Contract phải khóa **format**, không chỉ khóa psychology.

## Primary format

```text
Psychological profile / psychological deep-dive
```

## Content center

```text
A type of person
OR
A recurring behavioral pattern
```

## Primary narration

```text
Direct psychological explanation
```

## Secondary device

```text
Short behavioral examples
```

## Forbidden spine

```text
Narrative story
Personal anecdote
Cinematic monologue
Fictional character journey
Chronological life story
```

---

# 7. Allowed vs forbidden language

## Allowed

```text
Some people...

People who...

You may notice...

They tend to...

This often happens because...

Psychologically...

What looks like X may actually be Y...

```

## Not allowed as the structural spine

```text
One night...

Imagine you're lying in bed...

You walk into the room...

Then she looks at you...

The next morning...

He remembered...

After that...

```

### Important

Không cấm tuyệt đối behavioral examples.

Rule:

> Example được phép. Story progression không được phép.

---

# 8. Viewer psychological journey

Script nên tạo progression:

```text
"That's me."
      ↓
"Why do I do this?"
      ↓
"Oh, that's what's happening psychologically."
      ↓
"I never looked at it that way."
      ↓
"I understand this behavior differently now."
```

Không phải:

```text
"This happened."
      ↓
"I felt bad."
      ↓
"Then I realized..."
```

---

# 9. Phase 5 — Planning

Planner không được bắt đầu bằng:

> "Tạo một scene để hook."

Thay vào đó:

> "Establish psychological recognition."

## Dynamic route

Các module:

```text
PROFILE
SIGNS
MISCONCEPTION
MECHANISM
PROCESS
ORIGIN
PARADOX
STRENGTH
OVERUSE
RELATIONAL
REFRAME
INSIGHT
```

Planner chọn khoảng 6–10 module tùy topic.

Không ép tất cả topic theo một template cố định.

---

## Ví dụ

Topic:

```text
People who always care what others think
```

Route:

```text
PROFILE
→ SIGNS
→ MISCONCEPTION
→ MECHANISM
→ PROCESS
→ PARADOX
→ STRENGTH
→ OVERUSE
→ RELATIONAL
→ REFRAME
→ INSIGHT
```

Topic khác có thể route khác.

---

# 10. Phase 6 — Writing

## Core writer instruction

> Analyze, don't narrate.

Writer phải ưu tiên:

```text
Observation
→ Explanation
→ Mechanism
→ Example
→ Interpretation
```

Không ưu tiên:

```text
Scene
→ Action
→ Emotion
→ Scene
→ Reflection
```

---

# 11. Paragraph-level function

Mỗi paragraph phải thực hiện ít nhất một function:

```text
PROFILE
BEHAVIOR
EXPLANATION
MECHANISM
PROCESS
MISCONCEPTION
PARADOX
STRENGTH
OVERUSE
RELATIONAL
REFRAME
INSIGHT
```

Nếu paragraph không thuộc function nào:

```text
DELETE
```

hoặc:

```text
REWRITE
```

Mục tiêu là giảm các đoạn "văn vẻ nhưng không thêm psychological information".

---

# 12. Phase 7 — Review

Flow:

```text
review
→ consistency
→ script_qa
→ psychology_format_check
→ structure_check
```

Review phải kiểm tra thêm:

```text
FORMAT_ALIGNMENT
```

Reviewer phải phân loại:

```text
A. psychological profile
B. psychology explainer
C. self-help essay
D. personal narrative
E. fictional story
```

Target:

```text
A + B
```

Không được:

```text
D + E
```

---

# 13. Phase 8 — Psychology Format Check

## Stage mới

```text
psychology_format_check
```

Nếu muốn tránh thêm stage runtime, có thể implement trước `structure_check` như một sub-check.

## Metrics

```text
psychological_identity
behavioral_density
mechanism_depth
self_recognition
insight_density
narrative_contamination
```

Ví dụ:

```text
psychological_identity: 9
behavioral_density: 8
mechanism_depth: 9
self_recognition: 9
insight_density: 8
narrative_contamination: 2
```

### Suggested gate

```text
psychological_identity >= 7
behavioral_density >= 7
mechanism_depth >= 7
insight_density >= 7
narrative_contamination <= 3
```

Threshold nên được calibration sau 10–20 video thực tế.

---

# 14. Phase 9 — Upgrade structure_check

## Rule hiện tại

```text
≥3 scene markers
OR
≥8 dialogue markers
```

Giữ lại nhưng chỉ xem đây là:

```text
Surface-level detector
```

Không coi nó là định nghĩa đầy đủ của storytelling.

---

## Semantic detector

Cần đo:

```text
scene/action/temporal progression
VS
behavior/psychology/mechanism/insight
```

Ví dụ:

```text
Scene-heavy:
scene
→ action
→ emotion
→ action
→ memory
→ reaction
```

→ warning / fail.

Trong khi:

```text
Psychology-heavy:
behavior
→ explanation
→ mechanism
→ example
→ interpretation
```

→ pass.

Không hard-code threshold ngay lập tức. Log metric trên 20–30 scripts rồi calibration.

---

# 15. Phase 10 — Psychology Integrity Check

Phải ngăn AI tạo "generic psychology-sounding self-help".

## Bad

```text
You are sensitive.

You care deeply.

You are misunderstood.

You are actually strong.
```

Đây không đủ psychological depth.

## Good

```text
When social evaluation becomes an important source
of perceived safety, ambiguous signals from other people
can receive disproportionate attention.
```

Claim phải có mechanism hoặc evidence phù hợp với source pack.

---

# 16. Phase 11 — Repair

Repair không được chỉ polish câu chữ.

Nếu format alignment thấp:

```text
Identify narrative paragraphs.
→ Convert them into psychological observation,
  behavioral analysis, or mechanism explanation.
→ Preserve useful examples only as short illustrations.
→ Remove chronological story progression.
→ Do not replace one story with another story.
```

---

# 17. Final runtime architecture

```text
RESEARCH
    ↓
ingest
    ↓
performance
    ↓
topic_research
    ↓
topic_candidates
    ↓
topic_selection
    ↓
source_lock
    ↓
PSYCHOLOGY BLUEPRINT
    ↓
psychology_brief
    ↓
SCRIPT CONTRACT
    ↓
script_contract
    ↓
PLANNING
    ↓
planning
    ↓
WRITING
    ↓
writing
    ↓
REVIEW
    ↓
review
    ↓
consistency
    ↓
script_qa
    ↓
PSYCHOLOGY FORMAT CHECK
    ↓
structure_check
    ↓
translate_script_vi
    ↓
sections
    ↓
publish_draft
    ↓
resource_pack
```

---

# 18. Implementation priority

Không sửa tất cả cùng lúc.

## Sprint 1 — Psychology Blueprint

Sửa:

```text
psychology_brief
```

Thêm:

```text
behavioral_signature
common_misconception
psychological_reframe
strength
overuse
relational_dynamic
psychological_progression
```

Priority: **P0**

---

## Sprint 2 — Contract + Planner

Sửa:

```text
script_contract
planning
```

Mục tiêu:

> AI biết video là psychological profile trước khi viết.

Priority: **P0**

---

## Sprint 3 — Writer

Sửa:

```text
writing
```

Core rule:

> Analyze, don't narrate.

Priority: **P0**

---

## Sprint 4 — QA

Thêm:

```text
psychology_format_check
```

và nâng:

```text
structure_check
```

Priority: **P1**

---

## Sprint 5 — Repair

Sửa repair để có khả năng:

```text
structure rewrite
```

thay vì chỉ:

```text
sentence polish
```

Priority: **P1**

---

## Sprint 6 — Calibration

Chạy:

```text
10–20 topics
```

Log:

```text
format_score
mechanism_score
narrative_score
intro_retention
average_view_duration
```

Sau đó mới tinh chỉnh threshold.

Priority: **P2**

---

# 19. Definition of Done

Flow V2 được coi là đạt khi một script:

### Bắt đầu bằng

```text
psychological recognition
```

### Tập trung vào

```text
behavior
→ mechanism
→ inner process
→ contradiction
→ insight
```

### Behavioral examples

Được dùng như:

```text
evidence / illustration
```

không phải:

```text
story progression
```

### Không phụ thuộc vào

```text
character
plot
timeline
scene progression
```

### Người xem cảm thấy

```text
"That's me."
→
"Why?"
→
"Oh, that's the psychology behind it."
```

---

# 20. Core principle

> **The video is not a story about what happens to a person.**
>
> **The video is an explanation of why a type of person behaves, thinks, and reacts in a particular way.**

Story chỉ là minh họa.

Psychology mới là spine.

---

## Expected result

Trước:

```text
SCENE
→ EMOTION
→ EXPERIENCE
→ REFLECTION
→ PSYCHOLOGY
```

Sau:

```text
PSYCHOLOGICAL IDENTITY
→ BEHAVIOR
→ MISCONCEPTION
→ MECHANISM
→ INNER PROCESS
→ PARADOX
→ STRENGTH / OVERUSE
→ RELATIONAL EFFECT
→ REFRAME
→ INSIGHT
```

Mục tiêu của update này không phải "cấm storytelling".

Mục tiêu là:

> **Psychology-first Content Engine V2**
>
> **Analyze, don't narrate.**
