"""Problem-Solving Format Prompts v2 (8-10 min long-form + 60-90s Shorts)."""
from __future__ import annotations

from .validation import SENSITIVE_CLAIM_MARKERS, VALIDATION_PHRASES_JA

_BANNED_CLAIM_VOCAB = " / ".join(SENSITIVE_CLAIM_MARKERS)

CLAIM_VOCAB_BAN_VI = (
    "TỪ VỰNG BỊ CHẶN THEO MẶT CHỮ: các từ sau KHÔNG được xuất hiện, dù chỉ một lần, "
    "TRỪ KHI chính SOURCE PACK có chứa từ đó: " + _BANNED_CLAIM_VOCAB + ". "
    "Một từ lọt vào là toàn bộ output bị loại và phải chạy lại. "
    'Diễn đạt thay thế cho ý "chuyện này không mới bắt đầu": "đã lặp lại từ rất lâu", '
    '"những lần trước bạn cũng làm vậy", "không phải hôm nay mới thành ra thế" — '
    "giữ được hiệu ứng origin story mà không claim nguyên nhân phát triển/khoa học."
)

CLAIM_VOCAB_BAN_JA = (
    "語彙禁止（文字列一致で検証されます）: SOURCE PACK に含まれていない限り、次の語は一度も"
    "使わないでください: " + _BANNED_CLAIM_VOCAB + "。"
    "一語でも混ざると原稿全体が却下され、書き直しになります。"
    "「これは最近始まったことではありません」の代替表現: 「ずっと前から」"
    "「これまで何度も繰り返してきた場面」「今日はじめてこうなったわけではありません」。"
)

ANTI_STORY_RULES = """ANTI-STORYTELLING GUARDRAILS:
- Viewer và psychological tension là trung tâm.
- Được dùng một anonymous vignette, ordinary object/place và recurring symbol. Có thể quay lại cùng hình ảnh
  khi nghĩa của nó chuyển: recognition → interpretation → implication → landing.
- Không tạo nhân vật có tên, biography, character arc, factual anecdote, dialogue chain, flashback, hoặc chronology
  dùng để tự tạo causal proof.
- Scene không được thay argument. Sau mỗi sensory/symbolic turn phải có psychological interpretation,
  source-bounded mechanism hoặc implication mới.
- Nếu scene chỉ tiếp nối action → emotion → next scene mà không đổi nghĩa tension, cắt scene đó thay vì thêm mood.
"""

# ─────────────────────────────────────────────────────────────
# PSYCHOLOGY BRIEF V2 - Problem-solving: 1 mechanism + 3 tools
# ─────────────────────────────────────────────────────────────

