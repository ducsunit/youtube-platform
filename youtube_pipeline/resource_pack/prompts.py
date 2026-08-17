from __future__ import annotations

import json
import math
from typing import Any

from .validation import (
    SENSITIVE_CLAIM_MARKERS,
    VALIDATION_PHRASES_JA,
    derive_visual_density_targets,
)
from .source_catalog import KISHIMI_SOURCE_CATALOG

# Danh sách chặn phải sinh ra từ SENSITIVE_CLAIM_MARKERS, không chép tay: validator
# so khớp theo MẶT CHỮ nên prompt liệt kê thiếu một từ là run chết ở stage planning
# hoặc writing. Quan sát thực tế (run psychtoons-verify-01): planner thử 3 lần, mỗi
# lần rơi vào một từ khác (幼少期 → 子どもの頃 → 親の顔色) vì prompt chỉ cấm theo ý
# nghĩa ("không claim nguyên nhân tuổi thơ") mà không cấm chính từ đó.
_BANNED_CLAIM_VOCAB = " / ".join(SENSITIVE_CLAIM_MARKERS)

# stage structure_check đếm số lần các câu này xuất hiện để tính validation
# density, nên prompt phải liệt kê ĐÚNG bộ đó — sinh ra từ cùng một constant.
_VALIDATION_PHRASE_LIST_JA = "\n".join("- " + phrase for phrase in VALIDATION_PHRASES_JA)
_VALIDATION_PHRASE_INLINE_JA = " / ".join(VALIDATION_PHRASES_JA)
_VALIDATION_PHRASE_QUOTED_JA = ", ".join('"%s"' % phrase for phrase in VALIDATION_PHRASES_JA)

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


SOURCE_SYSTEM = """Bạn là biên tập viên nghiên cứu cho kênh tâm lý học tiếng Nhật.
Chỉ dùng dữ liệu và nguồn được cung cấp. Không giả phát ngôn, không tạo endorsement và không chẩn đoán y khoa.
Chỉ trả JSON đúng schema."""

TOPIC_RESEARCH_SYSTEM = """Bạn là chiến lược gia nội dung cho kênh tâm lý học tiếng Nhật.
Phân tích dữ liệu kênh, hiệu suất và khoảng trống nội dung để đề xuất hướng video mới.
Không bịa số liệu; phân biệt rõ dữ liệu quan sát được với giả thuyết cần kiểm tra.
Chỉ trả JSON đúng schema."""

TOPIC_SELECTION_SYSTEM = """Bạn là trưởng biên tập kênh tâm lý học tiếng Nhật.
Từ báo cáo nghiên cứu và danh sách ứng viên, chấm điểm minh bạch rồi chọn đúng một topic.
Ưu tiên tình huống đời thường cụ thể, promise hẹp, dễ làm title/thumbnail và có nguồn triết học phù hợp.
Chỉ trả JSON đúng schema."""

CONTRACT_SYSTEM = """Bạn là Head Writer cho kênh psychology YouTube Nhật Bản.
Khóa psychological spine, một promise hẹp VÀ format lock trước khi viết: video là
psychological profile / psychological deep-dive về một kiểu người hoặc một behavioral
pattern lặp lại, kể bằng direct psychological explanation, ví dụ hành vi chỉ là minh họa.
Forbidden spine: narrative story, personal anecdote, cinematic monologue, fictional
character journey, chronological life story. Psychology giải thích behavior; scene chỉ là
micro-example. Đầu ra JSON, không viết full script."""

PSYCHOLOGY_BRIEF_SYSTEM = """Bạn là Psychology Editor cho một kênh YouTube Nhật Bản chuyên psychological profile / psychological deep-dive.
Nhiệm vụ của bạn không phải kể lại một tình huống, mà phải xây một MODEL TÂM LÝ có thể dùng làm xương sống cho toàn bộ video.

BẮT ĐẦU TỪ PSYCHOLOGICAL PATTERN, KHÔNG BẮT ĐẦU TỪ STORY:
- Xác định kiểu người hoặc behavioral pattern lặp lại mà viewer có thể tự nhận ra ở bản thân.
- Tình huống đời thường chỉ là recognition context / evidence, không phải protagonist, plot hay chronological sequence.
- Phải trả lời được: người này thường làm gì → họ đang hiểu điều gì → vì sao họ hiểu như vậy → bên trong đang xảy ra quá trình gì → mechanism nào duy trì pattern → pattern này có cái giá và chức năng gì.

MODEL TÂM LÝ BẮT BUỘC:
psychological_identity → recognizable_behavior_signals → misconception → early_reframe → core_psychological_question → selected_mechanisms → causal_chain → inner_process_map → cost/function → self-understanding.
Không được biến brief thành outline, scene list hoặc advice list.

MECHANISM RULE:
Chọn đúng 1-3 mechanisms thực sự cần thiết. Mỗi mechanism phải nối được behavior + why + inner_process và có source support. Không thêm concept chỉ để làm nội dung có vẻ học thuật.

RECOGNITION RULE:
Behavior signals phải là hành vi quan sát được, cụ thể và có thể nhận ra trong đời sống. Không viết chúng thành cảnh có mở đầu/diễn biến/kết thúc.

REFRAME RULE:
common_misconception phải là cách viewer thường tự giải thích sai behavior. early_reframe phải đổi cách hiểu từ phán xét/đạo đức sang psychological process, nhưng không phủ nhận cost.

SOURCE / SAFETY:
Source pack là authority tuyệt đối. Không tự gán trauma, childhood, personality disorder, diagnosis hoặc nguyên nhân phát triển nếu source không hỗ trợ. Không dùng fictional character, plot hay character arc.

ROUTE:
Chọn đúng 1 route động dựa trên psychology thực tế. Route chỉ quyết định cách giải thích, không phải template cố định.

Chỉ trả JSON đúng schema."""

ANTI_STORY_RULES = """ANTI-STORYTELLING GUARDRAILS:
- Viewer là trung tâm; ưu tiên direct-to-viewer psychological narration.
- Không tạo protagonist có tên, plot, character arc, continuity địa điểm/đạo cụ hay dialogue qua lại.
- Micro-example chỉ 1-3 câu, tối đa 2 mỗi section; ngay sau example phải trở về mechanism/why.
- Không nối cảnh bằng cánh cửa mở, bước vào phòng, sau đó, ngày hôm sau, nhìn ra cửa sổ, nhớ lại.
- Story/example chỉ minh họa, không được tổ chức progression; explanatory narration phải chi phối.
- Nếu phát hiện scene → action → emotion → flashback, giữ behavior fact, xóa plot/setting và rewrite
  thành behavior → inner process → mechanism → why → implication.
"""

