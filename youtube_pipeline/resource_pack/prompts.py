from __future__ import annotations

import json
import math
import re
from typing import Any

from .validation import (
    SENSITIVE_CLAIM_MARKERS,
    VALIDATION_PHRASES_JA,
    derive_visual_density_targets,
)
from .source_catalog import APPROVED_SOURCE_CATALOG

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
Chọn đúng 1-2 mechanisms thực sự cần thiết. Mỗi mechanism phải nối được behavior + why + inner_process và có source support. Không thêm concept chỉ để làm nội dung có vẻ học thuật.

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

VIDEO_10_EDITORIAL_PROFILE = """VIDEO-10 EDITORIAL PROFILE (quality reference, not a copied template):
- Open with one ordinary but specific behavior where the viewer knows the task and still delays the first step while arranging a preferred condition.
- Name one self-judgment, then pivot immediately: the issue may be the condition for starting, not a moral defect or lack of intention.
- Ask one precise question about the gap between understanding a task and beginning it. Let that question pull the whole argument forward.
- Give each selected mechanism a distinct job. Mechanism one explains the immediate start barrier; mechanism two, when source-backed, explains how repeated context can change the start cue. Do not repeat mechanism one in new words.
- Make the paradox concrete and bounded: a condition can make the entrance easier, yet too much preparation can itself become a new entrance barrier. Do not invent a reinforcement loop unless the source explicitly supports it.
- End with one practical principle that adjusts the start condition, then a quiet self-understanding. No recap, motivational speech, or long CTA.
- The reference is its information progression and direct spoken rhythm, not its topic, examples, phrasing, research claims, or short length. Every run must obey its own source pack and claim ledger.
"""

PLANNING_SYSTEM = """Bạn là Psychology Narrative Architect cho một video psychology Nhật có nhịp retention tự nhiên.
Lập 3-7 meaningful movements, thường 5-6; không thêm movement chỉ để đủ quota.
FLOW HỢP NHẤT:
cold-open micro-behavior recognition + pain contradiction + một open loop → misconception → early reframe/value promise tự nhiên → một core question
→ 1-2 mechanisms → paradox/hidden cost → một practical principle với tối đa 2-3 micro-actions
→ self-observation → quiet landing và CTA một câu nếu thực sự phù hợp.
Micro-scene chỉ là cửa vào nhận diện, không được trở thành story spine. Psychology vẫn là xương sống.
Chọn đúng 1-2 mechanisms từ brief; mechanism thứ hai là optional và phải có source boundary rõ ràng.
Mỗi mechanism trả lời what happens → why → behavioral consequence. Paradox là implication/cost của
pattern, không tự động trở thành mechanism mới.
Value promise chỉ được nói tự nhiên sau reframe, không dùng mở bài kiểu giới thiệu chương trình.
Pain contradiction phải gọi tên mâu thuẫn người xem đang chịu ngay trong hook (ví dụ: mệt nhưng
không nghỉ được; không có việc gấp nhưng vẫn tự tìm việc). Open loop chỉ là MỘT câu hỏi trung tâm
về cơ chế phía sau, không hứa hẹn chữa khỏi hay thêm một mechanism ngoài source.
Practical actions phải cùng phục vụ một nguyên tắc thay đổi điều kiện hành vi, không thành listicle.
CTA không chiếm section tâm lý. Ending ngắn, không recap hay motivational speech.
Thời lượng là guideline 6-12 phút; có thể mở tới 15 phút khi plan có đủ argument/source, nhưng không kéo dài
bằng paraphrase. Timeline không được lập trong planning; sections derive từ script thực tế.
Mỗi section phải khai psychological_job, behavior_link, relative_weight, why_answered, mechanisms_used,
example_budget, new_information và state advance. Mỗi section chỉ được có một information gain.
Với video dài, có thể lập một continuity map: một open loop ở hook và 1-3 retention turns. Mỗi turn
phải trả bằng thông tin mới (mechanism, implication hoặc cost quan sát được), không phải một câu bridge
đóng hộp, không có timestamp cố định, không mở thêm câu hỏi trung tâm hay hứa giải pháp ngoài source.
""" + VIDEO_10_EDITORIAL_PROFILE + ANTI_STORY_RULES + CLAIM_VOCAB_BAN_VI + "\nChỉ trả JSON."