def psychology_brief_v2_prompt(topic_context: str, source_pack: dict, performance: dict) -> str:
    return f"""TOPIC CONTEXT:
{topic_context}

SOURCE PACK:
{source_pack}

PERFORMANCE:
{performance}

{ANTI_STORY_RULES}

{CLAIM_VOCAB_BAN_VI}

Build a PROBLEM-SOLVING psychology model for 8-10 min video.
FORMAT: 1 core mechanism + 3 actionable tools (NO multiple mechanisms).

Return JSON:
{{
  "phenomenon_or_type": "một kiểu người hoặc behavioral pattern lặp lại",
  "psychological_identity": "hệ thống tâm lý đang vận hành, không diagnosis",
  "core_psychological_question": "một câu hỏi WHY mà toàn bộ video phải giải thích",
  "main_tension": "mâu thuẫn tâm lý trung tâm",
  "recognizable_behavior_signals": ["3-6 hành vi cụ thể, không viết thành scene"],
  "common_misconception": "cách người xem thường hiểu sai hoặc tự phán xét behavior này",
  "early_reframe": "cách nhìn psychological thay thế cho misconception",
  "selected_mechanisms": [{{
    "name": "tên mechanism (ví dụ: 課題の分離, シャドウ, 個性化)",
    "role": "core mechanism driving the pattern",
    "behavior_explained": "behavior nào mechanism giải thích",
    "why": "chỉ nêu quan hệ hoặc cơ chế mà source trực tiếp hỗ trợ",
    "inner_process": "mô tả quan sát được hoặc để trống; không tự dựng chuỗi chú ý/đánh giá/cảm xúc",
    "evidence_status": "verified|editorial",
    "source_boundary": "claim nào source trực tiếp hỗ trợ; phần nào chỉ là editorial application"
  }}],
  "actionable_tools": [{{
    "name": "tên tool (ví dụ: Luật 3 giây, Script nói không, Micro-habit 7 ngày)",
    "description": "mô tả ngắn gọn tool này làm gì",
    "script_template": "template/script cụ thể có thể copy-paste",
    "micro_action": "hành động micro cụ thể viewer làm được hôm nay",
    "mechanism_link": "tên mechanism này tool ứng dụng"
  }},
  "editorial_dna": {{
    "audience_pain": "nỗi khó chịu cụ thể mà viewer đang tự nhận ra",
    "behavioral_entry": "một hành vi ngắn dùng để mở video, không phải scene story",
    "contradiction": "mâu thuẫn giữa điều viewer muốn và phản ứng đang xảy ra",
    "emotional_promise": "một self-understanding có giới hạn; không hứa chữa khỏi/thay đổi cuộc đời",
    "memory_line": "một insight viewer nên nhớ sau video, không phải slogan động viên",
    "title_angle": "góc title bám behavior/pain",
    "thumbnail_conflict": "mâu thuẫn thị giác cho thumbnail, không phải cốt truyện"
  }},
  "route": "EXPLANATION|PROFILE_SIGNS|PARADOX|PROCESS|RELATIONAL",
  "exclusions": ["scene-first storytelling", "fictional protagonist", "diagnosis", "unsupported childhood/trauma cause"]
}}

QUALITY CHECK:
1. Chỉ 1 mechanism trong selected_mechanisms.
2. Exact 3 tools trong actionable_tools, mỗi tool có script_template và micro_action.
3. Nếu xóa toàn bộ situation/example, psychology model vẫn đứng vững.
4. Mỗi tool phải link về mechanism duy nhất.
5. Không dùng scene làm causal unit.
6. Không biến practical_shift thành self-help chiếm trung tâm.
"""


# ─────────────────────────────────────────────────────────────
# CONTRACT V2 - 8-10 min Problem-Solving Format Lock
# ─────────────────────────────────────────────────────────────