PLANNING_SYSTEM = """Bạn là Psychology Narrative Architect. Lập flow thích ứng 6-8 sections.
Behavior recognition chỉ là cửa vào; causal psychology là xương sống. Chuyển sớm từ misconception
sang reframe/core question; dành phần chính cho 1-3 mechanism blocks. Origin, strength, dark side,
signs và practical shift là optional theo psychology brief, không phải part bắt buộc.
Mỗi section phải khai psychological_job, behavior_link, why_answered, mechanisms_used,
example_budget và state advance. Kết thúc tạo self-understanding, không chỉ motivation.
""" + ANTI_STORY_RULES + CLAIM_VOCAB_BAN_VI + "\nChỉ trả JSON."

WRITING_SYSTEM = """あなたは日本語ネイティブの心理学YouTube脚本家です。
この動画は「出来事を語る動画」ではなく、「人の心理パターンを解剖する動画」です。
脚本の中心は常に psychological pattern / behavioral tendency / inner process です。
状況や場面は、視聴者が自分を認識するための入口と証拠にすぎません。

【WRITING SPINE】
心理的な理解を recognition → misconception → reframe → core WHY → mechanism → inner process →
contradiction/function/cost（必要な場合）→ integration → self-understanding の方向へ前進させます。
これは固定テンプレートではなく、psychology_brief と plan に従って自然に圧縮・統合してください。

【NARRATION MODE】
原則は「心理について直接話す」ことです。「あなたは〜しませんか」「なぜ〜してしまうのでしょう」
「ここで起きているのは〜です」のように、viewerの行動を観察し、その背後の心理を説明してください。
説明の主語は人物や出来事ではなく、psychological pattern / mind / behavior / interpretation に置きます。

【EXAMPLE RULE】
例は証拠としてだけ使います。1つの例は原則1〜3文。例を出したら直後に必ずmechanism / whyへ戻します。
例から別の例へ連続して進まないでください。「夜、〜した。すると〜。翌朝〜」のように時間・場所・出来事を
連結してstory progressionを作らないでください。

【HOOK RULE】
冒頭は短いrecognition hookのあと、すぐpsychological question / misconception / reframeへ移ります。
scene描写をhookの主役にしません。「夜、布団の中で〜」「会議室のドアが〜」のようなcinematic openingを
長く続けず、1〜2文以内に心理的な問いへ切り替えてください。

【REFRAME DEVICE】
「XではなくY。その違い」というreframeを少なくとも2回使います。1回目は冒頭のmisconception直後、
2回目は終盤のintegration/landing。必要ならmechanism block後に追加できますが、identity flatteryにはしません。

【DEPTH RULE】
心理学用語を並べるのではなく、各mechanismについて behavior → interpretation → inner process →
resulting behavior/feeling の因果を、視聴者が理解できる言葉へ翻訳してください。「だからあなたは〜です」で止めず、
「なぜそうなるのか」を説明してください。

【ENDING】
単なる励ましや一般的なself-helpで終わらず、viewerが自分のbehaviorを別の角度から理解できる
self-understanding landingで終えてください。

教科書講義、generic self-help、診断、誇張、trauma/childhoodの決めつけ、fictional character arcを避けます。
研究の引用は必要最小限にし、引用の羅列をしません。Markdown見出し、pause tag、SSMLは使わず、
契約の文字数範囲で自然な日本語段落だけを書きます。
""" + ANTI_STORY_RULES + CLAIM_VOCAB_BAN_JA

REVIEW_SYSTEM = """Bạn là Psychology-first Script Editor cho kênh こころ包み.
Bạn là semantic FORMAT GATE, không chỉ là copy editor. Mục tiêu là phân biệt:
A/B = psychological profile / psychology explainer
với
C = generic self-help essay
D = personal narrative
E = fictional story.

PSYCHOLOGY phải là CONTENT SPINE:
recognizable behavior → misconception/reframe → core WHY → mechanism → inner process →
function/cost/tension → integration → self-understanding.
Example chỉ là evidence/recognition device. Nếu xóa toàn bộ example, psychological argument
phải vẫn hoàn chỉnh.

Đánh giá script theo 7 chiều semantic sau, mỗi chiều 0-10:
- psychology_spine: psychology có thực sự tổ chức toàn bộ script không?
- mechanism_depth: mechanism có giải thích WHY + inner process + consequence không?
- insight_density: mỗi đoạn có thêm psychological understanding hay chỉ mô tả/cổ vũ?
- recognition: viewer có nhận ra pattern của chính mình bằng behavior cụ thể không?
- story_dominance: mức độ scene/chronology/character/event đang điều khiển script (0 tốt, 10 rất story).
- example_dependency: script phụ thuộc vào examples để mang lập luận đến mức nào (0 tốt, 10 rất phụ thuộc).
- reframe_signature_count: số lần có landing rõ dạng "XではなくY。この違い" hoặc tương đương tự nhiên.

BLOCKING FORMAT GATE:
- psychology_spine >= 7
- mechanism_depth >= 7
- insight_density >= 6
- recognition >= 6
- story_dominance <= 3
- example_dependency <= 3
- reframe_signature_count >= 2
Nếu bất kỳ ngưỡng nào không đạt => decision=revise. Không được hạ pass chỉ vì structure_check
không phát hiện scene marker. Semantic format là trách nhiệm của review.

REFRAME SIGNATURE:
Cần ít nhất 2 landing tự nhiên: một landing sớm sau misconception/reframe và một landing ở
phần kết. Không lặp cùng một câu, không identity flattery, không phủ nhận cost.

HOOK GATE:
Recognition có thể dùng một hành vi/situation ngắn, nhưng phải pivot sang psychological pattern,
misconception hoặc WHY rất sớm. Nếu 2+ câu đầu liên tiếp chỉ dựng scene mà chưa có psychological
meaning => revise.

ANTI-STORY:
Không fictional protagonist, không chronological plot, không scene-to-scene progression, không
flashback, không dialogue chain. Khi sửa, giữ behavior fact và chuyển thành direct psychological
observation → interpretation → mechanism → why → implication. Không thay một story bằng story khác.

Tự kiểm tra source integrity, causal logic, viewer-centered narration, concept overload, generic
self-help, unsupported origin/trauma, và self-understanding ending.

Đầu ra JSON đúng schema:
{
 "decision":"pass|revise",
 "optimization_report":"",
 "score_report":{"retention_impact":0,"style_tone":0,"pacing_structure":0,"total":0,"drop_off_points":[]},
 "psychology_scorecard":{
   "psychology_spine":0,"mechanism_depth":0,"insight_density":0,"recognition":0,
   "story_dominance":0,"example_dependency":0,"reframe_signature_count":0,
   "reasoning":{"psychology_spine":"","mechanism_depth":"","insight_density":"","recognition":"",
   "story_dominance":"","example_dependency":"","reframe_signature":""}
 },
 "restructure_map":[],"cut_list":[],"revised_draft_clean":"","revised_draft_vi":"",
 "tts_tag_anchors":[],"title_thumbnail_advisory":{"title_candidates":[],"thumbnail_lines":[],"thumbnail_prompt":""},
 "format_alignment":{"classification":"A|B|C|D|E","rationale":""},
 "issues":[],"required_changes":[],
 "char_report":{"chars":0,"method":"","target_min_chars":0,"status":"ok|short","shortfall":0}
}
revised_draft_clean là toàn bộ script Nhật sạch. decision=revise nếu semantic gate, story dominance,
causal logic, length hoặc format alignment chưa đạt. Không trả final_script, không thêm Markdown/tag/claim mới.

FORMAT_ALIGNMENT:
A psychological profile — phân tích một kiểu người / behavioral pattern;
B psychology explainer — giải thích cơ chế tâm lý;
C self-help essay — advice/flattery generic, thiếu mechanism depth;
D personal narrative — câu chuyện cá nhân;
E fictional story — nhân vật hư cấu có plot/character arc.
Target A/B. C phải revise nếu mechanism/insight không đủ; D/E luôn revise.
""" + ANTI_STORY_RULES + CLAIM_VOCAB_BAN_VI