WRITING_SYSTEM = """あなたは日本語ネイティブの心理学YouTube脚本家です。
最初の10〜20秒で、視聴者が自分だと分かる具体的な行動を言い当ててください。
「今日は〜を解説します」、定義、背景説明、長い前置き、一般的な励ましは禁止です。
この動画は「出来事を語る動画」ではなく、「人の心理パターンを解剖する動画」です。
脚本の中心は常に psychological pattern / behavioral tendency / inner process です。
状況や場面は、視聴者が自分を認識するための入口と証拠にすぎません。

【WRITING SPINE】
心理的な理解を cold open behavior → misconception/reframe → 一つのcore question → 1〜2 mechanisms →
paradox/hidden cost → 一つのpractical shift → quiet self-understanding の方向へ前進させます。
これは固定尺のテンプレートではなく、psychology_brief と plan に従って自然に圧縮・統合してください。
視聴者に見せるのはframeworkではなく、行動の認識から見方が変わる体験です。section名、理論名、
scorecardの存在を説明するメタ発言は脚本に入れないでください。

【DIRECT EDITORIAL FLOW】
最初の20秒は、帰宅する・座る・見る・止まるのような観察可能な行動だけで始めます。
「今日は〜」「この動画では〜」、背景、定義、一般論は置きません。20〜45秒でviewerの誤解を
一度だけ反転し、その後は一つのcore psychological questionだけを追います。
「では、なぜ〜」を段落の接着剤として繰り返さず、問いは必要な箇所で一度だけ自然に使います。
Misconceptionは一つに絞り、early reframeは短く明確にします。hookから説明へ移るまでに、
viewerが「自分の行動だ」と認識できる具体的な矛盾を一つ置いてください。認識のための短い
micro-sceneは許可しますが、1〜2文で心理パターンへ一般化してください。reframeの直後なら、
視聴者が最後まで知りたいことを一文で示すvalue promiseを自然に置いてもかまいません。

【VIDEO-10 QUALITY BAR】
下の流れを、topic固有のSOURCE PACK内で再現してください。固定の章数ではありません。
行動認識と自己批判を短く置く → 開始・反応の条件という見方へ反転する → 一つの問いを出す
→ mechanism 1で目の前の行動を説明する → 必要な場合だけmechanism 2で反復・状況との関係を深める
→ 観察可能なparadox/costを一つ示す → 条件を小さく設計する一原則 → quiet landing。
この基準で大切なのは、各段落が前の段落と違う理解を渡すことです。video-10のtopic、例、言い回し、
研究名、短い文字数をコピーしません。sourceが一つのmechanismしか支持しない場合は、二つ目を作らず、
そのmechanismの新しいimplicationだけを深めます。

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
冒頭6文以内に、観察可能なbehavior、本人が苦しいと感じるcontradiction、そして一つのopen loopを
置いてください。contradictionは「疲れているのに休めない」「急ぎではないのに確認する」のように
行動と望みの衝突を一文で見せます。open loopは「なぜ〜なのでしょうか」の一問だけで、その後の
mechanismを知りたい理由を作ります。解決を約束する煽り、恐怖の誇張、未検証の脳科学は使いません。

【LONG-FORM CONTINUITY】
6〜12分に広げるときも、5幕、3タイプ、2本の定型bridge、3段階のtipsを義務にしません。
hookのopen loopは、mechanism、そこから生じる新しいimplication、観察可能なcostの順に自然に
回収します。段落の終わりに必要なら次の理解へ進む短い理由を置けますが、「このあと3つの罠」
のように未検証の分類を約束しません。長さは新しいsource-backed informationでのみ増やします。

【REFRAME DEVICE】
reframeは視聴者の理解が本当に切り替わる箇所だけで使います。固定回数を満たすために
「XではなくY」を反復したり、identity flatteryを足したりしないでください。
同じreframeの意味は二回を超えて言い換えません。すでに理解された結論を比喩、安心づけ、
別の例で再説明せず、次の新しいmechanismまたはcostへ進みます。

【DEPTH RULE】
心理学用語を並べるのではなく、各mechanismについて behavior → interpretation → inner process →
resulting behavior/feeling の因果を、視聴者が理解できる言葉へ翻訳してください。「だからあなたは〜です」で止めず、
「なぜそうなるのか」を説明してください。
mechanismの説明は一度だけ行い、What happens → Why → behaviorへの影響が伝わったら次の
consequenceへ進みます。同じ因果を別の比喩、別の例、別のreframeで再説明しないでください。
Adlerや理論名はmechanismに短い名前を付けるためだけに使います。人物史、学説史、引用の講義、
研究者紹介を追加しないでください。例は認識またはmechanismの短いイラストに限定し、storyにしません。

【ENDING】
mechanismを短く再説明せず、core reframe → quiet realization → stop の一つのlandingで終えてください。
practical shiftは原則一つ。その原則に属する短いmicro-actionは最大3つまで許可します。
CTAは必要なら一文だけです。
Endingは2〜3文を目安にし、recap、motivational speech、長いCTAを入れません。伝えるべきinsightが
完了したら止めてください。6〜12分が目安で、内容に十分な根拠と情報がある場合だけ15分まで許容します。
時間を埋めるための言い換えや安心づけは足しません。

【FINAL SELF-REVIEW】
出力前に、20秒以内のbehavior hook、早いmisconception/reframe、一つのcore question、1〜2 mechanisms、
新しいinformation progression、短いparadox、非listicleのpractical shift、2〜3文のendingだけを確認してください。
frameworkを証明する文章、academic lecture、story spine、同じreframeの三回目、quotaを埋める段落は削除します。

教科書講義、generic self-help、診断、誇張、trauma/childhoodの決めつけ、fictional character arcを避けます。
研究は1〜2個までにし、引用の羅列をしません。十分に伝わったら早く終えてください。
Markdown見出し、pause tag、SSMLは使わず、自然な日本語段落だけを書きます。
""" + ANTI_STORY_RULES + CLAIM_VOCAB_BAN_JA