def contract_v2_prompt(topic: str, source_pack: dict, performance: dict, brief: dict) -> str:
    return f"""TOPIC: {topic}
SOURCE PACK: {source_pack}
PSYCHOLOGY BRIEF: {brief}
PERFORMANCE: {performance}

Lock format for 8-10 min PROBLEM-SOLVING video (4500-6500 chars).

Return JSON:
{{
  "core_self_insight": "memory_line từ brief",
  "central_emotion": "audience_pain từ brief",
  "psychological_identity": "psychological_identity từ brief",
  "core_psychological_question": "core_psychological_question từ brief",
  "main_tension": "main_tension từ brief",
  "route": "route từ brief",
  "selected_mechanisms": ["tên mechanism duy nhất"],
  "single_core_promise": "emotional_promise từ brief",
  "title_candidates": [{{"title": "32-100 Japanese chars", "mechanism": "tên mechanism", "char_count": 0}}],
  "chosen_title": "copy đúng một title candidate",
  "chosen_title_char_count": 0,
  "target_duration_minutes": "8-10",
  "target_char_min": 4500,
  "target_char_max": 6500,
  "hook_contract": {{
    "recognition_by_seconds": 5,
    "misconception_or_tension_by_seconds": 12,
    "first_real_insight_by_seconds": 25,
    "core_question_by_seconds": 40
  }},
  "format_lock": {{
    "primary_format": "problem-solving psychological deep-dive",
    "content_center": "một psychological pattern + 1 mechanism + 3 tools",
    "primary_narration": "symbolic psychological analysis with reflective narration",
    "secondary_device": "3 actionable tools as editorial illustrations",
    "tool_slots": 3,
    "forbidden_spine": ["fictional claim presented as evidence", "chronological character biography", "symbolic scene without psychological advance", "unsupported causal story", "multiple mechanisms"]
  }},
  "content_spine": {{
    "psychological_pattern": "psychological_identity từ brief",
    "core_question": "core_psychological_question từ brief",
    "central_mechanism": "tên mechanism duy nhất",
    "causal_logic": "chỉ dùng source-locked support cho mechanism duy nhất",
    "viewer_self_understanding": "memory_line từ brief"
  }},
  "recognition_device": {{
    "behavioral_signals": "recognizable_behavior_signals từ brief",
    "micro_examples": [],
    "usage_rule": "vignettes create recognition or changed interpretation; never prove factual claim"
  }},
  "packaging_layer": {{
    "title_question": "title_angle từ brief",
    "thumbnail_question": "thumbnail_conflict từ brief",
    "curiosity_gap": "core_psychological_question từ brief",
    "packaging_must_not_become_content_spine": true
  }},
  "tool_slots": [
    {{"slot": 1, "tool_name": "actionable_tools[0].name", "mechanism_link": "actionable_tools[0].mechanism_link"}},
    {{"slot": 2, "tool_name": "actionable_tools[1].name", "mechanism_link": "actionable_tools[1].mechanism_link"}},
    {{"slot": 3, "tool_name": "actionable_tools[2].name", "mechanism_link": "actionable_tools[2].mechanism_link"}}
  ]
}}

FORMAT LOCK RULES:
1. Psychology is the spine. If all tools deleted, argument must still be complete.
2. Exactly 1 mechanism, exactly 3 tools. No more, no less.
3. Tools are editorial illustrations, not separate mechanisms.
4. Hook must pivot to psychological question by 12s, insight by 25s.
5. Every section must answer: mechanism explanation, tool demo, or self-understanding.
6. No chronological story, no character biography, no multiple mechanisms.
""" + CLAIM_VOCAB_BAN_VI


# ─────────────────────────────────────────────────────────────
# SHOT LIST PROMPT - 55 shots mapping
# ─────────────────────────────────────────────────────────────

def shot_list_prompt(script: str, brief: dict, contract: dict) -> str:
    return f"""SCRIPT:
{script}

CONTRACT: {contract}
BRIEF: {brief}

Map script to 55 shots for 8-10 min video.

Shot types:
- character_closeup: face/eyes, lip-sync needed
- character_medium: upper body, lip-sync needed  
- pov_screen: phone/PC screen, text overlay
- metaphor: symbolic visual (ink, shadows, objects)
- environment: room, office, nature

Return JSON:
{{
  "shots": [
    {{
      "shot_id": "SH01",
      "type": "character_closeup",
      "prompt": "visual prompt for ComfyUI",
      "visual_information": "description for animation",
      "duration_sec": 4.5,
      "audio_segment": "seg_01",
      "lip_sync": true,
      "animation_provider": "kling",
      "motion": "subtle breathing, eye movement",
      "text_start": 0,
      "text_end": 120
    }},
    ...
  ]
}}

RULES:
- Total shots: 50-60
- Character shots (lip_sync=true): ~35%
- Total duration: 480-600 seconds
- Audio segments: sequential seg_01, seg_02...
- Text mapping: cover entire script sequentially
"""


# ─────────────────────────────────────────────────────────────
# WRITING V2 - Problem-Solving Script
# ─────────────────────────────────────────────────────────────