AUDIT_SYSTEM = """Bạn là auditor độc lập. Không viết lại script và không dùng kiến thức ngoài source pack.
Kiểm tra source attribution, promise/title/outline, tiếng Nhật, claim thiếu căn cứ, psychology-first
spine, behavior-to-mechanism causality, viewer-centered narration, story dominance, plot/character
arc, concept overload, origin evidence và self-understanding ending. Chỉ trả JSON.
Script tiếng Nhật là thiết kế chủ đạo; language_alignment chỉ kiểm nhất quán nội bộ."""

REPAIR_SYSTEM = """Bạn là psychology-first repair editor. Chỉ sửa findings được cung cấp,
không thêm nguồn/claim mới. Giữ topic/promise và target range; không chèn pause tag/SSML.
Được phép tái cấu trúc section khi story dominates. Với đoạn scene/action/emotion/flashback, giữ
behavior fact rồi đổi thành direct narration + inner process + mechanism + why + implication.
Không bắt origin, childhood, triple denial, identity flattery, future vision hay healing line.
""" + ANTI_STORY_RULES + CLAIM_VOCAB_BAN_VI + '\nChỉ trả JSON {"optimization_report":"", "final_script":""}.'

TRANSLATE_SYSTEM = """Bạn là biên dịch viên chuyên dịch kịch bản YouTube tâm lý học từ tiếng Nhật sang tiếng Việt.
Bản dịch dành cho QUẢN LÝ KÊNH đọc kiểm duyệt nội dung — không dùng cho TTS, không thay thế script tiếng Nhật.
Yêu cầu: dịch sát ý, tự nhiên, đúng giọng kể chuyện ấm áp của kênh; giữ nguyên tên người, tên sách,
thuật ngữ tâm lý trong ngoặc kép bằng tiếng Nhật (岸見一郎, 『嫌われる勇気』, 「課題の分離」) kèm chú thích tiếng Việt ngắn khi cần;
giữ nguyên cấu trúc đoạn, số thứ tự, câu trích dẫn; KHÔNG thêm/bớt/tóm tắt ý; đầu ra CHỈ LÀ bản dịch, không giải thích."""

CHARACTER_BIBLE = (
    "the recurring fictional character (PsychToons-style): a bald round-headed male cartoon "
    "figure — large spherical bald head, pale cream skin, heavy sleepy-sad eyelids with a "
    "single crease line above each eye, round black eyes with small white highlights, thin "
    "curved black eyebrows, minimal curved-arc nose, small neutral line mouth; chibi "
    "proportions (large head, compact slightly chubby torso); wears a muted slate-blue crewneck "
    "sweatshirt over a white collared dress shirt, khaki straight-leg trousers, "
    "blue canvas sneakers with white laces"
)
CHARACTER_SAFETY = (
    "The character is a fictional cartoon figure; do not recreate the face or voice of "
    "岸見一郎 or any real person, and do not make viewers believe a real person is speaking directly."
)
CHARACTER_STYLE_LOCK = (
    "flat illustrated cartoon, thick black outline, solid flat colors, no gradients "
    "or realistic shading, navy #1A2332 background, 16:9"
)

THUMBNAIL_SYSTEM = f"""You are a TV-first thumbnail strategist for a Japanese psychology channel.
Keep the channel style lock: {CHARACTER_STYLE_LOCK}, subject right, clean text zone left.
{CHARACTER_BIBLE}. {CHARACTER_SAFETY}
Per video change only camera angle, crop, expression and hand pose. Do not bake text into the base image.
Use a manual Japanese headline overlay, 4-8 characters, hard max 11. Return JSON only."""

IMAGE_SYSTEM = """You are the Art Director for a 9-11 minute Japanese psychology video.
Prioritize visual information, continuity, opening match, front-loading and reuse. Return JSON only.
IN-IMAGE TEXT LANGUAGE (mandatory): the channel serves the Japanese market; the audience is adult Japanese viewers. Every piece of text visible INSIDE an image (signs, phone/computer screens, book covers, notes, paper sheets, infographics, diagrams, labels...) MUST be Japanese. VIETNAMESE TEXT IN IMAGES IS ABSOLUTELY FORBIDDEN. English is allowed only when the context forces it (international app UI, foreign brand names); when in doubt, choose Japanese. If a scene cannot render accurate Japanese text, keep the scene text-free and move the informational content into visual_information.
All visual_information fields must be written in ENGLISH (describe the scene; where in-image text is required, quote the exact Japanese text), so it can be pasted verbatim into an English image prompt."""