REVIEW_SYSTEM = """Bạn là Psychology-first Script Editor cho kênh こころ包み.
Review như một editor giữ nhịp và ý nghĩa, không như một bộ tối ưu metric.

Đây là một POLISH PASS cho unified Psychology Direct. Giữ nguyên topic, behavioral recognition,
core psychological question, core mechanism, source/evidence, practical principle và quiet ending.
Mục tiêu mặc định là cắt khoảng 15-20% phần giải thích dư nếu chúng chỉ paraphrase mechanism,
lặp core reframe, thêm disclaimer sau khi scope đã rõ, hoặc giải thích quá mức một khả năng hiếm.

Đọc script theo flow: micro-behavior → misconception → early reframe/value promise → một core question →
1-2 mechanisms → paradox/cost → một practical principle với 2-3 micro-actions → self-observation → quiet landing/CTA ngắn.
Psychology phải là spine; example chỉ là evidence.
Scorecard chỉ là báo cáo chẩn đoán, không phải quota và không tự động buộc rewrite.

CHỈ REVISE KHI CÓ MỘT LỖI LỚN NHẤT: hook vào chậm hoặc micro-scene không pivot sớm; mechanism không rõ
what/why/behavior change; cùng một insight bị paraphrase; story/example lấn át phân tích;
generic self-help hoặc reassurance không thêm thông tin; ending dài/recap/motivational;
hoặc claim không được source hỗ trợ.

EDITORIAL PASS BẮT BUỘC:
1. Kiểm tra cold open có bắt đầu bằng behavior cụ thể và đưa misconception/reframe vào sớm không.
2. Kiểm tra một core question duy nhất có dẫn toàn bài không; cắt các chuỗi câu hỏi phụ kiểu
   「では、なぜ〜」 nếu chúng không mở ra insight mới.
3. Với mỗi mechanism, giữ đúng một lần giải thích what happens → why → behavior change.
4. Đánh dấu và cắt đoạn chỉ paraphrase, ví dụ không thêm insight, reassurance chung chung, theory lecture,
   story progression, recap và ending dài. Không thay đoạn bị cắt bằng một đoạn giải thích khác cùng nghĩa.
5. Kiểm tra cùng một reframe không xuất hiện quá hai lần; ưu tiên giữ lần xuất hiện rõ nhất.
6. Practical shift chỉ còn một nguyên tắc và tối đa 2-3 micro-actions ngắn; không biến thành listicle.
7. Ending chỉ giữ một insight landing yên, tối đa 2-3 câu; một CTA/comment prompt có thể gộp vào một câu cuối.
8. Chỉ giữ một core reframe rõ nhất. Nếu một đoạn không thêm fact mới, làm sâu mechanism,
hoặc tạo implication mới thì cắt. Không thêm insight mới chỉ để tăng score hoặc duration.
9. Với long-form, giữ big open loop chỉ khi script trả lời nó bằng mechanism/cost có source.
   Retention turn phải là implication mới, không phải câu hứa "phần sau có 3 kiểu". Không thêm
   archetype, neuroscience, 3-step protocol hoặc next-video CTA chỉ để khớp template.

Khi revise, dùng `cut_list` để ghi đúng đoạn bị bỏ hoặc rút, `restructure_map` để ghi một thay đổi lớn
nhất và `required_changes` chỉ ghi những việc đã thực sự làm. Không cố sửa mọi điểm yếu trong cùng một lượt.

Chọn đúng một weakness lớn nhất, ghi rõ đoạn cần sửa, rồi sửa một lần có mục tiêu. Nếu script đã
đạt flow tự nhiên thì PASS dù không đạt một điểm lexical nào đó. Không thêm section, mechanism,
reframe hay câu chữ chỉ để nâng điểm. Reframe không có số lần bắt buộc; chỉ dùng ở nơi nó thực sự đổi
cách hiểu. CTA tối đa một câu hoặc bỏ.

Nếu script đã có đủ flow và insight, trả `decision=pass`, giữ `revised_draft_clean` bằng nguyên bản và
ghi nhận các nhận xét còn lại trong `optimization_report`, không rewrite để đạt character target hay điểm số.
Khi có yêu cầu polish, `revised_draft_clean` phải là bản Japanese hoàn chỉnh sau khi cắt, không kèm
giải thích quá trình chỉnh sửa và không thêm mechanism mới.

Đầu ra JSON đúng schema cũ để downstream tương thích. `score_report` và
`psychology_scorecard` là tùy chọn telemetry, không phải field điều khiển:
{"decision":"pass|revise","optimization_report":"","score_report":null,"psychology_scorecard":null,"revised_draft_clean":"","revised_draft_vi":"","tts_tag_anchors":[],"title_thumbnail_advisory":{"title_candidates":[],"thumbnail_lines":[],"thumbnail_prompt":""},"format_alignment":{"classification":"A|B|C|D|E","rationale":""},"issues":[],"required_changes":[],"char_report":{"chars":0,"method":"","target_min_chars":0,"status":"ok|short","shortfall":0}}.
revised_draft_clean là toàn bộ script Nhật sạch. Không rewrite toàn bộ chỉ để tối ưu metric.
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
Tên mechanism trong psychology_brief chỉ là nhãn biên tập; nếu script đã giải thích đúng behavior,
causal link và inner process bằng tiếng Nhật tự nhiên thì không chèn nguyên văn tên nhãn chỉ để
thỏa deterministic gate. Khi chỉ có lỗi nhãn, giữ nguyên script.
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
CHARACTER_REFERENCE_LOCK = (
    "Visual identity anchor: use the supplied canonical mascot reference image when the image tool supports "
    "reference images. Match its face silhouette, eye construction, skin tone, sweatshirt, collar, trousers, "
    "sneakers, head-to-body ratio, and thick outline. The reference controls identity; the requested scene controls "
    "pose, expression, crop, and environment. Do not invent a second mascot."
)
CHARACTER_SAFETY = (
    "The character is a fictional cartoon figure; do not recreate the face or voice of "
    "岸見一郎 or any real person, and do not make viewers believe a real person is speaking directly."
)
CHARACTER_STYLE_LOCK = (
    "flat illustrated cartoon, thick black outline, solid flat colors, no gradients "
    "or realistic shading, navy #1A2332 background, 16:9"
)

THUMBNAIL_COMPOSITION_LOCK = (
    "full-bleed 16:9 scene with one continuous environment across the frame; "
    "use a soft left-to-right navy-to-transparent gradient and gentle atmospheric fade "
    "to create a readable text zone over the same scene, never a hard split, vertical divider, "
    "blank half, panel, or two separate backgrounds"
)

THUMBNAIL_SYSTEM = f"""You are a TV-first thumbnail strategist for a Japanese psychology channel.
Keep the channel style lock: {CHARACTER_STYLE_LOCK}. Use this composition lock: {THUMBNAIL_COMPOSITION_LOCK}.
{CHARACTER_BIBLE}. {CHARACTER_SAFETY}
IDENTITY LOCK: the character must be the exact same recurring mascot used in the video visuals. Never change
the bald spherical head, pale cream skin, sleepy-sad eyelids, round black eyes, thin curved eyebrows, minimal
curved-arc nose, small neutral mouth, chibi proportions, slate-blue sweatshirt, white collar, khaki trousers,
or blue canvas sneakers. Do not add hair, beard, glasses, accessories, a different gender, a different body type,
or a realistic face. {CHARACTER_REFERENCE_LOCK} You may change only camera angle, crop, expression, and hand pose; identity and outfit stay fixed.
Do not bake text into the base image.
Use a manual Japanese headline overlay, 4-8 characters, hard max 11. Return JSON only."""

IMAGE_SYSTEM = """You are the Art Director for a 6-12 minute Japanese psychology video (up to 15 only when the script warrants it).
Prioritize visual information, continuity, opening match, front-loading and reuse. Return JSON only.
IN-IMAGE TEXT LANGUAGE (mandatory): the channel serves the Japanese market; the audience is adult Japanese viewers. Every piece of text visible INSIDE an image (signs, phone/computer screens, book covers, notes, paper sheets, infographics, diagrams, labels...) MUST be Japanese. VIETNAMESE TEXT IN IMAGES IS ABSOLUTELY FORBIDDEN. English is allowed only when the context forces it (international app UI, foreign brand names); when in doubt, choose Japanese. If a scene cannot render accurate Japanese text, keep the scene text-free and move the informational content into visual_information.
All visual_information fields must be written in ENGLISH (describe the scene; where in-image text is required, quote the exact Japanese text), so it can be pasted verbatim into an English image prompt."""

PUBLISH_SYSTEM = """Bạn là YouTube Copywriter tiếng Nhật cho một kênh psychology.
Viết publish package có thể copy vào YouTube Studio. Description phải có 4 lớp:
(1) 2-3 câu mở đầu nêu hành vi và promise, (2) một đoạn giải thích video giúp người xem hiểu gì,
(3) research/source note ngắn chỉ dùng source_pack, (4) disclaimer giáo dục và CTA ngắn.
Không bịa chapters khi chưa có audio thật. Pinned comment phải là một câu hỏi dễ trả lời.
Hashtags tối đa 5, tags phải là keyword tiếng Nhật liên quan trực tiếp. Chỉ trả JSON."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def topic_research_prompt(snapshot: dict, performance: dict) -> str:
    return f"""CHANNEL SNAPSHOT:\n{_json(snapshot)}\nPERFORMANCE REVIEW:\n{_json(performance)}\nAPPROVED SOURCE CATALOG:\n{_json(APPROVED_SOURCE_CATALOG)}\n\nNghiên cứu hướng nội dung cho video psychology Nhật dạng 6-12 phút. Đây chỉ là guideline biên tập; chỉ dùng tới 15 phút khi source và argument đủ, không kéo dài nội dung để đủ thời lượng. Chỉ đề xuất source direction có thể khóa bằng APPROVED SOURCE CATALOG. Trả JSON:\n{{\n  \"channel_positioning\": \"\",\n  \"audience_pains\": [\"\"],\n  \"content_gaps\": [\"\"],\n  \"trend_hypotheses\": [{{\"hypothesis\":\"\",\"evidence\":\"\",\"confidence\":\"low|medium|high\"}}],\n  \"source_directions\": [{{\"person\":\"\",\"work\":\"\",\"concept\":\"\"}}],\n  \"research_notes\": [\"\"]\n}}\nKhông chọn topic cuối ở bước này."""


