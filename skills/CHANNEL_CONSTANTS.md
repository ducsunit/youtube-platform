# CHANNEL CONSTANTS — こころ包み

**Psychology-First Adaptive Workflow — single source of truth.**
Nguồn duy nhất cho các quy tắc global. Skill phải đọc file này trước khi chạy; không hardcode lại giá trị đã có key.

## COMPATIBILITY: CHANNEL-WIDE CONSTANTS

Các key sau được các skill không thuộc script workflow dùng chung; giữ tại đây để mọi
`CONSTANTS.*` reference resolve về một nguồn duy nhất.

```yaml
duration_standard: "35-45 phút; chỉ mở tới 55 phút khi revelation/source thực sự đủ"
format_deep_dive: REMOVED
upgrade_gate_retention_30s_pct: 70
upgrade_gate_consecutive_videos: 3
mechanism_diversity_window: 3
image_style_lock: "high-contrast black-and-off-white ink tableau, thick brush outline, sparse silhouettes, one controlled lemon-gold #FFE500 accent; thumbnail uses a bold symbolic transformation rather than a literal room scene"
image_character_bible: "→ xem CHARACTER_BIBLE trong youtube_pipeline/resource_prompts.py"
image_environment_bible: "minimal ink-drawn symbolic environment on off-white paper; one high-contrast visual metaphor"
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
duration_focus: "35-45 phút, không kéo dài bằng filler; tối đa 55 phút khi đủ revelation"
char_range_target: "13600-17500"
char_range_absolute: "11500-21500"
cpm_measured: 389
cpm_range: "380-400"
tts_profile: {speed: 1.02, pitch: -1, volume: 1.02}
sections_count_range: "5-7, dynamic"
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
script_spine: "sensory recognition → identity tension → symbolic reframe → one core question → 1-2 source-backed mechanisms → escalating revelations/implications → reflective landing"
mechanism_count_target: "1-2"
mechanism_count_hard_max: 2
behavior_signals_range: "3-6"
psychology_explanation_min_pct: 45
scene_example_max_pct: 45
micro_example_max_sentences: 8
consecutive_scene_sentences_max: 8
dialogue_exchange_max: 2
origin_policy: "optional; only when supported and causally useful"
practical_shift_policy: "optional; only when mechanism-derived and source-supported"
ending_policy: "self-understanding, not generic motivation"
```

### Core phases

1. Sensory recognition — một khoảnh khắc mà viewer cảm được ngay.
2. Identity tension — điều họ tưởng mình biết về bản thân bắt đầu lệch đi.
3. Symbolic reframe + một core question.
4. 1-2 mechanism có nguồn; mỗi mechanism mở một revelation/implication mới.
5. Paradox, reflective self-observation, rồi quiet landing.

### Optional branches

Chỉ chọn khi phù hợp topic và nguồn: origin/development; contradiction; adaptive strength; overuse/dark side; relational misunderstanding; signs/profile expansion; practical shift.

Không có `khuôn 14 bước`, exact 7-part, mandatory origin story, mandatory childhood/trauma, mandatory 3-step solution, triple denial, future vision hay healing sentence.


## PSYCHOLOGY FORMAT REVIEW GATE

`script_audit` là source/editorial gate duy nhất sau khi viết. Các metric chỉ là telemetry; không được biến thành quota cho rewrite.

```yaml
psychology_review_gate:
  target_formats: [symbolic_psychological_narrative]
  blocking_scores:
    psychology_spine_min: 7.0
    mechanism_depth_min: 7.0
    insight_density_min: 6.0
    recognition_min: 6.0
    story_dominance_max: 7.0
    example_dependency_max: 7.0
    reframe_signature_min: 1
  hook:
    max_scene_led_sentences_before_psychology: 2
  rule: "Chỉ sửa khi có defect cụ thể hoặc claim ngoài nguồn; không sửa để nâng metric proxy."
```

## ANTI-STORY GUARDRAILS

```yaml
viewer_is_center: true
fictional_protagonist: "allowed only as an explicitly illustrative, non-factual vignette"
plot_or_character_arc: "allowed when it serves a symbolic psychological revelation, never as research evidence"
scene_continuity_across_sections: "allowed within one bounded vignette"
sequential_story_transitions: "allowed sparingly; each transition must reveal a new implication"
example_rule: "vignette must create recognition, metaphor, or implication; it must not be offered as factual proof"
each_concept_must_answer_why: true
trauma_by_default: forbidden
diagnosis_of_viewer: forbidden
generic_self_help: forbidden
```

Các dấu hiệu phải rewrite: vignette được trình bày như fact, story thay thế toàn bộ mechanism, narrative lặp lại mà không có revelation mới, hoặc kết luận diagnosis/trauma/spiritual certainty ngoài source.

Vignette hợp lệ: `sensory image → identity tension → symbolic observation → source-backed mechanism or clearly marked reflection → implication`.

## TITLE & THUMBNAIL

```yaml
title_target_chars: "32-56"
title_hard_max_chars: 70
title_front_load_chars: 20
title_keywords_jp: "心理学, 心理, 考えすぎ, 人間関係"
thumbnail_copy_target_chars: "6-10"
thumbnail_copy_hard_max_chars: 14
title_thumbnail_overlap_max_pct: 35
contrast_min_ratio: "7:1"
thumbnail_typography: "Noto Sans JP Black (fallback M PLUS 1p ExtraBold); #FFE500 fill, 10-14px black stroke at 1280x720, subtle 3-5px black shadow, tracking -0.03em to -0.06em, usually one line in top 24-30%"
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