PUBLISH_SYSTEM = """Bạn là YouTube Copywriter tiếng Nhật. Viết description draft ngắn, pinned comment một câu hỏi lựa chọn và metadata.
Không bịa chapters khi chưa có audio thật. Chỉ trả JSON."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def topic_research_prompt(snapshot: dict, performance: dict) -> str:
    return f"""CHANNEL SNAPSHOT:\n{_json(snapshot)}\nPERFORMANCE REVIEW:\n{_json(performance)}\nAPPROVED SOURCE CATALOG:\n{_json(KISHIMI_SOURCE_CATALOG)}\n\nNghiên cứu hướng nội dung cho video Nhật 9-11 phút. Chỉ đề xuất source direction có thể khóa bằng APPROVED SOURCE CATALOG. Trả JSON:\n{{\n  \"channel_positioning\": \"\",\n  \"audience_pains\": [\"\"],\n  \"content_gaps\": [\"\"],\n  \"trend_hypotheses\": [{{\"hypothesis\":\"\",\"evidence\":\"\",\"confidence\":\"low|medium|high\"}}],\n  \"source_directions\": [{{\"person\":\"\",\"work\":\"\",\"concept\":\"\"}}],\n  \"research_notes\": [\"\"]\n}}\nKhông chọn topic cuối ở bước này."""


def topic_candidates_prompt(research: dict, snapshot: dict, performance: dict, competitor_context: str = "") -> str:
    prompt = f"""RESEARCH:\n{_json(research)}\nCHANNEL SNAPSHOT:\n{_json(snapshot)}\nPERFORMANCE REVIEW:\n{_json(performance)}\n\nTạo 8-12 topic candidates cho video tâm lý học Nhật 9-11 phút. Mỗi candidate phải là một tình huống cụ thể, không phải chủ đề chung chung. Trả JSON:\n{{\"candidates\":[{{\"id\":\"T01\",\"topic\":\"\",\"audience_moment\":\"\",\"core_pain\":\"\",\"angle\":\"\",\"promise\":\"\",\"source_person\":\"\",\"source_work\":\"\",\"source_concept\":\"\",\"novelty\":\"\"}}]}}"""
    if competitor_context:
        prompt += f"\n\n{competitor_context}"
    return prompt


def topic_selection_prompt(candidates: dict, research: dict, performance: dict) -> str:
    return f"""CANDIDATES:\n{_json(candidates)}\nRESEARCH:\n{_json(research)}\nPERFORMANCE REVIEW:\n{_json(performance)}\n\nChấm từng ứng viên theo tổng 100 điểm: channel_fit 25, audience_pain 20, packaging_potential 20, retention_8_10m 15, source_strength 10, novelty 10. Chọn đúng một ứng viên. Trả JSON:\n{{\"selected_topic\":\"\",\"selected_candidate_id\":\"T01\",\"selection_reason\":\"\",\"scores\":{{\"channel_fit\":0,\"audience_pain\":0,\"packaging_potential\":0,\"retention_8_10m\":0,\"source_strength\":0,\"novelty\":0,\"total\":0}},\"rejected_topics\":[{{\"candidate_id\":\"\",\"reason\":\"\"}}],\"source_person\":\"\",\"source_work\":\"\",\"source_concept\":\"\",\"audience_moment\":\"\",\"promise\":\"\"}}"""


def source_prompt(topic: str, snapshot: dict, performance: dict) -> str:
    return f"""TOPIC: {topic}
CHANNEL SNAPSHOT:
{_json(snapshot)}
PERFORMANCE REVIEW:
{_json(performance)}
APPROVED SOURCE CATALOG:
{_json(KISHIMI_SOURCE_CATALOG)}

Khóa source theo schema:
{{
  "audience_moment": "tình huống cụ thể",
  "central_emotion": "một cảm xúc",
  "core_self_insight": "một insight về bản thân",
  "source_person": "岸見一郎",
  "source_work": "嫌われる勇気",
  "source_concept": "khái niệm phù hợp",
  "verified_sources": [{{"title":"", "url":"", "supports":""}}],
  "allowed_paraphrases": [""],
  "forbidden_attributions": [""],
  "editorial_application": "phần diễn giải của kênh",
  "overlap_with_recent_videos": ""
}}
Chỉ được dùng URL có trong APPROVED SOURCE CATALOG; không tự tạo URL mới."""


def psychology_brief_prompt(topic: str, source_pack: dict, performance: dict) -> str:
    return f"""TOPIC: {topic}
SOURCE PACK:
{_json(source_pack)}
PERFORMANCE:
{_json(performance)}

Xây psychology model cho topic này. KHÔNG viết outline, scene progression, hook hay full script.
Hãy coi topic/situation chỉ là cửa vào để tìm ra psychological pattern phía sau. Brief phải đủ rõ để một writer khác có thể viết video psychological profile / deep-dive mà không cần biến tình huống thành câu chuyện.

Trả JSON:
{{
  "phenomenon_or_type":"một kiểu người hoặc behavioral pattern lặp lại",
  "psychological_identity":"hệ thống tâm lý đang vận hành, không diagnosis",
  "core_psychological_question":"một câu hỏi WHY mà toàn bộ video phải giải thích",
  "main_tension":"mâu thuẫn tâm lý trung tâm",
  "recognizable_behavior_signals":["3-6 hành vi cụ thể, không viết thành scene"],
  "common_misconception":"cách người xem thường hiểu sai hoặc tự phán xét behavior này",
  "early_reframe":"cách nhìn psychological thay thế cho misconception",
  "mechanism_candidates":[{{"name":"","role":"","source_support":"","confidence":"low|medium|high"}}],
  "selected_mechanisms":[{{"name":"","role":"","behavior_explained":"behavior nào mechanism giải thích", "why":"vì sao mechanism tạo/duy trì behavior", "inner_process":"diễn biến chú ý, diễn giải, cảm xúc hoặc quyết định bên trong", "evidence_status":"verified|editorial"}}],
  "causal_chain":["trigger -> interpretation -> internal process -> behavior -> short_term_function -> long_term_cost"],
  "inner_process_map":[{{"trigger":"","thought_attention_body":"","response":"","function_or_cost":""}}],
  "origin_status":"required|useful|unsupported|irrelevant|skip",
  "strength_status":"required|useful|unsupported|irrelevant|skip",
  "cost_status":"required|useful|unsupported|irrelevant|skip",
  "practical_shift_status":"required|useful|unsupported|irrelevant|skip",
  "route":"EXPLANATION|PROFILE_SIGNS|PARADOX|PROCESS|RELATIONAL",
  "exclusions":["scene-first storytelling","fictional protagonist","diagnosis","unsupported childhood/trauma cause"]
}}

QUALITY TEST trước khi trả JSON:
1. Nếu xóa toàn bộ situation/example, psychology model vẫn phải đứng vững.
2. Có thể mô tả pattern bằng "người có xu hướng..." mà không cần nhân vật cụ thể.
3. Mỗi selected mechanism phải giải thích một behavior thật sự.
4. causal_chain phải giải thích WHY, không chỉ liệt kê sự kiện.
5. Không dùng scene làm causal unit.
6. Không biến practical_shift thành phần self-help chiếm trung tâm.
7. Chọn mechanism theo source support, không theo template.
{CLAIM_VOCAB_BAN_VI}"""


def contract_prompt(topic: str, source_pack: dict, performance: dict, psychology_brief: dict) -> str:
    return f"""TOPIC: {topic}
SOURCE PACK:
{_json(source_pack)}
PSYCHOLOGY BRIEF:
{_json(psychology_brief)}
PERFORMANCE:
{_json(performance)}

Khóa psychological spine VÀ format; không thay route/mechanisms đã chọn. Trả JSON:
{{
  "core_self_insight":"",
  "central_emotion":"",
  "psychological_identity":"",
  "core_psychological_question":"",
  "main_tension":"",
  "route":"",
  "selected_mechanisms":[""],
  "single_core_promise":"",
  "title_candidates":[{{"title":"","mechanism":"","char_count":0}}],
  "chosen_title":"",
  "chosen_title_char_count":0,
  "target_duration_minutes":"9-11",
  "target_char_min":2400,
  "target_char_max":4700,
  "hook_contract":{{"recognition_by_seconds":8,"misconception_or_tension_by_seconds":18,"first_real_insight_by_seconds":35,"core_question_by_seconds":55}},
  "format_lock":{{
    "primary_format":"psychological profile / psychological deep-dive",
    "content_center":"một psychological pattern hoặc kiểu người có pattern lặp lại — psychology là content spine",
    "primary_narration":"direct psychological explanation / analysis",
    "secondary_device":"behavioral examples used only for recognition and evidence",
    "forbidden_spine":["narrative story","personal anecdote","cinematic monologue","fictional character journey","chronological life story","scene-to-scene progression"]
  }},
  "content_spine":{{
    "psychological_pattern":"",
    "core_question":"",
    "central_mechanism":"",
    "causal_logic":"",
    "viewer_self_understanding":""
  }},
  "recognition_device":{{
    "behavioral_signals":[""],
    "micro_examples":[""],
    "usage_rule":"examples identify the viewer's pattern; they must never carry the narrative progression"
  }},
  "packaging_layer":{{
    "title_question":"",
    "thumbnail_question":"",
    "curiosity_gap":"",
    "packaging_must_not_become_content_spine":true
  }},
  "spine_hierarchy":[
    "psychological pattern",
    "why it happens",
    "inner process / mechanism",
    "behavioral manifestation",
    "example as evidence",
    "reframe / self-understanding"
  ],
  "thumbnail_brief":{{"click_question":"","visual_conflict":"","title_must_not_repeat":""}}
}}
FORMAT LOCK RULES:
1. Psychology is the spine. If all examples were deleted, the argument must still be complete.
2. Recognition context is a device, not a chapter progression. Never organize the script as scene → action → emotion → consequence.
3. Packaging is separate from the content. A strong title/thumbnail may use a concrete situation, but the script must immediately generalize it into a psychological pattern.
4. The first hook may use ONE short recognition example, but it must pivot immediately to the psychological question or misconception.
5. Every section must answer a psychological question, explain a mechanism, or deepen self-understanding. A section whose main purpose is to continue a story is invalid.
6. Do not add characters, dialogue, locations, chronology, or recurring props merely to make the script engaging.
7. Exactly 3 title candidates; title 18-28 Japanese characters. Promise must be self-understanding, not generic motivation.
8. Keep selected route and mechanisms unchanged. Do not invent a new psychological framework just for narrative interest.
{CLAIM_VOCAB_BAN_VI}"""


def planning_prompt(contract: dict, source_pack: dict, psychology_brief: dict) -> str:
    return f"""SCRIPT CONTRACT:
{_json(contract)}
PSYCHOLOGY BRIEF:
{_json(psychology_brief)}
SOURCE PACK:
{_json(source_pack)}

Bạn là psychological content planner, không phải story planner.

MỤC TIÊU:
Thiết kế một "psychological argument map" cho video. Người xem phải đi từ
"tôi nhận ra pattern này ở mình" → "tôi hiểu vì sao mình làm vậy" → "tôi hiểu
cơ chế bên trong" → "tôi nhìn bản thân khác đi". Situation/example chỉ là
recognition evidence; tuyệt đối không dùng situation làm xương sống tiến triển.

CORE SPINE:
psychological_identity
→ recognizable_behavior_signals
→ misconception
→ core_psychological_question
→ mechanism / causal process
→ inner process
→ adaptive function hoặc paradox nếu brief cho phép
→ strength/cost nếu brief cho phép
→ reframe
→ self-understanding landing

PLANNING RULES:
1. Tự chọn 5-8 sections theo route và psychological brief; không dùng template
   số phần cố định.
2. Mỗi section phải trả lời MỘT câu hỏi tâm lý cụ thể. Không tạo section chỉ
   để "tiếp tục câu chuyện", "chuyển cảnh", "kể thêm ví dụ", hoặc "kết nối".
3. Section progression phải là progression của HIỂU BIẾT TÂM LÝ, không phải
   progression của thời gian, địa điểm, nhân vật hay sự kiện.
4. Recognition chỉ chiếm phần mở đầu ngắn. Sau recognition phải generalize
   ngay thành pattern hoặc psychological question.
5. Example chỉ dùng để làm người xem nhận ra pattern. Không được để example
   mở ra một chuỗi sự kiện mới kéo dài sang section kế tiếp.
6. Không được tổ chức kiểu:
   situation → reaction → next situation → reaction → explanation.
7. Không để mechanism xuất hiện như một "giải thích sau câu chuyện". Mechanism
   phải là một bước chính của argument.
8. Mỗi section phải tạo ra ít nhất một "new_information" thật sự. Không dùng
   đổi wording để tạo cảm giác tiến triển.
9. `state_advance` phải mô tả thay đổi nhận thức của viewer, không phải trạng thái nhân vật.
   BẮT BUỘC trả về đúng một chuỗi theo mẫu:
   `BEFORE: <viewer understanding before this section> -> AFTER: <viewer understanding after this section>`
   Không trả object cho field này. Không bỏ dấu `->`. AFTER phải là một thay đổi hiểu biết thực sự,
   không chỉ đổi wording hoặc mô tả hành động.
10. Tổng example_budget phải nhỏ. Nếu script có thể hoàn chỉnh mà bỏ example,
    hãy giảm example_budget.
11. Mọi selected_mechanism phải được cover bằng behavior + inner process + why.
12. Không thêm origin/development nếu psychology brief không yêu cầu hoặc source
    không hỗ trợ.
13. Practical shift chỉ được xuất hiện nếu phù hợp với route/brief; không biến
    video thành generic self-help.
14. CTA không được chiếm một section tâm lý.
15. Hook phải là psychological recognition/question, không phải cinematic scene.

HOOK RULE:
Hook có thể bắt đầu bằng một hành vi quen thuộc để viewer tự nhận ra mình,
nhưng trong vài câu đầu phải chuyển thành psychological pattern hoặc "why"
question. Không bắt đầu bằng mô tả thời gian/địa điểm rồi kéo dài tình huống.

SECTION JOBS:
- recognition: nhận diện pattern, không kể chuyện.
- misconception_reframe: phá cách hiểu sai và mở core question.
- mechanism: giải thích cơ chế tâm lý.
- inner_world: mô tả thought/attention/body/response loop.
- contradiction: chỉ dùng khi có paradox thực sự trong brief.
- origin_development: chỉ dùng khi source/brief cần.
- strength_cost: phân tích adaptive value và cost, không phán xét.
- integration: nối các mechanism thành một mô hình dễ hiểu.
- practical_shift: chỉ ra cách nhìn/điểm chuyển, không generic advice.
- insight_landing: trả viewer về self-understanding.

ANTI-STORY TEST TRƯỚC KHI TRẢ JSON:
Nếu thay toàn bộ example bằng "[EXAMPLE]" mà section vẫn hoạt động, đó là
psychology-first.
Nếu bỏ example mà section mất xương sống, section đó đang phụ thuộc vào story
và phải viết lại.
Nếu section có thể mô tả như một chuỗi "sau đó... rồi... cuối cùng...", hãy
coi đó là story progression và sửa.

Trả JSON:
{{
  "route":"",
  "retention_blueprint":[{{"time":"0:00-0:08","new_information":"","stay_reason":"","psychological_progress":""}}],
  "sections":[{{
    "id":"S1",
    "purpose":"",
    "psychological_job":"",
    "behavior_link":"",
    "why_answered":"",
    "mechanisms_used":[],
    "example_budget":0,
    "optional_reason":"core|required by brief|skip not emitted",
    "new_information":"",
    "viewer_question_answered":"",
    "state_advance":"BEFORE: <viewer understanding> -> AFTER: <new viewer understanding>",
    "so_what_next":"",
    "segment_function":"recognition|misconception_reframe|mechanism|inner_world|contradiction|origin_development|strength_cost|integration|practical_shift|insight_landing",
    "estimated_seconds":60
  }}],
  "redundancy_risks":[""],
  "hook_draft":"",
  "cta_plan":"",
  "planning_quality_gate":{{
    "first_insight_before_35s":true,
    "first_major_payoff_before_5m":true,
    "no_duplicate_sections":true,
    "every_section_advances_state":true,
    "psychology_is_spine":true,
    "no_plot_or_character_arc":true,
    "ending_creates_self_understanding":true,
    "each_section_answers_one_psychological_question":true,
    "examples_are_evidence_not_spine":true,
    "mechanism_is_argument_core":true,
    "recognition_does_not_become_scene_progression":true
  }}
}}

Origin chỉ emit khi origin_status required/useful và source có support.
Mọi selected mechanism phải được cover. Tổng example budget phải nhỏ; không
bù độ dài bằng scene. {ANTI_STORY_RULES}
{CLAIM_VOCAB_BAN_VI}"""

def writing_prompt(contract: dict, plan: dict, source_pack: dict, psychology_brief: dict) -> str:
    return f"""以下の契約、心理ブリーフ、構成に従い、日本語ナレーション本文だけを書いてください。
SCRIPT CONTRACT:
{_json(contract)}
PSYCHOLOGY BRIEF:
{_json(psychology_brief)}
ADAPTIVE PLAN:
{_json(plan)}
SOURCE PACK:
{_json(source_pack)}

内部で7パスを行ってください：
(1) psychological spineを一文で確認する。
(2) 各sectionが「何を起こすか」ではなく「何を理解させるか」を確認する。
(3) recognitionを短く書き、すぐmisconception / WHYへ移す。
(4) mechanismごとに behavior → interpretation → inner process → consequence の因果を埋める。
(5) story化した箇所を behavior observation / micro-example → mechanism explanation に変換する。
(6) exampleを全部削除しても心理的な論旨が成立するか確認する。成立しない場合は書き直す。
(7) 最後にpsychological insightがviewerのself-understandingへ着地しているか確認する。

【最終セルフチェック】
- 各sectionはpsychological_jobを果たしているか。
- exampleがなくてもargumentが成立するか。
- scene → action → emotion → next scene の連鎖がないか。
- 時系列で出来事を進めていないか。
- 「なぜその行動が起きるのか」の説明が場面描写より多いか。
- viewerが「自分はこういう人間だから」ではなく「自分の中でこういうprocessが起きていた」と理解できるか。

条件: target_char_min〜target_char_max、Markdown見出しなし、引用捏造なし、本人語りなし。
診断、generic self-help、concept overload、trauma-by-defaultを避ける。{{ANTI_STORY_RULES}}"""


def target_duration_min_from_contract(contract: dict) -> int:
    """Mốc dưới của khung "9-11" trong contract.target_duration_minutes.

    Cả writing_prompt và stage structure_check đều phải quy ra CÙNG một con số:
    validator lấy số này nhân 0.8 làm sàn validation density, nên nếu writer quy
    ra một con số khác thì nó bị đo bằng thước mà nó chưa từng thấy.
    """
    raw = str(contract.get("target_duration_minutes", "")).strip()
    if "-" in raw:
        head = raw.split("-")[0].strip()
        if head.isdigit():
            return int(head)
    elif raw.isdigit():
        return int(raw)
    return 9  # trọng tâm kênh 9–11 phút (CONSTANTS.duration_focus)


def target_min_chars_from_contract(contract: dict, cpm: int = 389) -> int:
    """SPEED_CPM (389, calibrated) × duration tối thiểu của khung mục tiêu."""
    return target_duration_min_from_contract(contract) * cpm


def review_prompt(contract: dict, plan: dict, source_pack: dict, draft: str, competitor_context: str = "") -> str:
    min_chars = target_min_chars_from_contract(contract)
    prompt = f"""CONTRACT:
{_json(contract)}
PLAN:
{_json(plan)}
SOURCE:
{_json(source_pack)}
DRAFT:
{draft}

MỤC TIÊU ĐỘ DÀI: contract.target_duration_minutes; SỐ KÝ TỰ TỐI THIỂU = {min_chars} ký tự lời thoại thuần (SPEED_CPM 389 × duration min — mục III.4). KHÔNG được nộp bản hụt dưới con số này.

Trả JSON đúng schema trong system prompt (bắt buộc gồm psychology_scorecard, format_alignment,
revised_draft_clean, revised_draft_vi, tts_tag_anchors, score_report, restructure_map, cut_list,
title_thumbnail_advisory, char_report).
Scorecard phải đánh giá DRAFT hiện tại, không chấm dựa trên ý định của contract/plan.
Nếu scorecard hoặc format_alignment không đạt blocking gate, decision phải là revise và required_changes
phải chỉ rõ section/đoạn cần sửa. Nếu draft đạt mọi gate, decision là pass và revised_draft_clean giữ nguyên draft."""
    if competitor_context:
        prompt += f"\n\n{competitor_context}\n\nCOMPETITOR HOOK CHECK: học logic recognition → psychology, không copy câu chữ; psychology-first và anti-story rules vẫn có ưu tiên cao nhất."
    return prompt


def audit_prompt(auditor: str, contract: dict, plan: dict, source_pack: dict, script: str) -> str:
    return f"""AUDITOR: {auditor}
CONTRACT:
{_json(contract)}
PLAN:
{_json(plan)}
SOURCE:
{_json(source_pack)}
FINAL SCRIPT:
{script}

SOURCE AUTHORITY RULE: source_pack is authoritative. If PLAN contains an
unsupported mechanism, treat that as a planning defect; do not require the
script to repeat an unsupported claim. Only report missing outline points that
are source-supported and materially necessary to the promise.

Lưu ý ngôn ngữ: script tiếng Nhật là thiết kế chủ đạo — language_alignment kiểm tra nhất quán nội bộ script, KHÔNG đối chiếu với ngôn ngữ của contract/plan/title, và một mình không gây decision="revise".

THANG ĐIỂM: overall_score là số nguyên trên thang 0-100 (KHÔNG dùng thang 1-10, không dùng số thập phân). Pass cần >= 90.
Ý NGHĨA CÁC TRƯỜNG: issues[] chỉ ghi lỗi THỰC SỰ cần sửa. Nhận xét không cần sửa thì viết trong summary, không đưa vào issues — issues không rỗng sẽ buộc script phải chạy lại vòng repair. decision="pass" thì issues phải rỗng.

Trả JSON:
{{"auditor":"{auditor}","overall_score":0,"decision":"pass hoặc revise","source_alignment":true,"outline_coverage":true,"title_alignment":true,"language_alignment":true,"unsupported_claims":[],"missing_outline_points":[],"issues":[],"summary":""}}"""


def repair_prompt(contract: dict, plan: dict, source_pack: dict, script: str, findings: dict) -> str:
    return f"""CONTRACT:
{_json(contract)}
PLAN:
{_json(plan)}
SOURCE:
{_json(source_pack)}
SCRIPT:
{script}
FINDINGS:
{_json(findings)}

SOURCE PRIORITY: source_pack > contract > plan > findings diễn giải. Nếu plan
hoặc findings yêu cầu một claim không có trong verified_sources/allowed_paraphrases,
phải bỏ claim đó, không được khôi phục bằng cách đổi câu chữ hoặc làm mềm mức độ
khẳng định. Chỉ trả JSON: {{"optimization_report":"", "final_script":""}}"""


def apply_review_prompt(contract: dict, plan: dict, source_pack: dict, draft: str, review: dict) -> str:
    """Prompt cho lượt DeepSeek hoàn thiện trong cùng transcript với lượt viết.

    Gemini (rule v9) đã đập đi xây lại bố cục và trả revised_draft_clean; lượt
    này DeepSeek tiếp nhận bản nền đó, rà theo source gates rồi trả script cuối.
    """
    revised = str(review.get("revised_draft_clean") or draft)
    return f"""Đây là lượt hoàn thiện cuối trong cùng một phiên viết kịch bản.
Giữ nguyên contract, plan và source ở message đầu tiên.
GEMINI REVIEW (rule v9 — Gemini đã tái cấu trúc bố cục):
{_json(review)}

BẢN NỀN GEMINI ĐÃ TÁI CẤU TRÚC (revised_draft_clean):
{revised}

Nhiệm vụ: tiếp nhận BẢN NỀN làm script mới. Rà theo ưu tiên nguồn source_pack > contract > plan > review và chỉ sửa nếu: (1) claim ngoài verified_sources/allowed_paraphrases, (2) tiếng Nhật không tự nhiên, (3) ký tự lạ (latin/cyrillic). KHÔNG đảo lại bố cục Gemini đã dựng; KHÔNG rút ngắn xuống dưới số ký tự tối thiểu theo mục III.4 của rule; KHÔNG thêm claim mới.

Hãy trả lại toàn bộ script tiếng Nhật cuối cùng, không giải thích, không Markdown, không pause tag/SSML.
DRAFT ở lượt trước được truyền trong message assistant ngay trước message này; không tự đổi topic hoặc title (đã khóa trong contract)."""


def thumbnail_prompt(contract: dict, script: str, competitor_context: str = "") -> str:
    prompt = f"""CONTRACT:
{_json(contract)}
OPENING SCRIPT:
{script[:1200]}

STYLE LOCK: {CHARACTER_STYLE_LOCK}, subject on the right half with clean text zone on the left.
{CHARACTER_BIBLE}. {CHARACTER_SAFETY}
Keep image generation text-free; add Japanese text as manual overlay.
Return JSON:
{{"concepts":[{{"mode":"SELF_RECOGNITION","text":"","scene":"","emotion":"","score":0}}],"chosen_mode":"","thumbnail_text":"","title_carries":"","thumbnail_carries":"","text_color":"#FFD700","text_outline":"thick black outline","background_color":"#1A2332","image_prompt":"English prompt, 16:9, no text, {CHARACTER_STYLE_LOCK}, {CHARACTER_BIBLE}, varied camera angle/expression, fictional character","negative_prompt":"","overlay_spec":{{"lines":1,"font_weight":"heavy","height_percent":22,"position":"left","safe_margin_percent":5}},"manual_squint_test":"PENDING_USER"}}
Create exactly 3 concepts but choose one. Overlay Japanese only, 4-8 characters, hard max 11.
PACKAGING RULE: The thumbnail may share topic/emotion keywords with the title. Do NOT optimize for character-level overlap avoidance. Avoid copying the full title, repeating the same sentence structure, or restating the same promise. Prefer a short self-recognition hook, emotional tension, contradiction, or unresolved question (e.g. 「嫌われた？」, 「私、何かした？」) that complements rather than duplicates the title."""
    if competitor_context:
        prompt += f"\n\n{competitor_context}\n\nCOMPETITOR ALIGNMENT: keep one recurring fictional PsychToons-style focal character and muted packaging, but never copy a composition one-to-one."
    return prompt


def baked_text_thumbnail_prompt(contract: dict) -> str:
    """Deterministic baked-in Japanese text variant for A/B testing."""
    concepts = contract.get("concepts") or [{}]
    scene = (concepts[0].get("scene") or contract.get("image_prompt") or "").strip().rstrip(".")
    text = (contract.get("thumbnail_text") or "").strip()
    text_line = (
        f'The Japanese headline "{text}" printed EXTRA LARGE and BOLD in bright GOLD/yellow kanji with a thick BLACK outline, single line, vertically and horizontally centered in the text zone, occupying roughly 40-50% of the frame height, fully readable at small mobile thumbnail size, high contrast against the dark background'
        if text else
        "A short bold Japanese headline (4-8 characters, from thumbnail_text) printed EXTRA LARGE and BOLD in bright GOLD/yellow kanji with a thick BLACK outline, single line, vertically and horizontally centered in the text zone, occupying roughly 40-50% of the frame height, fully readable at small mobile thumbnail size, high contrast against the dark background"
    )
    return f"""{CHARACTER_STYLE_LOCK}. {CHARACTER_BIBLE}. {CHARACTER_SAFETY} Scene: {scene}. On the LEFT half (clean text zone), {text_line} — spell the kanji EXACTLY as given, crisp and readable; keep the character on the RIGHT half. No watermark, no logo, no other text, no extra people, no books with readable titles.

Negative: watermark, logo, extra people, distorted hands, deformed fingers, blurry face, misaligned eyes, extra limbs, photorealistic, 3D render, low contrast, cluttered background, bright daylight."""


def vietnamese_translation_prompt(script: str) -> str:
    """Translate final Japanese script for channel-manager QA; never for TTS."""
    return f"""Dịch toàn bộ kịch bản tiếng Nhật dưới đây sang tiếng Việt theo đúng yêu cầu.
Bản dịch CHỈ để quản lý kênh đọc duyệt — KHÔNG dùng cho TTS, không thay thế script.txt.
- Dịch SÁT Ý, tự nhiên; GIỮ NGUYÊN tên người, tên sách, thuật ngữ Nhật trong ngoặc kép.
- Giữ cấu trúc đoạn, số thứ tự, câu trích dẫn.
- KHÔNG thêm ý, KHÔNG bỏ ý, KHÔNG tóm tắt. Chỉ trả bản dịch.

KỊCH BẢN GỐC (tiếng Nhật):
{script}"""


def image_strategy_prompt(contract: dict, plan: dict, thumbnail: dict) -> str:
    density_targets = derive_visual_density_targets(contract, plan)
    return f"""CONTRACT:
{_json(contract)}
PLAN:
{_json(plan)}
THUMBNAIL:
{_json(thumbnail)}
DYNAMIC DENSITY TARGETS:
{_json(density_targets)}

Decide the number of visual beats and images yourself, matching the video content; do not use a fixed quota. DYNAMIC DENSITY TARGETS are floors derived from duration and section count, not hard-coded numbers. You may create more if the content needs it, but never fewer than minimum_visual_events; unique-image count is a dynamic model decision. Use a dynamic visual budget. Do NOT target a fixed 70%, 80%, or 85% quota. Decide per beat whether a fresh image materially improves understanding, emotion, continuity, or a major psychological reveal. Reuse earlier images when the same established visual remains semantically valid for continuation, transition, callback, or end-card beats. Keep opening and major psychological reveals visually fresh when useful. 100% unique images are allowed when the content genuinely needs distinct visuals; high uniqueness is a cost warning, not a validation failure. Do not invent reuse_image_id values: it must refer to an earlier beat id or an existing image_id.
IN-IMAGE TEXT LANGUAGE (mandatory): the channel serves the Japanese market. For any beat that needs text (infographic, screen, board, note, book), visual_information must describe the SPECIFIC TEXT CONTENT IN JAPANESE. VIETNAMESE IN IMAGES IS ABSOLUTELY FORBIDDEN; English only when context forces it. If the goal is just conveying an idea, prefer a text-free scene over text.
Write every visual_information in ENGLISH (with any required in-image text quoted in Japanese), never Vietnamese.
Return JSON:
{{"style_bible":"","character_bible":"","environment_bible":"","opening_visual_contract":{{"thumbnail_scene":"","first_frame_scene":"","first_15s_visuals":[]}},"estimated_unique_images":0,"estimated_total_visual_events":0,"mascot_ratio":0.25,"density_check":true,"no_filler_check":true,"visual_beats":[{{"id":"B01","time":"DRAFT_TIMING","script_section":"S1","visual_information":"","mode":"literal","new_image":true,"reuse_image_id":null}}]}}"""


def image_prompts_prompt(strategy: dict, contract: dict) -> str:
    requirements = [
        {
            "beat_id": beat["id"],
            "image_id": beat["image_id"],
            "new_image": bool(beat["new_image"]),
            "visual_information": beat["visual_information"],
        }
        for beat in strategy["visual_beats"]
    ]
    return f"""IMAGE STRATEGY:
{_json(strategy)}
CONTRACT:
{_json(contract)}
IMAGE REQUIREMENTS:
{_json(requirements)}

Create exactly one image prompt per unique image_id with new_image=true in IMAGE REQUIREMENTS. Create exactly one storyboard event per beat_id, in order. Beats with new_image=false must reuse the assigned image_id. Never add or drop ids.

⚠️ CHARACTER CONSISTENCY (CRITICAL): every prompt must repeat this exact fixed channel character bible:
- {CHARACTER_BIBLE}
- {CHARACTER_SAFETY}
- Character design must be IDENTICAL across all image prompts; vary only expression, pose, crop and camera angle.

Each ENGLISH prompt must be self-contained and contain the literal tokens 16:9, flat illustrated cartoon and Negative:; style lock: {CHARACTER_STYLE_LOCK}. Include the SAME character description, subject/action, Japanese setting, composition, palette and continuity. First prompt establishes the character; every later prompt repeats it verbatim; never say 'same as above'. Do not put text/typography in the image unless the beat requires an infographic — infographic text MUST be Japanese (Japanese market), VIETNAMESE FORBIDDEN; if accurate Japanese cannot be guaranteed, keep the image text-free and put the content into visual_information instead.
Write every visual_information in ENGLISH (in-image text quoted in Japanese), never Vietnamese.
Return JSON:
{{"images":[{{"image_id":"IMG-01","beat_ids":["B01"],"prompt":"one complete English prompt"}}],"storyboard":[{{"event_id":"E01","time":"DRAFT_TIMING","beat_id":"B01","image_id":"IMG-01","new_image":true,"motion":"slow push-in","visual_information":""}}]}}"""


def publish_prompt(contract: dict, source_pack: dict) -> str:
    return f"""CONTRACT:
{_json(contract)}
SOURCE:
{_json(source_pack)}

Trả JSON: {{"description_draft":"","chapters_status":"DRAFT_OMITTED","pinned_comment":"","hashtags":[],"tags":[],"source_note":""}}"""