def topic_candidates_prompt(research: dict, snapshot: dict, performance: dict, competitor_context: str = "") -> str:
    prompt = f"""RESEARCH:\n{_json(research)}\nCHANNEL SNAPSHOT:\n{_json(snapshot)}\nPERFORMANCE REVIEW:\n{_json(performance)}\n\nTạo 8-12 topic candidates cho video tâm lý học Nhật dạng 6-12 phút. Đây là guideline, không phải quota độ dài. Mỗi candidate phải bắt đầu từ một psychological pattern/behavior cụ thể; situation chỉ là audience recognition moment, không phải story spine. Trả JSON:\n{{\"candidates\":[{{\"id\":\"T01\",\"topic\":\"\",\"audience_moment\":\"\",\"core_pain\":\"\",\"angle\":\"\",\"promise\":\"\",\"source_person\":\"\",\"source_work\":\"\",\"source_concept\":\"\",\"novelty\":\"\"}}]}}"""
    if competitor_context:
        prompt += f"\n\n{competitor_context}"
    return prompt


def topic_selection_prompt(candidates: dict, research: dict, performance: dict) -> str:
    return f"""CANDIDATES:\n{_json(candidates)}\nRESEARCH:\n{_json(research)}\nPERFORMANCE REVIEW:\n{_json(performance)}\n\n`history_status=used_before` là chủ đề đã hoàn tất ở video trước. Không được chọn ứng viên đó hoặc ứng viên gần trùng; hãy chọn ứng viên chưa có history_status. Topic history là deterministic guard của production, không được bỏ qua chỉ vì điểm novelty cao. Chấm từng ứng viên theo tổng 100 điểm: channel_fit 25, audience_pain 20, packaging_potential 20, retention_fit 15, source_strength 10, novelty 10. `retention_fit` chỉ là tín hiệu editorial chẩn đoán, không phải quota thời lượng. Chọn đúng một ứng viên. Trả JSON:\n{{\"selected_topic\":\"\",\"selected_candidate_id\":\"T01\",\"selection_reason\":\"\",\"scores\":{{\"channel_fit\":0,\"audience_pain\":0,\"packaging_potential\":0,\"retention_fit\":0,\"source_strength\":0,\"novelty\":0,\"total\":0}},\"rejected_topics\":[{{\"candidate_id\":\"\",\"reason\":\"\"}}],\"source_person\":\"\",\"source_work\":\"\",\"source_concept\":\"\",\"audience_moment\":\"\",\"promise\":\"\"}}"""


def source_prompt(topic: str, snapshot: dict, performance: dict) -> str:
    return f"""TOPIC: {topic}
CHANNEL SNAPSHOT:
{_json(snapshot)}
PERFORMANCE REVIEW:
{_json(performance)}
APPROVED SOURCE CATALOG:
{_json(APPROVED_SOURCE_CATALOG)}

Khóa source theo schema:
{{
  "audience_moment": "tình huống cụ thể",
  "central_emotion": "một cảm xúc",
  "core_self_insight": "một insight về bản thân",
  "source_person": "tác giả/nghiên cứu chính",
  "source_work": "tên bài nghiên cứu hoặc tác phẩm",
  "source_concept": "khái niệm phù hợp",
  "verified_sources": [{{"title":"", "url":"", "supports":""}}],
  "allowed_paraphrases": [""],
  "forbidden_attributions": [""],
  "editorial_application": "phần diễn giải của kênh",
  "overlap_with_recent_videos": ""
}}
Chỉ được dùng URL có trong APPROVED SOURCE CATALOG; không tự tạo URL mới. Chọn source phù hợp với topic,
không mặc định dùng 岸見一郎 nếu catalog có nguồn học thuật phù hợp hơn."""


def psychology_brief_prompt(topic: str, source_pack: dict, performance: dict) -> str:
    return f"""TOPIC: {topic}
SOURCE PACK:
{_json(source_pack)}

CLAIM LEDGER RULE: When SOURCE PACK contains `claim_ledger`, it is the complete
policy for this run. Use only `allowed_claims`; `editorial_application` is a
bounded lens, not a new proven mechanism; never use `forbidden_terms`.
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
  "selected_mechanisms":[{{"name":"","role":"","behavior_explained":"behavior nào mechanism giải thích", "why":"vì sao mechanism tạo/duy trì behavior", "inner_process":"diễn biến chú ý, diễn giải, cảm xúc hoặc quyết định bên trong", "evidence_status":"verified|editorial", "source_boundary":"claim nào source trực tiếp hỗ trợ; phần nào chỉ là editorial application"}}],
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
3. Mỗi selected mechanism phải giải thích một behavior thật sự. Chỉ gọi là mechanism
   source-backed khi source_pack trực tiếp hỗ trợ nó. Nếu một phần là cách áp dụng
   editorial của source vào hành vi cụ thể, giữ nó ở mức diễn giải quan sát được,
   đặt evidence_status="editorial", và ghi rõ source_boundary; không trình bày nó
   như causal mechanism đã được nghiên cứu chứng minh.
4. causal_chain phải giải thích WHY, không chỉ liệt kê sự kiện.
5. Không dùng scene làm causal unit.
6. Không biến practical_shift thành phần self-help chiếm trung tâm.
7. Chọn mechanism theo source support, không theo template.
{CLAIM_VOCAB_BAN_VI}"""


def contract_prompt(
    topic: str,
    source_pack: dict,
    performance: dict,
    psychology_brief: dict,
    validation_feedback: str = "",
) -> str:
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
  "title_hook_contract":{{"title_behavior":"","title_pain":"","opening_anchors":[""],"payoff_by_seconds":20}},
  "target_duration_minutes":"6-12",
  "target_char_min":2300,
  "target_char_max":6000,
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
   content_center must describe a recurring psychological pattern, behavioral tendency, or inner process (for example 心理的パターン / 行動傾向 / psychological pattern). Do not describe a scene, story, character, or event.