def writing_v2_prompt(contract: dict, shot_list: dict, source_pack: dict, brief: dict) -> str:
    return f"""CONTRACT: {contract}
SHOT LIST: {shot_list}
SOURCE PACK: {source_pack}
BRIEF: {brief}

Write 4500-6500 chars Japanese PROBLEM-SOLVING script (8-10 min).

STRUCTURE (follow shot_list timing):
1. HOOK (0-40s): Sensory recognition → Identity tension → Core question
2. MECHANISM (40s-3min): ONE mechanism explanation (what/why/behavior)
3. TOOL 1 (3-5min): Tool 1 demo + script + micro-action
4. TOOL 2 (5-7min): Tool 2 demo + script + micro-action  
5. TOOL 3 (7-9min): Tool 3 demo + script + micro-action
6. LANDING (9-10min): Core reframe → Quiet realization → CTA

{ANTI_STORY_RULES}

STYLE:
- Japanese natural, spoken rhythm
- Sensory opening (room, object, habit, sensation)
- Pivot to psychological tension by 12s
- Core question by 40s
- ONE mechanism explained once (what→why→behavior)
- 3 tools: each = name + script template + micro-action
- Tools are editorial illustrations, not mechanisms
- Landing: core reframe → quiet realization → ONE CTA sentence
- NO channel intro, NO definitions, NO generic encouragement

{CLAIM_VOCAB_BAN_JA}

{ANTI_STORY_RULES}

Write ONLY Japanese paragraphs. No markdown, no headings, no SSML.
"""


# ─────────────────────────────────────────────────────────────
# REVIEW V2 - Problem-Solving Gate
# ─────────────────────────────────────────────────────────────

def review_v2_prompt(contract: dict, plan: dict, source_pack: dict, draft: str) -> str:
    return f"""CONTRACT: {contract}
PLAN: {plan}
SOURCE PACK: {source_pack}
DRAFT: {draft}

Review PROBLEM-SOLVING script. Return JSON:
{{
  "decision": "pass|revise",
  "optimization_report": "detailed feedback",
  "issues": ["list of issues"],
  "required_changes": ["specific changes needed"],
  "format_alignment": {{"classification": "A|B|C|D|E", "rationale": "..."}},
  "title_hook_alignment": {{"passed": true, "anchors": ["..."]}},
  "apply_review_prompt": "prompt for editor if revise",
  "char_report": {{"chars": 0, "target_min": 4500, "status": "ok|short"}}
}}

CHECKLIST (only revise for MAJOR issues):
1. Hook: sensory recognition → identity tension → core question by 40s?
2. EXACTLY 1 mechanism explained once (what→why→behavior)?
3. EXACTLY 3 tools, each with script_template + micro-action?
4. Tools linked to the ONE mechanism?
5. No repetition of same proposition?
6. No generic self-help, no diagnosis, no trauma claims?
7. Landing: core reframe → quiet realization → ONE CTA?
8. Title-hook alignment in first 20s?
9. Char count 4500-6500?

Only revise for the SINGLE BIGGEST issue. If flow is natural, PASS.
"""


# ─────────────────────────────────────────────────────────────
# PLANNING PROMPT
# ─────────────────────────────────────────────────────────────

