# CHANNEL CONSTANTS — こころ包み

**Psychology-First Adaptive Workflow — single source of truth.**
Nguồn duy nhất cho các quy tắc global. Skill phải đọc file này trước khi chạy; không hardcode lại giá trị đã có key.

## COMPATIBILITY: CHANNEL-WIDE CONSTANTS

Các key sau được các skill không thuộc script workflow dùng chung; giữ tại đây để mọi
`CONSTANTS.*` reference resolve về một nguồn duy nhất.

```yaml
duration_standard: "13-15 phút"
format_deep_dive: REMOVED
upgrade_gate_retention_30s_pct: 70
upgrade_gate_consecutive_videos: 3
mechanism_diversity_window: 3
image_style_lock: "flat illustrated cartoon, thick black outline, solid flat colors, no gradients or realistic shading, navy #1A2332 background"
image_character_bible: "→ xem CHARACTER_BIBLE trong youtube_pipeline/resource_prompts.py"
image_environment_bible: "minimal flat Japanese interior, solid color blocks on navy #1A2332 background"
research_citation_block_required: true
medical_disclaimer: "※本動画は教育・情報提供を目的としたものであり、専門的な医学的助言ではありません。"
tags_count: "9-15"
tags_mix: "broad / long-tail / brand"
brand_tag: "こころ包み"
caption_upload_required: true
publish_time_utc: "12:00"
publish_time_jst: "21:00"
cta_comment_preset_answer_required: true
cta_comment_before_subscribe: true
ctr_target: 4.5
retention_30s_target_pct: 65
retention_60s_target_pct: 50
retention_120s_target_pct: 38
retention_300s_target_pct: 25
avp_target_pct: 20
like_rate_target_pct: 2
visual_events_per_image_min: 1.30
visual_density_curve:
  first_30_seconds: "3-6 giây/event"
  seconds_30_to_90: "5-8 giây/event"
  minutes_1_5_to_5: "7-12 giây/event"
  deep_explanation: "10-18 giây/event"
  emotional_landing: "15-25 giây/event"
tv_share_pct: 69
```

## FORMAT & TTS

```yaml
duration_focus: "9-11 phút"
char_range_target: "3500-4300"
char_range_absolute: "2400-4700"
cpm_measured: 389
cpm_range: "380-400"
tts_profile: {speed: 1.02, pitch: -1, volume: 1.02}
sections_count_range: "6-8, dynamic"
```

## HOOK & VALUE

```yaml
hook_contract:
  recognition_by_seconds: 8
  misconception_or_tension_by_seconds: 18
  first_real_insight_by_seconds: 35
  core_question_by_seconds: 55
  channel_intro_before_60s: false
  abstract_definition_first_45s: false
first_payoff_before_minutes: 5
value_rhythm_window_seconds: "45-90"
no_emotion_only_max_seconds: 45
```

## PSYCHOLOGY-FIRST SCRIPT SPINE

```yaml
script_spine: "behavior recognition → misconception → early reframe/core question → mechanism chain → inner process → adaptive branches → integration → self-understanding insight"
mechanism_count_target: "2-3"
mechanism_count_hard_max: 4
behavior_signals_range: "3-6"
psychology_explanation_min_pct: 55
scene_example_max_pct: 20
micro_example_max_sentences: 3
consecutive_scene_sentences_max: 3
dialogue_exchange_max: 1
origin_policy: "optional; only when supported and causally useful"
practical_shift_policy: "optional; only when mechanism-derived and source-supported"
ending_policy: "self-understanding, not generic motivation"
```

### Core phases

1. Behavior recognition — ngắn, direct-to-viewer.
2. Misconception → early reframe → core psychological question.
3. Mechanism build — mỗi cơ chế nối behavior → why → inner thought/body process → consequence.
4. Integration/self-awareness.
5. Insight landing tạo hiểu chính mình.

### Optional branches

Chỉ chọn khi phù hợp topic và nguồn: origin/development; contradiction; adaptive strength; overuse/dark side; relational misunderstanding; signs/profile expansion; practical shift.

Không có `khuôn 14 bước`, exact 7-part, mandatory origin story, mandatory childhood/trauma, mandatory 3-step solution, triple denial, future vision hay healing sentence.


## PSYCHOLOGY FORMAT REVIEW GATE

`review` là semantic gate chính cho format. `structure_check` chỉ xử lý deterministic anti-story; không được dùng marker count như định nghĩa đầy đủ của storytelling.

```yaml
psychology_review_gate:
  target_formats: [A, B]
  blocking_scores:
    psychology_spine_min: 7.0
    mechanism_depth_min: 7.0
    insight_density_min: 6.0
    recognition_min: 6.0
    story_dominance_max: 3.0
    example_dependency_max: 3.0
    reframe_signature_min: 2
  hook:
    max_scene_led_sentences_before_psychology: 2
  rule: "Nếu score semantic không đạt, review phải revise; không được hạ pass chỉ vì script không có marker scene."
```

## ANTI-STORY GUARDRAILS

```yaml
viewer_is_center: true
fictional_protagonist: forbidden
plot_or_character_arc: forbidden
scene_continuity_across_sections: forbidden
sequential_story_transitions: forbidden
example_rule: "1-3 câu rồi quay ngay về psychological explanation"
each_concept_must_answer_why: true
trauma_by_default: forbidden
diagnosis_of_viewer: forbidden
generic_self_help: forbidden
```

Các dấu hiệu phải rewrite: dựng cửa/phòng/thời tiết; nhân vật có tên; chuỗi “bước vào → nhìn → nhớ lại → sau đó”; dialogue qua lại; flashback; setup-conflict-climax-resolution; một tình huống chiếm nhiều đoạn.

Rewrite thành: `recognizable behavior → direct inner process → mechanism → why → implication`.

## TITLE & THUMBNAIL

```yaml
title_target_chars: "18-24"
title_hard_max_chars: 28
title_front_load_chars: 20
title_keywords_jp: "心理学, 心理, 考えすぎ, 人間関係"
thumbnail_copy_target_chars: "4-8"
thumbnail_copy_hard_max_chars: 11
title_thumbnail_overlap_max_pct: 35
contrast_min_ratio: "7:1"
```

## QA

```yaml
research_min_count: 3
fact_integrity_required: true
no_diagnosis_required: true
psychology_brief_required: true
mechanism_explains_behavior_required: true
inner_process_required: true
main_tension_when_applicable: true
anti_story_check_required: true
self_understanding_ending_required: true
```