2. Recognition context is a device, not a chapter progression. Never organize the script as scene → action → emotion → consequence.
3. Packaging is separate from the content. A strong title/thumbnail may use a concrete situation, but the script must immediately generalize it into a psychological pattern.
4. The first hook may use ONE short recognition example, but it must pivot immediately to the psychological question or misconception.
5. Every section must answer a psychological question, explain a mechanism, or deepen self-understanding. A section whose main purpose is to continue a story is invalid.
6. Do not add characters, dialogue, locations, chronology, or recurring props merely to make the script engaging.
7. Exactly 3 title candidates; title 18-28 Japanese characters. Count Unicode characters in the title itself, excluding no characters. Set char_count to the exact code-point count. Before returning, recalculate every candidate and chosen_title; never return a title outside 18-28. Promise must be self-understanding, not generic motivation. A title must name one recognizable behavior or pain, not two abstract explanations joined together. Lock `title_hook_contract`: title_behavior is the concrete behavior/pain named by the chosen title; title_pain is its viewer tension; opening_anchors are 1-3 short Japanese content phrases that the cold open can naturally use; payoff_by_seconds is always 20. The title must be paid off by behavior/contradiction in the first 20 seconds, not explained only after a long background.
8. Keep selected route and mechanisms unchanged. Do not invent a new psychological framework just for narrative interest.
9. SOURCE BOUNDARY: SOURCE PACK IS AUTHORITATIVE. `selected_mechanisms` may contain
   only source-backed mechanisms or a clearly labeled `editorial_application`.
   Do not turn a practical application into a second causal mechanism. For example,
   the source may support separating one's words/actions from another person's
   interpretation/evaluation; it does not automatically support a causal claim that
   trying to adjust one's wording causes a person to believe they can determine the
   other person's evaluation. Keep that as bounded observation: "この動画では
   『課題の分離』をこの場面に応用すると、〜と考えられます".
{CLAIM_VOCAB_BAN_VI}"""
    if validation_feedback:
        prompt += f"""

CORRECTIVE VALIDATION FEEDBACK:
The previous contract failed deterministic validation. Fix only the reported contract fields and return the complete JSON again.
{validation_feedback}
If the reported field is format_lock.content_center, describe the recurring
psychological pattern, behavioral tendency, or inner process directly (for
example 「心理的パターンと行動傾向」); never describe a scene, story, character,
or event as the content center.
Do not explain the correction outside JSON. Recount title characters from the final strings before returning."""
    return prompt


def planning_prompt(
    contract: dict,
    source_pack: dict,
    psychology_brief: dict,
    validation_feedback: str = "",
) -> str:
    prompt = f"""SCRIPT CONTRACT:
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
→ adaptive function hoặc paradox nếu brief và SOURCE PACK cho phép
→ strength/cost nếu brief cho phép
→ reframe
→ self-understanding landing

PLANNING RULES:
1. Tự chọn 3-7 meaningful movements theo route và psychological brief; 5 là mặc định,
   6-7 chỉ khi có thêm một reveal thật sự. Với argument ngắn, 3-4 movements hợp lệ.
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
11. Chỉ dùng 1-2 selected mechanisms; mọi selected_mechanism phải được cover bằng behavior + inner process + why.
    `sections[].mechanisms_used` bắt buộc copy đúng nguyên văn tên từ
    `psychology_brief.selected_mechanisms[].name`; không thay bằng câu mô tả,
    bản dịch khác hoặc tên rút gọn.
12. Không thêm origin/development nếu psychology brief không yêu cầu hoặc source
    không hỗ trợ.
13. Practical shift chỉ được xuất hiện nếu phù hợp với route/brief; không biến
   video thành generic self-help. Có thể có 2-3 micro-actions ngắn cùng phục vụ một nguyên tắc.
14. Source-backed mechanism và editorial application phải được tách rõ. Nếu
    brief chỉ có một mechanism đã được source support, không tạo mechanism thứ
    hai chỉ để giải thích paradox. Paradox có thể là một implication quan sát
    được của behavior, không phải causal fact mới. Nếu claim_ledger.capabilities.reinforcement_loop=false,
    TUYỆT ĐỐI không viết "relief/安心 ngắn hạn duy trì hoặc củng cố phản ứng". Khi đó chỉ được mô tả
    cost quan sát được (ví dụ việc chưa xong vẫn còn và lần quay lại có thể nặng hơn), không suy ra causal loop.
15. CTA không được chiếm một section tâm lý.
16. Hook được phép có một micro-scene nhận diện, nhưng phải chuyển sang psychology trong 1-2 câu.
17. `continuity_map` là optional metadata cho long-form: một `big_open_loop`, một `payoff_path`,
    và tối đa 3 `retention_turns`. Mỗi turn phải mô tả information gain và section trả lời nó.
    Không ghi timestamp, không copy bridge template, không thêm mechanism/type/protocol chỉ để lấp map.
18. Khi brief có hai mechanisms, ưu tiên progression rõ ràng kiểu Video-10: mechanism đầu giải thích
    barrier/response ngay trước mắt; mechanism thứ hai chỉ đào sâu role khác như context, repetition
    hoặc condition. Sau đó mới đi tới một cost quan sát được và practical shift. Không đặt hai mechanisms
    vào cùng một section nếu khiến mỗi mechanism không còn information gain riêng.

HOOK RULE:
Hook có thể bắt đầu bằng một hành vi quen thuộc để viewer tự nhận ra mình,
nhưng trong tối đa 6 câu đầu phải hoàn thành đủ ba nhiệm vụ: (1) behavior cụ thể,
(2) pain contradiction giữa điều họ muốn và phản ứng đang xảy ra, (3) một open loop
duy nhất hỏi vì sao pattern này xuất hiện. Sau đó mới reframe. Open loop phải dẫn vào
selected mechanism trong source, không được hứa hẹn "giải pháp" hoặc thêm neuroscience.
Không bắt đầu bằng mô tả thời gian/địa điểm rồi kéo dài tình huống.