def planning_prompt(topic: str, brief: dict, source_pack: dict, performance: dict) -> str:
    return f"""TOPIC: {topic}
BRIEF: {brief}
SOURCE PACK: {source_pack}
PERFORMANCE: {performance}

Create planning.json with 5-7 movements for PROBLEM-SOLVING format.

Return JSON:
{{
  "core_question": "core_psychological_question từ brief",
  "hook_draft": "behavioral_entry từ brief",
  "sections": [
    {{"id": "S1", "phase": "RECOGNITION", "segment_function": "recognition", "psychological_job": "sensory recognition and identity tension", "behavior_link": "...", "why_answered": "...", "mechanisms_used": [], "example_budget": 1, "new_information": "...", "state_advance": "BEFORE: behavior seen as flaw -> AFTER: pattern has meaning", "relative_weight": 1.0}},
    {{"id": "S2", "phase": "REFRAME_QUESTION", "segment_function": "reframe_question", "psychological_job": "early reframe and core question", "behavior_link": "...", "why_answered": "...", "mechanisms_used": [], "example_budget": 0, "new_information": "...", "state_advance": "...", "relative_weight": 1.0}},
    {{"id": "S3", "phase": "MECHANISM", "segment_function": "mechanism", "psychological_job": "source-backed mechanism", "behavior_link": "...", "why_answered": "...", "mechanisms_used": ["tên mechanism duy nhất"], "example_budget": 1, "new_information": "...", "state_advance": "...", "relative_weight": 1.5}},
    {{"id": "S4", "phase": "CONSEQUENCE", "segment_function": "integration", "psychological_job": "tool 1 demo and implication", "behavior_link": "...", "why_answered": "...", "mechanisms_used": ["tên mechanism"], "example_budget": 1, "new_information": "...", "state_advance": "...", "relative_weight": 1.5}},
    {{"id": "S5", "phase": "CONSEQUENCE", "segment_function": "integration", "psychological_job": "tool 2 demo and implication", "behavior_link": "...", "why_answered": "...", "mechanisms_used": ["tên mechanism"], "example_budget": 1, "new_information": "...", "state_advance": "...", "relative_weight": 1.5}},
    {{"id": "S6", "phase": "PRACTICAL_SHIFT", "segment_function": "practical_shift", "psychological_job": "tool 3 demo and micro-action", "behavior_link": "...", "why_answered": "...", "mechanisms_used": ["tên mechanism"], "example_budget": 1, "new_information": "...", "state_advance": "...", "relative_weight": 1.0}},
    {{"id": "S7", "phase": "INSIGHT_LANDING", "segment_function": "insight_landing", "psychological_job": "quiet self-understanding", "behavior_link": "...", "why_answered": "...", "mechanisms_used": ["tên mechanism"], "example_budget": 0, "new_information": "memory_line từ brief", "state_advance": "...", "relative_weight": 1.0}}
  ],
  "planning_quality_gate": {{
    "no_duplicate_sections": true,
    "every_section_advances_state": true,
    "psychology_is_spine": true,
    "no_plot_or_character_arc": true,
    "ending_creates_self_understanding": true,
    "exactly_one_mechanism": true,
    "exactly_three_tools": true
  }}
}}
"""


# ─────────────────────────────────────────────────────────────
# SHORTS PROMPTS
# ─────────────────────────────────────────────────────────────

def _shorts_script_prompt(topic: dict, brief: dict) -> str:
    return f"""Write a 60-90 second vertical Shorts script for Japanese audience.

Topic: {topic.get('tool', {}).get('name', topic.get('pain', ''))}
Pain: {topic.get('pain', '')}
Mechanism: {topic.get('mechanism', '')}

Format (60-90s):
1. HOOK (0-3s): Visual + text - relatable pain moment
2. INSIGHT (3-15s): One-sentence mechanism reveal
3. TOOL (15-45s): One actionable script/template
4. MICRO-ACTION (45-60s): One tiny step to do today
5. CTA (60-75s): "Try this today" + follow for more

Japanese, natural spoken style, problem-solving tone. No intros/outros.
Target: 180-220 words Japanese."""


def _shorts_shot_list_prompt(script: str) -> str:
    return f"""Break this Shorts script into 8-12 vertical shots (9:16).
Script: {script}

Return JSON:
{{
  "shots": [
    {{"shot_id": "S01", "type": "character_closeup", "prompt": "...", "duration": 3, "text": "...", "lip_sync": true}},
    ...
  ]
}}"""


def _shorts_shot_list_prompt(script: str) -> str:
    return f"""Break this Shorts script into 8-12 vertical shots (9:16).
Script: {script}

Return JSON:
{{
  "shots": [
    {{"shot_id": "S01", "type": "character_closeup", "prompt": "...", "duration": 3, "text": "...", "lip_sync": true}},
    ...
  ]
}}"""


def _shorts_publish_prompt(script: str, brief: dict) -> str:
    return f"""Create publish package for Shorts.
Script: {script}
Brief: {brief}

Return JSON:
{{
  "title": "Shorts title (Japanese, 30-50 chars)",
  "description": "2-3 câu mở đầu + CTA",
  "hashtags": ["#心理学", "#境界線", "#Shorts"],
  "tags": ["心理学", "境界線", "生きづらさ"],
  "scheduled_time": "19:00 JST",
  "pinned_comment": "One question to drive engagement"
}}"""