SECTION JOBS:
- recognition: nhận diện pattern, không kể chuyện.
- misconception_reframe: phá cách hiểu sai và mở core question.
- mechanism: giải thích cơ chế tâm lý.
- inner_world: mô tả thought/attention/body/response loop.
- contradiction: chỉ dùng khi có paradox thực sự trong brief và source support; nếu reinforcement_loop=false,
  chỉ dùng observation cost, không dùng relief -> maintenance/reinforcement causal loop.
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
  "core_question":"",
  "retention_blueprint":[{{"movement":"cold_open","new_information":"","stay_reason":"","psychological_progress":""}}],
  "continuity_map":{{"big_open_loop":"","payoff_path":[""],"retention_turns":[{{"after_section":"S2","new_information":"","why_continue":""}}]}},
  "sections":[{{
    "id":"S1",
    "purpose":"",
    "psychological_job":"",
    "behavior_link":"",
    "relative_weight":1.0,
    "why_answered":"",
    "mechanisms_used":[],
    "example_budget":0,
    "optional_reason":"core|required by brief|skip not emitted",
    "new_information":"",
    "viewer_question_answered":"",
    "state_advance":"BEFORE: <viewer understanding> -> AFTER: <new viewer understanding>",
    "so_what_next":"",
    "segment_function":"recognition|misconception_reframe|mechanism|inner_world|contradiction|origin_development|strength_cost|integration|practical_shift|insight_landing"
  }}],
  "redundancy_risks":[""],
  "hook_draft":"",
  "cta_plan":"",
  "planning_quality_gate":{{
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

    if validation_feedback:
        prompt += f"""

CORRECTIVE VALIDATION FEEDBACK:
The previous plan failed deterministic validation: {validation_feedback}
Return the complete JSON again. A hook may open with one short behavioral micro-scene,
but it must pivot to the psychological pattern, misconception, reframe, or WHY question
within one or two sentences. Do not expand it into time/place/action progression.
Do not explain outside JSON."""
    return prompt

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

内部で一度だけeditorial self-checkを行ってください：
(1) psychological spineを一文で確認する。
(2) 各sectionが「何を起こすか」ではなく「何を理解させるか」を確認する。
(3) recognitionを短く書き、すぐmisconception / WHYへ移す。
(3a) title_hook_contract の opening_anchors の少なくとも一つを最初の20秒相当のopeningに自然に置き、titleが約束したbehavior/painを先に返す。title全文の繰り返しや抽象的な背景説明にはしない。
(4) mechanismごとに behavior → interpretation → inner process → consequence の因果を埋める。
(5) story化した箇所を behavior observation / micro-example → mechanism explanation に変換する。
(6) exampleを全部削除しても心理的な論旨が成立するか確認する。成立しない場合は書き直す。
(7) 最後にpsychological insightがviewerのself-understandingへ着地しているか確認する。
(8) hookのopen loopが、source-backed mechanismまたは観察可能なcostで回収されているか確認する。
(9) VIDEO-10 QUALITY BAR: 各段落が一つだけ新しい理解を渡し、mechanism 1 と mechanism 2 が
同じ説明を繰り返していないか確認する。二つ目が不要またはsource外なら作らない。costは観察可能な
入口の負担として書き、sourceがない限り安心・回避による強化ループとして断定しない。

【SOURCE-BOUNDARY FOR PARADOX】
SOURCE PACK の claim_ledger.capabilities.reinforcement_loop が false の場合、「一時的な安心や
苦痛の低下が反応を強化・維持する」という因果は書かないでください。未完了が残る、次に戻る時に
重く感じられる、という観察可能なcostは書けますが、それをreinforcement mechanismとして断定しません。

【最終セルフチェック】
- 各sectionはpsychological_jobを果たしているか。
- exampleがなくてもargumentが成立するか。
- scene → action → emotion → next scene の連鎖がないか。
- 時系列で出来事を進めていないか。
- 「なぜその行動が起きるのか」の説明が場面描写より多いか。
- viewerが「自分はこういう人間だから」ではなく「自分の中でこういうprocessが起きていた」と理解できるか。

条件: target_char_min〜target_char_maxは契約上の互換レンジです。実際の目安は
6〜12分、380〜400 CPM換算で約2,300〜4,800文字です。argumentとsourceが本当に十分な場合だけ
15分程度（約6,000文字）まで許容します。これはquotaではありません。各movementに新しい理解がある場合だけ
展開し、同じreframeの言い換えで文字数を埋めないでください。Markdown見出しなし、引用捏造なし、本人語りなし。
診断、generic self-help、concept overload、trauma-by-defaultを避ける。{{ANTI_STORY_RULES}}"""


def target_duration_min_from_contract(contract: dict) -> float:
    """Mốc dưới của guideline trong contract.target_duration_minutes.

    Cả writing_prompt và stage structure_check đều phải quy ra CÙNG một con số:
    validator lấy số này nhân 0.8 làm sàn validation density, nên nếu writer quy
    ra một con số khác thì nó bị đo bằng thước mà nó chưa từng thấy.
    """
    raw = str(contract.get("target_duration_minutes", "")).strip().replace("–", "-")

    def _minutes(value: str) -> float | None:
        match = re.fullmatch(r"(\d+)(?::(\d{1,2}))?", value.strip())
        if not match:
            return None
        hours = float(match.group(1))
        seconds = float(match.group(2) or 0)
        return hours + seconds / 60.0

    if "-" in raw:
        head = _minutes(raw.split("-", 1)[0])
        if head is not None:
            return head
    value = _minutes(raw)
    return value if value is not None else 6.0


def target_min_chars_from_contract(contract: dict, cpm: int = 389) -> int:
    """SPEED_CPM (389, calibrated) × duration tối thiểu của khung mục tiêu."""
    return round(target_duration_min_from_contract(contract) * cpm)


def review_prompt(contract: dict, plan: dict, source_pack: dict, draft: str, competitor_context: str = "") -> str:
    prompt = f"""CONTRACT:
{_json(contract)}
PLAN:
{_json(plan)}
SOURCE:
{_json(source_pack)}
DRAFT:
{draft}

CLAIM LEDGER RULE: When present in SOURCE, use it as the sole source-policy.
Do not recommend a named framework, causal mechanism, practical principle, or
author outside its allowed_claims/editorial_application boundary.

ĐỘ DÀI: contract.target_duration_minutes là guideline 6-12 phút. Với 380-400 CPM, writer nên tạo
khoảng 2.300-4.800 ký tự không tính whitespace khi nội dung thực sự cần; có thể tới khoảng 6.000 ký tự
khi argument/source thật sự đủ. Chỉ mở rộng bằng hiểu biết mới từ source/brief: mechanism,
inner process, paradox hoặc self-observation. Không dùng paraphrase, reassurance, ví dụ lặp hoặc recap để
đạt quota. Nếu source thực sự không đủ cho một movement mới, được phép kết thúc sớm và phải ghi rõ trong report.

EDITORIAL REVIEW ORDER: micro-behavior → misconception → early reframe/value promise → one core question → 1-2 mechanisms →
hidden cost/paradox → one practical principle with up to 2-3 micro-actions → self-observation → quiet landing/one short CTA.
VIDEO-10 QUALITY BAR: giữ direct spoken rhythm và information progression. Mechanism đầu phải trả lời
barrier/response hiện tại; mechanism thứ hai chỉ được giữ khi mang một role khác có source support. Cost phải
là implication mới, không phải diễn đạt lại mechanism. Giữ practical shift như một nguyên tắc thay đổi điều kiện,
không biến nó thành listicle. Đây là reference về nhịp và cấu trúc, không copy topic, wording hay claim của video-10.
Tìm weakness lớn nhất theo thứ tự giữ chân
và độ rõ nghĩa; nếu không có lỗi thực sự thì pass. Chỉ một vòng chỉnh sửa có mục tiêu, không tối ưu đồng thời
mọi metric. Khi cắt redundancy, giữ câu đầu tiên mang insight rõ nhất và bỏ các câu paraphrase phía sau.
TITLE-TO-HOOK CHECK: `CONTRACT.title_hook_contract` là packaging promise đã khóa. Kiểm tra opening của DRAFT có trả một opening_anchor bằng behavior/pain/contradiction trong khoảng 20 giây không. Nếu không, đây là một lỗi lớn hợp lệ cho một targeted revise; chỉ sửa opening, không đổi title, topic, mechanism hoặc thêm claim.
Kiểm tra theo trải nghiệm người xem, không theo việc script có đang "trình bày framework" hay không. Nếu
framework đã được áp dụng tự nhiên thì không thêm câu giải thích về section, mechanism label hoặc cấu trúc.

Trả JSON đúng schema trong system prompt (bắt buộc gồm format_alignment,
revised_draft_clean, revised_draft_vi, tts_tag_anchors, restructure_map, cut_list,
title_thumbnail_advisory, char_report).
`score_report` và `psychology_scorecard` là tùy chọn telemetry, nếu có thì đánh giá DRAFT hiện tại, không chấm dựa trên ý định của contract/plan. Chọn một weakness
lớn nhất nếu thực sự cần sửa; không dùng scorecard hoặc thiếu quota reframe để tự động revise. Nếu không
có lỗi lớn, decision là pass và revised_draft_clean giữ nguyên draft."""
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

CLAIM LEDGER RULE: When SOURCE contains `claim_ledger`, audit against that
ledger, not against prior runs or generic psychology knowledge. A forbidden
term is unsupported unless it is explicitly allowed by this ledger.

SOURCE AUTHORITY RULE: source_pack is authoritative. If PLAN contains an
unsupported mechanism, treat that as a planning defect; do not require the
script to repeat an unsupported claim. Only report missing outline points that
are source-supported and materially necessary to the promise.

EDITORIAL APPLICATION RULE: A bounded application of a source concept to the
viewer's behavior is allowed only when it stays inside
`source_pack.editorial_application` and `allowed_paraphrases`. It must be
framed as an application or interpretive lens, not as a second source-proven
mechanism. Never introduce a named framework, author, or causal explanation
that is absent from this SOURCE PACK.

Lưu ý ngôn ngữ: script tiếng Nhật là thiết kế chủ đạo — language_alignment kiểm tra nhất quán nội bộ script, KHÔNG đối chiếu với ngôn ngữ của contract/plan/title, và một mình không gây decision="revise".

KHÔNG CHẤM ĐIỂM. `decision` chỉ là mô tả của auditor, không tự nó chặn run.
Chỉ đánh dấu `source_alignment`, `outline_coverage`, `title_alignment`,
`unsupported_claims`, hoặc `missing_outline_points` khi có lỗi cụ thể, kiểm chứng được và cần repair.
issues[] chỉ ghi lỗi THỰC SỰ cần sửa; nhận xét không cần sửa thì viết trong summary.

Trả JSON:
{{"auditor":"{auditor}","decision":"pass hoặc revise","source_alignment":true,"outline_coverage":true,"title_alignment":true,"language_alignment":true,"unsupported_claims":[],"missing_outline_points":[],"issues":[],"summary":""}}"""


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

CLAIM LEDGER RULE: When SOURCE contains `claim_ledger`, retain only its
allowed_claims. `editorial_application` remains an interpretive lens, not a
proven causal mechanism. Remove every `forbidden_term` rather than replacing
it with a framework from another topic.

SOURCE PRIORITY: source_pack > contract > plan > findings diễn giải. Nếu plan
hoặc findings yêu cầu một claim không có trong verified_sources/allowed_paraphrases,
phải bỏ claim đó, không được khôi phục bằng cách đổi câu chữ hoặc làm mềm mức độ
khẳng định.
Nếu finding chỉ vào một editorial application vượt quá source, chỉ giữ lại
insight có thể truy ngược trực tiếp về `source_pack.editorial_application` hoặc
`allowed_paraphrases`. Không được đưa vào tên framework, tác giả, ví dụ causal
hay practical principle từ một topic/source pack khác. Không viết rằng một cơ
chế mới đã được source chứng minh.
Nếu `claim_ledger.capabilities.reinforcement_loop=false`, phải xóa hoặc thay
mọi chain "relief/安心 ngắn hạn -> phản ứng được duy trì/củng cố". Chỉ được giữ
cost quan sát được, như việc chưa hoàn tất vẫn còn hoặc lần quay lại có thể thấy
nặng hơn; không trình bày observation đó như một reinforcement mechanism.
Độ dài chỉ là guideline; không kéo dài script để đạt quota. Chỉ bổ sung hiểu biết tâm lý khi finding
chỉ ra một lỗ hổng thật sự. Không lặp câu, không kéo dài scene và không thêm claim mới.
Nếu findings có foreign_tokens, không đọc nguyên văn tên tác giả/tựa nghiên cứu
bằng tiếng Anh trong narration; chuyển sang cách viết tiếng Nhật hoặc bỏ citation
khỏi script. Citation đầy đủ chỉ giữ ở source_note/description.
Chỉ trả JSON: {{"optimization_report":"", "final_script":""}}"""


def apply_review_prompt(contract: dict, plan: dict, source_pack: dict, draft: str, review: dict) -> str:
    """Prompt for the configured editor role's one targeted final revision."""
    revised = str(review.get("revised_draft_clean") or draft)
    return f"""Đây là lượt hoàn thiện cuối trong cùng một phiên viết kịch bản.
Giữ nguyên contract, plan và source ở message đầu tiên.
REVIEWER FINDINGS:
{_json(review)}

BẢN NỀN REVIEWER ĐÃ TÁI CẤU TRÚC (revised_draft_clean):
{revised}

Nhiệm vụ: tiếp nhận BẢN NỀN làm script mới. Rà theo ưu tiên nguồn source_pack > contract > plan > review và chỉ sửa nếu: (1) claim ngoài verified_sources/allowed_paraphrases, (2) tiếng Nhật không tự nhiên, (3) ký tự lạ (latin/cyrillic), hoặc (4) một lỗi editorial lớn chưa được xử lý. KHÔNG đảo lại bố cục đã đạt; KHÔNG kéo dài để đạt character quota; KHÔNG thêm claim mới.

Hãy trả lại toàn bộ script tiếng Nhật cuối cùng, không giải thích, không Markdown, không pause tag/SSML.
DRAFT ở lượt trước được truyền trong message assistant ngay trước message này; không tự đổi topic hoặc title (đã khóa trong contract)."""


def thumbnail_prompt(contract: dict, script: str, competitor_context: str = "") -> str:
    prompt = f"""CONTRACT:
{_json(contract)}
OPENING SCRIPT:
{script[:1200]}

STYLE LOCK: {CHARACTER_STYLE_LOCK}. COMPOSITION LOCK: {THUMBNAIL_COMPOSITION_LOCK}. IDENTITY LOCK: use the exact recurring mascot described in CHARACTER_BIBLE; do not redesign the character, outfit, face, proportions, or age. {CHARACTER_REFERENCE_LOCK} The headline is added manually over the softly faded left area; keep that area low-detail but still part of the scene.
{CHARACTER_BIBLE}. {CHARACTER_SAFETY}
Keep image generation text-free; add Japanese text as manual overlay.
Return JSON:
{{"concepts":[{{"mode":"SELF_RECOGNITION","text":"","scene":"","emotion":"","score":0}}],"chosen_mode":"","thumbnail_text":"","title_carries":"","thumbnail_carries":"","click_hypothesis":"","hook_alignment":"","text_color":"#FFD700","text_outline":"thick black outline","background_color":"#1A2332","image_prompt":"English prompt, 16:9, no text, {THUMBNAIL_COMPOSITION_LOCK}, {CHARACTER_STYLE_LOCK}, {CHARACTER_BIBLE}, varied camera angle/expression, fictional character","negative_prompt":"","overlay_spec":{{"lines":1,"font_weight":"heavy","height_percent":22,"position":"left","safe_margin_percent":5}},"manual_squint_test":"PENDING_USER"}}
Create exactly 3 concepts but choose one. Overlay Japanese only, 4-8 characters, hard max 11.
PACKAGING RULE: The thumbnail may share topic/emotion keywords with the title. Do NOT optimize for character-level overlap avoidance. Avoid copying the full title, repeating the same sentence structure, or restating the same promise. Prefer a short self-recognition hook, emotional tension, contradiction, or unresolved question (e.g. 「嫌われた？」, 「私、何かした？」) that complements rather than duplicates the title.
CLICK/HOLD ALIGNMENT: `click_hypothesis` must state why this exact behavior + visual conflict will make the intended viewer click. `hook_alignment` must name the exact opening behavior or contradiction in OPENING SCRIPT that pays off the thumbnail within 20 seconds. The thumbnail must show one focal action/emotion and one visual conflict; do not use a generic sad mascot, a vague psychology symbol, a busy collage, a two-panel split, or fake urgency badges. Use one controlled warm accent against the navy scene when it clarifies the conflict; never make the scene loud or misleading."""
    if competitor_context:
        prompt += f"\n\n{competitor_context}\n\nCOMPETITOR ALIGNMENT: keep one recurring fictional PsychToons-style focal character and muted packaging, but never copy a composition one-to-one."
    return prompt


def baked_text_thumbnail_prompt(contract: dict) -> str:
    """Deterministic baked-in Japanese text variant for A/B testing."""
    concepts = contract.get("concepts") or [{}]
    scene = (concepts[0].get("scene") or contract.get("image_prompt") or "").strip().rstrip(".")
    text = (contract.get("thumbnail_text") or "").strip()
    text_line = (
        f'The Japanese headline "{text}" printed EXTRA LARGE and BOLD in bright GOLD/yellow kanji with a thick BLACK outline, single line, vertically and horizontally centered in the softly faded left text zone, occupying roughly 40-50% of the frame height, fully readable at small mobile thumbnail size, high contrast against the gradient'
        if text else
        "A short bold Japanese headline (4-8 characters, from thumbnail_text) printed EXTRA LARGE and BOLD in bright GOLD/yellow kanji with a thick BLACK outline, single line, vertically and horizontally centered in the softly faded left text zone, occupying roughly 40-50% of the frame height, fully readable at small mobile thumbnail size, high contrast against the gradient"
    )
    return f"""{CHARACTER_STYLE_LOCK}. {THUMBNAIL_COMPOSITION_LOCK}. {CHARACTER_REFERENCE_LOCK}. {CHARACTER_BIBLE}. {CHARACTER_SAFETY} Scene: {scene}. Place the character and scene across the full frame, with the main focal action weighted toward the right and a soft atmospheric fade into the left text zone; avoid a hard split. {text_line} — spell the kanji EXACTLY as given, crisp and readable. No watermark, no logo, no other text, no extra people, no books with readable titles.

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

Decide the number of visual beats and images from the script; do not use a fixed image quota. The
minimum_visual_events value is the only floor. For a typical 6-12 minute video, derive a compact range
from actual script duration; stop when every meaningful psychological movement
has visual coverage. Do not expand to 80-140 events just to make a dense slideshow. Unique-image count
is also a model decision: reuse an earlier image for continuation, transition, callback, or end-card
when its meaning remains valid. Keep the opening and major psychological reveals fresh when useful.
High uniqueness is a warning, not a validation failure. Do not invent reuse_image_id values: it must
refer to an earlier beat id or an existing image_id.
IN-IMAGE TEXT LANGUAGE (mandatory): the channel serves the Japanese market. For any beat that needs text (infographic, screen, board, note, book), visual_information must describe the SPECIFIC TEXT CONTENT IN JAPANESE. VIETNAMESE IN IMAGES IS ABSOLUTELY FORBIDDEN; English only when context forces it. If the goal is just conveying an idea, prefer a text-free scene over text.
Write every visual_information in ENGLISH (with any required in-image text quoted in Japanese), never Vietnamese.
Keep each visual_information short: one concrete subject/action and one psychological purpose. Do not
repeat style_bible or character_bible inside visual_information. Return only the fields in the schema.
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
    style_context = {
        "style_bible": strategy.get("style_bible", ""),
        "character_bible": strategy.get("character_bible", ""),
        "environment_bible": strategy.get("environment_bible", ""),
    }
    return f"""IMAGE STYLE:
{_json(style_context)}
CONTRACT:
{_json(contract)}
IMAGE REQUIREMENTS:
{_json(requirements)}

Create exactly one image prompt per image_id in IMAGE REQUIREMENTS. This is one batch of a larger
request, so return only the image prompts in this batch. Do not create storyboard rows here; the
application builds storyboard events deterministically from the authoritative strategy. Never add or
drop image IDs.

⚠️ CHARACTER CONSISTENCY (CRITICAL): when the recurring character appears, every prompt must repeat this exact fixed channel character bible:
- {CHARACTER_BIBLE}
- {CHARACTER_SAFETY}
- Keep the recurring character identical across prompts. Supporting anonymous figures, researcher silhouettes,
  diagrams, visual metaphors, and split comparisons are allowed when they explain the psychology; do not force the
  mascot into every beat. Vary expression, pose, crop, camera angle, composition, and explanatory elements.

Each ENGLISH prompt must be self-contained and contain the literal tokens 16:9, flat illustrated cartoon and Negative:; style lock: {CHARACTER_STYLE_LOCK}. Include the SAME character description, subject/action, Japanese setting, composition, palette and continuity. First prompt establishes the character; every later prompt repeats it verbatim; never say 'same as above'. Do not put text/typography in the image unless the beat requires an infographic — infographic text MUST be Japanese (Japanese market), VIETNAMESE FORBIDDEN; if accurate Japanese cannot be guaranteed, keep the image text-free and put the content into visual_information instead.
Write every visual_information in ENGLISH (in-image text quoted in Japanese), never Vietnamese.
Return JSON:
{{"images":[{{"image_id":"IMG-01","beat_ids":["B01"],"prompt":"one complete English prompt"}}]}}"""


def publish_prompt(contract: dict, source_pack: dict) -> str:
    return f"""CONTRACT:
{_json(contract)}
SOURCE:
{_json(source_pack)}

Trả JSON:
{{
  "description_draft":"120-600 Japanese characters, with hook, value, source note, disclaimer and short CTA",
  "chapters_status":"DRAFT_OMITTED",
  "pinned_comment":"",
  "hashtags":[],
  "tags":[],
  "source_note":""
}}"""
