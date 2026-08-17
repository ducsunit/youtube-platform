from __future__ import annotations

import json
import logging
from typing import Any, Mapping, Protocol

from ..config import Settings
from ..core.llm_cache import LLMResponseCache
from ..domain.models import ValidationError
from .metrics import non_whitespace_chars
from ..infrastructure.model_trace import trace_parsed_response, trace_raw_response, trace_request
from ..providers import parse_json_object
from .prompts import (
    AUDIT_SYSTEM,
    CONTRACT_SYSTEM,
    IMAGE_SYSTEM,
    PLANNING_SYSTEM,
    PSYCHOLOGY_BRIEF_SYSTEM,
    PUBLISH_SYSTEM,
    REPAIR_SYSTEM,
    REVIEW_SYSTEM,
    SOURCE_SYSTEM,
    TOPIC_RESEARCH_SYSTEM,
    TOPIC_SELECTION_SYSTEM,
    THUMBNAIL_SYSTEM,
    TRANSLATE_SYSTEM,
    WRITING_SYSTEM,
    audit_prompt,
    apply_review_prompt,
    contract_prompt,
    image_prompts_prompt,
    image_strategy_prompt,
    planning_prompt,
    psychology_brief_prompt,
    publish_prompt,
    repair_prompt,
    review_prompt,
    source_prompt,
    target_min_chars_from_contract,
    topic_candidates_prompt,
    topic_research_prompt,
    topic_selection_prompt,
    thumbnail_prompt,
    vietnamese_translation_prompt,
    writing_prompt,
)

logger = logging.getLogger(__name__)


def _normalize_psychology_context(psychology_brief: dict | None) -> dict:
    """Normalize optional psychology context for backward-compatible provider calls.

    The runtime always supplies a validated psychology_brief. Direct provider calls and
    older integrations may omit it, so prompt builders receive an explicit empty object
    instead of raising a NameError or inventing a model.
    """
    if not psychology_brief:
        return {}
    if not isinstance(psychology_brief, dict):
        raise TypeError("psychology_brief must be a dict or None")
    return psychology_brief


class ResourceContentProvider(Protocol):
    def research_topics(self, snapshot: dict, performance: dict) -> dict: ...
    def create_topic_candidates(self, research: dict, snapshot: dict, performance: dict, competitor_context: str = "") -> dict: ...
    def select_topic(self, candidates: dict, research: dict, performance: dict) -> dict: ...
    def lock_source(self, topic: str, snapshot: dict, performance: dict) -> dict: ...
    def create_psychology_brief(self, topic: str, source_pack: dict, performance: dict) -> dict: ...
    def create_contract(self, topic: str, source_pack: dict, performance: dict, psychology_brief: dict) -> dict: ...
    def create_plan(self, contract: dict, source_pack: dict, psychology_brief: dict) -> dict: ...
    def write_script(self, contract: dict, plan: dict, source_pack: dict, psychology_brief: dict | None = None) -> str: ...
    def review_script(self, contract: dict, plan: dict, source_pack: dict, draft: str, competitor_context: str = "") -> dict: ...
    def apply_review(self, contract: dict, plan: dict, source_pack: dict, draft: str, review: dict) -> str: ...
    def audit_script(self, auditor: str, contract: dict, plan: dict, source_pack: dict, script: str) -> dict: ...
    def repair_script(self, contract: dict, plan: dict, source_pack: dict, script: str, findings: dict) -> dict: ...
    def translate_to_vietnamese(self, script: str) -> str: ...
    def create_thumbnail(self, contract: dict, script: str, competitor_context: str = "") -> dict: ...
    def create_image_strategy(self, contract: dict, plan: dict, thumbnail: dict) -> dict: ...
    def create_image_prompts(self, strategy: dict, contract: dict) -> dict: ...
    def create_publish_draft(self, contract: dict, source_pack: dict) -> dict: ...


class AIResourceProvider:
    def __init__(self, settings: Settings) -> None:
        try:
            from google import genai
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Thiếu SDK; hãy cài project dependencies.") from exc
        self.settings = settings
        self.gemini = genai.Client(api_key=settings.gemini_api_key)
        self.deepseek = OpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url)
        self.llm_cache = LLMResponseCache(settings.llm_cache_dir, settings.llm_cache_enabled, settings.llm_cache_schema_version)

    def cache_stats(self) -> dict[str, Any]:
        return self.llm_cache.stats()

    @property
    def max_retries(self) -> int:
        return self.settings.max_retries

    def _thinking_level(self, label: str) -> str:
        """Single production policy: high reasoning only where it protects quality."""
        quality_critical = {"RP_PSYCHOLOGY_BRIEF", "RP_REVIEW", "RP_AUDIT_GEMINI"}
        return "high" if label in quality_critical else "medium"

    def _gemini_generate(self, model: str, contents: str, config: Any, label: str) -> Any:
        """Gọi Gemini với retry khi API quá tải (503 / UNAVAILABLE / high demand).

        Lỗi quá tải là tạm thời — ngủ 15–30s rồi thử lại, tối đa 3 lần. Mọi lỗi
        khác (4xx, xác thực, mạng thật) raise ngay để không che giấu lỗi.
        """
        import random
        import time

        from google.genai import errors as genai_errors

        max_attempts = 3
        base_delay = 15.0
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                return self.gemini.models.generate_content(
                    model=model, contents=contents, config=config
                )
            except genai_errors.APIError as exc:
                last_error = exc
                message = str(exc).lower()
                overloaded = (
                    getattr(exc, "code", None) == 503
                    or "unavailable" in message
                    or "high demand" in message
                )
                if not overloaded or attempt == max_attempts:
                    raise
                delay = base_delay * attempt + random.uniform(0, 5)
                logger.warning(
                    "Gemini quá tải (503) — thử lại lần %d/%d sau %.0fs | stage=%s",
                    attempt + 1,
                    max_attempts,
                    delay,
                    label,
                )
                time.sleep(delay)
        assert last_error is not None
        raise last_error

    @staticmethod
    def _cacheable_label(label: str) -> bool:
        """Cache only deterministic/repeatable content tasks.

        Creative generation (writing, repair, thumbnail and image prompts) stays
        uncached so a retry can genuinely produce a different candidate.
        """
        return label in {
            "RP_TOPIC_RESEARCH",
            "RP_TOPIC_CANDIDATES",
            "RP_TOPIC_SELECTION",
            "RP_SOURCE_LOCK",
            "RP_PSYCHOLOGY_BRIEF",
            "RP_SCRIPT_CONTRACT",
            "RP_PLANNING",
            "RP_AUDIT_GEMINI",
            "RP_AUDIT_DEEPSEEK",
            "RP_TRANSLATE_VI",
            "RP_PUBLISH_DRAFT",
        }

    def _gemini_json(
        self,
        label: str,
        system: str,
        prompt: str,
        temperature: float = 0.2,
        model: str | None = None,
        thinking_level: str | None = None,
    ) -> dict:
        from google.genai import types

        chosen_model = model or self.settings.gemini_analysis_model
        level = thinking_level or self._thinking_level(label)
        cache_key = self.llm_cache.build_key(
            provider="gemini", model=chosen_model, system=system, prompt=prompt,
            temperature=temperature, thinking_level=level, schema_version=self.settings.llm_cache_schema_version,
        )
        cached = self.llm_cache.get(cache_key) if self._cacheable_label(label) else None
        if cached is not None:
            trace_raw_response(label, label, cached)
            try:
                value = parse_json_object(cached)
            except ValidationError:
                # Never let a malformed cached model response poison retries.
                self.llm_cache.delete(cache_key)
                logger.warning(
                    "Invalid LLM cache entry discarded | provider=Gemini | stage=%s | model=%s",
                    label, chosen_model,
                )
            else:
                trace_parsed_response(label, label, value)
                logger.info("LLM cache hit | provider=Gemini | stage=%s | model=%s", label, chosen_model)
                return value
        trace_request(label, label, "Gemini", chosen_model, system, prompt, temperature)
        response = self._gemini_generate(
            model=chosen_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                temperature=temperature,
                thinking_config=types.ThinkingConfig(thinking_level=level),
            ),
            label=label,
        )
        trace_raw_response(label, label, response.text)
        value = parse_json_object(response.text)
        trace_parsed_response(label, label, value)
        # Cache only responses that successfully parsed as JSON.
        if self._cacheable_label(label):
            self.llm_cache.put(cache_key, response.text)
        logger.info("Resource provider complete | stage=%s | model=%s", label, chosen_model)
        return value

    def _deepseek_json(self, label: str, system: str, prompt: str, temperature: float = 0.0) -> dict:
        cache_key = self.llm_cache.build_key(
            provider="deepseek", model=self.settings.deepseek_model, system=system, prompt=prompt,
            temperature=temperature, thinking_level="", schema_version=self.settings.llm_cache_schema_version,
        )
        cached = self.llm_cache.get(cache_key) if self._cacheable_label(label) else None
        if cached is not None:
            trace_raw_response(label, label, cached)
            try:
                value = parse_json_object(cached)
            except ValidationError:
                self.llm_cache.delete(cache_key)
                logger.warning(
                    "Invalid LLM cache entry discarded | provider=DeepSeek | stage=%s | model=%s",
                    label, self.settings.deepseek_model,
                )
            else:
                trace_parsed_response(label, label, value)
                logger.info("LLM cache hit | provider=DeepSeek | stage=%s | model=%s", label, self.settings.deepseek_model)
                return value
        raw = ""
        for attempt in range(1, 3):
            trace_request(label, label, "DeepSeek", self.settings.deepseek_model, system, prompt, temperature)
            response = self.deepseek.chat.completions.create(
                model=self.settings.deepseek_model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                temperature=temperature,
            )
            raw = response.choices[0].message.content or ""
            if raw.strip():
                break
            logger.warning("DeepSeek trả nội dung rỗng (lần %d/2) | stage=%s", attempt, label)
        trace_raw_response(label, label, raw)
        value = parse_json_object(raw)
        trace_parsed_response(label, label, value)
        # Cache only responses that successfully parsed as JSON.
        if self._cacheable_label(label):
            self.llm_cache.put(cache_key, raw)
        return value

    def _deepseek_text(self, label: str, system: str, prompt: str, temperature: float = 0.7) -> str:
        cache_key = self.llm_cache.build_key(
            provider="deepseek", model=self.settings.deepseek_model, system=system, prompt=prompt,
            temperature=temperature, thinking_level="", schema_version=self.settings.llm_cache_schema_version,
        )
        cached = self.llm_cache.get(cache_key) if self._cacheable_label(label) else None
        if cached is not None:
            trace_raw_response(label, label, cached)
            trace_parsed_response(label, label, cached)
            logger.info("LLM cache hit | provider=DeepSeek | stage=%s | model=%s", label, self.settings.deepseek_model)
            return cached
        trace_request(label, label, "DeepSeek", self.settings.deepseek_model, system, prompt, temperature)
        response = self.deepseek.chat.completions.create(
            model=self.settings.deepseek_model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            temperature=temperature,
        )
        value = response.choices[0].message.content
        if not value or not value.strip():
            raise ValueError("DeepSeek trả script rỗng.")
        result = value.strip()
        if self._cacheable_label(label):
            self.llm_cache.put(cache_key, result)
        trace_raw_response(label, label, result)
        trace_parsed_response(label, label, result)
        return result

    def _deepseek_text_messages(
        self,
        label: str,
        system: str,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
    ) -> str:
        """Reconstruct a DeepSeek conversation from persisted messages.

        Chat Completions is stateless. Sending the original user prompt, the
        previous DeepSeek answer as an assistant message, and Gemini's review as
        the next user message preserves the writer context across API calls and
        can be reproduced after a checkpoint resume.
        """
        full_messages = [{"role": "system", "content": system}, *messages]
        prompt = json.dumps(full_messages, ensure_ascii=False, sort_keys=True)
        cache_key = self.llm_cache.build_key(
            provider="deepseek", model=self.settings.deepseek_model, system=system, prompt=prompt,
            temperature=temperature, thinking_level="messages", schema_version=self.settings.llm_cache_schema_version,
        )
        cached = self.llm_cache.get(cache_key) if self._cacheable_label(label) else None
        if cached is not None:
            trace_raw_response(label, label, cached)
            trace_parsed_response(label, label, cached)
            logger.info("LLM cache hit | provider=DeepSeek | stage=%s | model=%s", label, self.settings.deepseek_model)
            return cached
        trace_request(label, label, "DeepSeek", self.settings.deepseek_model, system, prompt, temperature)
        response = self.deepseek.chat.completions.create(
            model=self.settings.deepseek_model,
            messages=full_messages,
            temperature=temperature,
        )
        value = response.choices[0].message.content
        if not value or not value.strip():
            raise ValueError("DeepSeek trả script đã sửa rỗng.")
        result = value.strip()
        if self._cacheable_label(label):
            self.llm_cache.put(cache_key, result)
        trace_raw_response(label, label, result)
        trace_parsed_response(label, label, result)
        return result

    def lock_source(self, topic: str, snapshot: dict, performance: dict) -> dict:
        return self._gemini_json("RP_SOURCE_LOCK", SOURCE_SYSTEM, source_prompt(topic, snapshot, performance))

    def research_topics(self, snapshot: dict, performance: dict) -> dict:
        return self._gemini_json("RP_TOPIC_RESEARCH", TOPIC_RESEARCH_SYSTEM, topic_research_prompt(snapshot, performance), temperature=0.4)

    def create_topic_candidates(self, research: dict, snapshot: dict, performance: dict, competitor_context: str = "") -> dict:
        return self._gemini_json("RP_TOPIC_CANDIDATES", TOPIC_RESEARCH_SYSTEM, topic_candidates_prompt(research, snapshot, performance, competitor_context), temperature=0.5)

    def select_topic(self, candidates: dict, research: dict, performance: dict) -> dict:
        return self._gemini_json("RP_TOPIC_SELECTION", TOPIC_SELECTION_SYSTEM, topic_selection_prompt(candidates, research, performance), temperature=0.1)

    def create_psychology_brief(self, topic: str, source_pack: dict, performance: dict) -> dict:
        return self._gemini_json("RP_PSYCHOLOGY_BRIEF", PSYCHOLOGY_BRIEF_SYSTEM, psychology_brief_prompt(topic, source_pack, performance), temperature=0.2)

    def create_contract(self, topic: str, source_pack: dict, performance: dict, psychology_brief: dict | None = None) -> dict:
        psychology_brief = _normalize_psychology_context(psychology_brief)
        return self._deepseek_json("RP_SCRIPT_CONTRACT", CONTRACT_SYSTEM, contract_prompt(topic, source_pack, performance, psychology_brief), temperature=0.2)

    def create_plan(self, contract: dict, source_pack: dict, psychology_brief: dict | None = None) -> dict:
        psychology_brief = _normalize_psychology_context(psychology_brief)
        return self._deepseek_json("RP_PLANNING", PLANNING_SYSTEM, planning_prompt(contract, source_pack, psychology_brief), temperature=0.3)

    def write_script(self, contract: dict, plan: dict, source_pack: dict, psychology_brief: dict | None = None) -> str:
        psychology_brief = _normalize_psychology_context(psychology_brief)
        return self._deepseek_text("RP_WRITING", WRITING_SYSTEM, writing_prompt(contract, plan, source_pack, psychology_brief))

    def review_script(self, contract: dict, plan: dict, source_pack: dict, draft: str, competitor_context: str = "") -> dict:
        return self._gemini_json(
            "RP_REVIEW",
            REVIEW_SYSTEM,
            review_prompt(contract, plan, source_pack, draft, competitor_context),
            model=self.settings.gemini_review_model,
        )

    def apply_review(self, contract: dict, plan: dict, source_pack: dict, draft: str, review: dict) -> str:
        original_prompt = writing_prompt(contract, plan, source_pack, {
            "psychological_identity": contract.get("psychological_identity"),
            "core_psychological_question": contract.get("core_psychological_question"),
            "main_tension": contract.get("main_tension"),
            "route": contract.get("route"),
            "selected_mechanisms": [{"name": name} for name in contract.get("selected_mechanisms", [])],
        })
        follow_up = apply_review_prompt(contract, plan, source_pack, draft, review)
        return self._deepseek_text_messages(
            "RP_APPLY_REVIEW",
            WRITING_SYSTEM,
            [
                {"role": "user", "content": original_prompt},
                {"role": "assistant", "content": draft},
                {"role": "user", "content": follow_up},
            ],
            temperature=0.2,
        )

    def audit_script(self, auditor: str, contract: dict, plan: dict, source_pack: dict, script: str) -> dict:
        prompt = audit_prompt(auditor, contract, plan, source_pack, script)
        if auditor == "deepseek":
            return self._deepseek_json("RP_AUDIT_DEEPSEEK", AUDIT_SYSTEM, prompt)
        return self._gemini_json(
            "RP_AUDIT_GEMINI",
            AUDIT_SYSTEM,
            prompt,
            temperature=0.0,
            model=self.settings.gemini_audit_model,
        )

    def repair_script(self, contract: dict, plan: dict, source_pack: dict, script: str, findings: dict) -> dict:
        return self._deepseek_json(
            "RP_REPAIR",
            REPAIR_SYSTEM,
            repair_prompt(contract, plan, source_pack, script, findings),
            temperature=0.2,
        )

    def translate_to_vietnamese(self, script: str) -> str:
        return self._deepseek_text("RP_TRANSLATE_VI", TRANSLATE_SYSTEM, vietnamese_translation_prompt(script), temperature=0.3)

    def create_thumbnail(self, contract: dict, script: str, competitor_context: str = "") -> dict:
        return self._deepseek_json("RP_THUMBNAIL", THUMBNAIL_SYSTEM, thumbnail_prompt(contract, script, competitor_context), temperature=0.4)

    def create_image_strategy(self, contract: dict, plan: dict, thumbnail: dict) -> dict:
        return self._deepseek_json("RP_IMAGE_STRATEGY", IMAGE_SYSTEM, image_strategy_prompt(contract, plan, thumbnail), temperature=0.4)

    def create_image_prompts(self, strategy: dict, contract: dict) -> dict:
        return self._deepseek_json("RP_IMAGE_PROMPTS", IMAGE_SYSTEM, image_prompts_prompt(strategy, contract), temperature=0.5)

    def create_publish_draft(self, contract: dict, source_pack: dict) -> dict:
        return self._deepseek_json("RP_PUBLISH_DRAFT", PUBLISH_SYSTEM, publish_prompt(contract, source_pack), temperature=0.4)


def _demo_script() -> str:
    paragraphs = [
        "通知を見た瞬間、返事をしなければと思うのに、指が止まってしまう夜があります。短い一文を送るだけなのに、胸の奥が重くなり、画面を閉じてしまう。時間がたつほど罪悪感は大きくなり、今さら何と返せばいいのか分からなくなる。これは、単に怠けているから起きるのでしょうか。",
        "実際には、返事を書く前から心の中で多くの仕事が始まっています。相手はどんな気持ちで送ったのか。短すぎると冷たく見えないか。絵文字を付けるべきか。すぐ会話が続いたら対応できるか。一つの通知の後ろにある可能性を先回りして考えるほど、返事は小さな作業ではなくなります。",
        "特に、人の表情や声の変化に敏感な人は、文章に書かれていない気持ちまで読み取ろうとします。相手を大切にしたい気持ちが強いからこそ、正しい返事を探し続けます。しかし、正解のないものに正解を求めると、心は動けなくなります。返せないのではなく、失敗しない返事を作ろうとして疲れているのです。",
        "ここで役に立つのが、アドラー心理学で語られる課題の分離という考え方です。岸見一郎と古賀史健の著書『嫌われる勇気』では、自分が引き受ける課題と、相手が引き受ける課題を見分ける大切さが説明されています。これは人を切り捨てるためではなく、関係を無理なく続けるための境界線です。",
        "返事をいつ、どのような言葉で送るかは、自分が選ぶ課題です。一方、その返事を読んで相手がどう感じるかは、最終的には相手の課題です。もちろん、乱暴な言葉を使わない配慮は必要です。しかし、どれほど丁寧に書いても、相手の受け取り方を完全に管理することはできません。",
        "私たちはしばしば、相手を悲しませないことまで自分の責任だと考えます。その瞬間、返事は会話ではなく、相手の感情を操作する仕事に変わります。遅れたことを何度も謝り、理由を長く説明し、嫌われていない証拠を言葉の中に詰め込もうとする。すると、一通の返事に必要なエネルギーがさらに大きくなります。",
        "課題を分けるとは、冷たくなることではありません。自分にできるのは、今の状態を正直に伝え、必要なら返事を待ってもらうことです。相手が少し残念に思う可能性まで消すことではありません。相手にも、自分の感情を受け止め、関係について考える力があると信じることでもあります。",
        "まず試せるのは、完璧な返事ではなく、会話を一度止めるための短い返事です。今日は少し余裕がないので、落ち着いたら返します。この一文なら、相手を無視せず、自分の限界も隠しません。詳しく説明するのは、必要になった時で構いません。今すべてを解決しなくてもいいのです。",
        "次に、返事をする時間を自分で決めます。通知が来るたびに反応するのではなく、夜の二十分だけ確認する。急ぎの用事は電話で知らせてもらう。こうした小さなルールは、相手を遠ざける壁ではありません。いつなら落ち着いて向き合えるかを伝える、関係の案内板です。",
        "それでも罪悪感が出てきたら、心の中で一つだけ確認します。今、私は失礼なことをしているのか。それとも、相手が失望する可能性を恐れているだけなのか。この二つは似ていますが、同じではありません。必要な配慮をした後に残る不安まで、すべて責任として抱える必要はありません。",
        "返事が遅れるたびに自分を責める人は、関係を軽く考えているのではありません。むしろ、大切にしようとしすぎて、自分の余白を使い切っていることがあります。だから必要なのは、もっと頑張って早く返すことではなく、どこまでが自分の役割なのかを静かに見直すことです。",
        "今日から、返事の前に相手の気持ちを完璧に整えようとするのを少しだけやめてみてください。誠実な一文を送り、その先の受け取り方は相手に返す。課題を分けることは、関係を壊す勇気ではなく、無理をせず関係に戻るための勇気です。",
        "もし今、返せていないメッセージがあるなら、長い説明を完成させる必要はありません。今は余裕がないけれど、落ち着いたら返したい。その気持ちだけを短く届けてもいいのです。返事の速さではなく、無理のない形で関係に向き合おうとする姿勢が、あなたの誠実さを表します。",
        "あなたは、返事を急がなければならない場面と、少し待ってもらえる場面を分けられていますか。コメントでは、すぐ返す、時間を決めて返す、落ち着いてから返す、今の自分に近いものを一つだけ教えてください。自分の課題を大切にするところから、軽い関係の作り方は始まります。",
    ]
    additions = [
        "相手を尊重することと、相手の気分を背負うことは別です。前者は思いやりですが、後者が続くと自分の気持ちを感じる余裕がなくなります。",
        "短い返事を選ぶ時、自分を正当化する長い理由は必要ありません。事実を一つ伝え、次に話せる時期を示すだけでも、十分に誠実な連絡になります。",
        "境界線は一度で完璧に引けるものではありません。小さく試し、相手との関係に合わせて調整することで、自分にも相手にも分かりやすい形になります。",
        "返事を待つ時間を相手に渡すことは、相手の力を信じることでもあります。すべてを先回りして守ろうとしない関係には、息をつける余白が生まれます。",
    ]
    text = "\n\n".join(paragraphs)
    index = 0
    from .metrics import non_whitespace_chars

    while non_whitespace_chars(text) < 2850:
        text += "\n\n" + additions[index % len(additions)]
        index += 1
    while non_whitespace_chars(text) > 3000:
        cut = text.rfind("\n\n")
        if cut < 0 or non_whitespace_chars(text[:cut]) < 2800:
            break
        text = text[:cut]
    return text


class DemoResourceProvider:
    def research_topics(self, snapshot: dict, performance: dict) -> dict:
        return {
            "channel_positioning": "Tâm lý học ứng dụng cho những khoảnh khắc đời thường của người trưởng thành Nhật Bản.",
            "audience_pains": ["返信を後回しにした罪悪感", "相手の期待を背負いすぎる"],
            "content_gaps": ["応答の遅れを課題の分離で捉える具体例"],
            "trend_hypotheses": [{"hypothesis": "具体的な返信場面は抽象的な心理学より自己認識を生みやすい", "evidence": "既存動画のアドラー心理学関心", "confidence": "medium"}],
            "source_directions": [{"person": "岸見一郎", "work": "嫌われる勇気", "concept": "課題の分離"}],
            "research_notes": ["Demo fixture; production Gemini should validate current sources and competition."],
        }

    def create_topic_candidates(self, research: dict, snapshot: dict, performance: dict, competitor_context: str = "") -> dict:
        return {"candidates": [
            {"id": "T01", "topic": "返信を後回しにしたあとの罪悪感", "audience_moment": "通知を見ても返事ができず、夜に自分を責める", "core_pain": "相手の感情まで管理しようとする", "angle": "課題の分離を返信に応用する", "promise": "背負いすぎた責任を見分けて、短く誠実に返せる", "source_person": "岸見一郎", "source_work": "嫌われる勇気", "source_concept": "課題の分離", "novelty": "具体的な返信場面"},
            {"id": "T02", "topic": "人の期待に応え続けて疲れた夜", "audience_moment": "断れずに予定を埋め尽くす", "core_pain": "期待を裏切る恐れ", "angle": "他者の期待と自分の選択", "promise": "断ることへの罪悪感を整理する", "source_person": "岸見一郎", "source_work": "嫌われる勇気", "source_concept": "課題の分離", "novelty": "日常の断り方"},
            {"id": "T03", "topic": "嫌われるのが怖くて本音を言えない理由", "audience_moment": "会話のあとに言葉を何度も反省する", "core_pain": "評価への依存", "angle": "承認欲求と自由", "promise": "相手の評価を自分の責任から切り離す", "source_person": "岸見一郎", "source_work": "嫌われる勇気", "source_concept": "承認欲求", "novelty": "会話後の反芻"},
            {"id": "T04", "topic": "断ったあとに自分を責めてしまう夜", "audience_moment": "誘いを断った直後にメッセージを読み返す", "core_pain": "境界線への罪悪感", "angle": "断ることと関係の責任", "promise": "境界線を冷たさと混同しない", "source_person": "岸見一郎", "source_work": "嫌われる勇気", "source_concept": "課題の分離", "novelty": "断った直後の感情"},
            {"id": "T05", "topic": "既読がつかないだけで不安になる理由", "audience_moment": "送信後に何度も画面を確認する", "core_pain": "反応を管理できない不安", "angle": "相手の反応と自分の課題", "promise": "待つ時間の不安を整理する", "source_person": "岸見一郎", "source_work": "嫌われる勇気", "source_concept": "課題の分離", "novelty": "送信後の待機時間"},
            {"id": "T06", "topic": "頼まれると断れない人が疲れる理由", "audience_moment": "余裕がないのに仕事を引き受ける", "core_pain": "役に立たなければという恐れ", "angle": "貢献感と自己犠牲の違い", "promise": "引き受ける基準を取り戻す", "source_person": "岸見一郎", "source_work": "幸せになる勇気", "source_concept": "共同体感覚", "novelty": "職場の依頼場面"},
            {"id": "T07", "topic": "会話のあと一人で反省会をする夜", "audience_moment": "帰宅後に自分の発言を繰り返し思い出す", "core_pain": "評価への過剰な想像", "angle": "他者評価を自分の支配外に戻す", "promise": "反芻を止める問いを持つ", "source_person": "岸見一郎", "source_work": "嫌われる勇気", "source_concept": "承認欲求", "novelty": "会話後の一人反省会"},
            {"id": "T08", "topic": "謝りすぎるほど関係が苦しくなる理由", "audience_moment": "小さな遅れにも長い謝罪を送る", "core_pain": "嫌われないための過剰修復", "angle": "誠実さと感情管理を分ける", "promise": "短く必要な謝罪に戻す", "source_person": "岸見一郎", "source_work": "嫌われる勇気", "source_concept": "課題の分離", "novelty": "謝罪メッセージの長文化"},
        ]}

    def select_topic(self, candidates: dict, research: dict, performance: dict) -> dict:
        return {"selected_topic": "返信を後回しにしたあとの罪悪感", "selected_candidate_id": "T01", "selection_reason": "最も具体的な視聴者瞬間と実践可能な心理学の接続があり、9-11分で約束を完結しやすい。", "scores": {"channel_fit": 24, "audience_pain": 19, "packaging_potential": 18, "retention_8_10m": 14, "source_strength": 9, "novelty": 9, "total": 93}, "rejected_topics": [{"candidate_id": "T02", "reason": "状況が広く、thumbnail promise が弱い"}, {"candidate_id": "T03", "reason": "既存の承認欲求テーマと重なりやすい"}], "source_person": "岸見一郎", "source_work": "嫌われる勇気", "source_concept": "課題の分離", "audience_moment": "通知を見ても返事ができず、夜に自分を責める", "promise": "背負いすぎた責任を見分けて、短く誠実に返せる"}

    def lock_source(self, topic: str, snapshot: dict, performance: dict) -> dict:
        return {
            "audience_moment": "返事を後回しにしたあと、相手を失望させた気がして画面を開けない夜",
            "central_emotion": "罪悪感",
            "core_self_insight": "返事ができない背景には、相手の感情まで管理しようとする負担がある",
            "source_person": "岸見一郎",
            "source_work": "嫌われる勇気",
            "source_concept": "課題の分離",
            "verified_sources": [
                {"title": "岸見一郎公式ホームページ", "url": "https://kishimi.com/", "supports": "著者プロフィール"},
                {"title": "嫌われる勇気｜ダイヤモンド社", "url": "https://www.diamond.co.jp/book/9784478025819.html", "supports": "著者と課題の分離を含む目次"},
            ],
            "allowed_paraphrases": ["自分の課題と相手の課題を見分ける"],
            "forbidden_attributions": ["岸見一郎本人が視聴者へ直接助言している表現"],
            "editorial_application": "返信の遅れによる罪悪感へ課題の分離を応用する",
            "overlap_with_recent_videos": "課題の分離は既出だが、返信という新しい生活場面に限定する",
        }

    def create_psychology_brief(self, topic: str, source_pack: dict, performance: dict) -> dict:
        mechanism = source_pack["source_concept"]
        return {
            "phenomenon_or_type": "返信前に相手の反応を考えすぎて動けなくなる人",
            "psychological_identity": "他者の反応まで自分の責任として処理する傾向",
            "core_psychological_question": "なぜ短い返信が大きな心理的仕事になるのか",
            "main_tension": "関係を守ろうとするほど返信できなくなる",
            "recognizable_behavior_signals": ["通知を閉じる", "文面を何度も直す", "遅れるほど罪悪感が増す"],
            "common_misconception": "怠けや無関心",
            "early_reframe": "返事の前に相手の感情まで管理しようとしている",
            "mechanism_candidates": [{"name": mechanism, "role": "responsibility boundary", "source_support": "verified source pack", "confidence": "high"}],
            "selected_mechanisms": [{"name": mechanism, "role": "separate controllable responsibility", "behavior_explained": "返信の過剰準備", "why": "相手の受け取り方まで自分の課題にすると作業が終わらない", "inner_process": "失望させない正解を探し続ける", "evidence_status": "verified"}],
            "causal_chain": ["通知 -> 相手の感情を予測 -> 完璧な返信を探す -> 停止と罪悪感"],
            "inner_process_map": [{"trigger": "通知", "thought_attention_body": "相手の反応へ注意が固定", "response": "返信を保留"}],
            "origin_status": "unsupported", "strength_status": "useful", "cost_status": "required",
            "practical_shift_status": "useful", "route": "PROCESS",
            "exclusions": ["childhood cause", "diagnosis", "fictional protagonist"],
        }

    def create_contract(self, topic: str, source_pack: dict, performance: dict, psychology_brief: dict | None = None) -> dict:
        psychology_brief = psychology_brief or self.create_psychology_brief(topic, source_pack, performance)
        candidates = [
            {"title": "返事をしないだけで、なぜ心が苦しい？", "mechanism": "question", "char_count": 18},
            {"title": "返信できない夜、なぜ心だけが疲れる？", "mechanism": "situation", "char_count": 18},
            {"title": "返事が遅れるほど、罪悪感が重くなる夜", "mechanism": "consequence", "char_count": 18},
        ]
        return {
            "core_self_insight": source_pack["core_self_insight"],
            "central_emotion": "罪悪感",
            "psychological_identity": psychology_brief["psychological_identity"],
            "core_psychological_question": psychology_brief["core_psychological_question"],
            "main_tension": psychology_brief["main_tension"],
            "route": psychology_brief["route"],
            "selected_mechanisms": [item["name"] for item in psychology_brief["selected_mechanisms"]],
            "single_core_promise": "返信の小さな負担が大きくなる理由を理解し、課題の分離で背負いすぎた責任を返す",
            "title_candidates": candidates,
            "chosen_title": candidates[1]["title"],
            "chosen_title_char_count": 18,
            "target_duration_minutes": "9-11",
            "target_char_min": 2400,
            "target_char_max": 4700,
            "hook_contract": {"recognition_by_seconds": 8, "misconception_or_tension_by_seconds": 18, "first_real_insight_by_seconds": 35, "core_question_by_seconds": 55},
            "thumbnail_brief": {"click_question": "なぜ短い返信が怖いのか", "visual_conflict": "通知は小さいのに心の影は大きい", "title_must_not_repeat": "返信できない"},
            "format_lock": {
                "primary_format": "psychological profile / psychological deep-dive",
                "content_center": "một kiểu người — người căng thẳng vì tin nhắn chưa trả lời",
                "primary_narration": "direct psychological explanation",
                "secondary_device": "short behavioral examples",
                "forbidden_spine": [
                    "narrative story",
                    "personal anecdote",
                    "cinematic monologue",
                    "fictional character journey",
                    "chronological life story",
                ],
            },
        }

    def create_plan(self, contract: dict, source_pack: dict, psychology_brief: dict | None = None) -> dict:
        psychology_brief = psychology_brief or {
            "route": contract.get("route", "EXPLANATION"),
            "selected_mechanisms": [{"name": name} for name in contract.get("selected_mechanisms", [])],
        }
        functions = ["recognition", "misconception_reframe", "mechanism", "inner_world", "contradiction", "integration", "practical_shift", "insight_landing"]
        mechanism = psychology_brief["selected_mechanisms"][0]["name"]
        sections = []
        for index, function in enumerate(functions, start=1):
            used = [mechanism] if function in {"mechanism", "inner_world", "contradiction", "integration", "practical_shift"} else []
            sections.append({"id": "S%d" % index, "purpose": function, "psychological_job": function, "behavior_link": "返信行動との接続", "why_answered": "なぜ返信負担が増えるか", "mechanisms_used": used, "example_budget": 1 if function in {"recognition", "mechanism"} else 0, "optional_reason": "core" if function not in {"practical_shift"} else "brief=useful", "new_information": "新しい情報%d" % index, "viewer_question_answered": "問い%d" % index, "state_advance": "理解%d -> 理解%d" % (index - 1, index), "so_what_next": "次の問い%d" % index, "segment_function": function, "estimated_seconds": 65})
        return {
            "route": psychology_brief["route"],
            "retention_blueprint": [
                {"time": "0:00-0:08", "new_information": "通知を見て手が止まる場面", "stay_reason": "自分を認識する", "visual_opportunity": "暗い部屋と小さな通知"},
                {"time": "0:08-0:35", "new_information": "怠けではなく感情管理の負担", "stay_reason": "理解が反転する", "visual_opportunity": "小さな画面と大きな影"},
            ],
            "sections": sections,
            "redundancy_risks": ["同じ安心表現を繰り返さない"],
            "reassurance_lines_used": [],
            "hook_draft": "通知を見た瞬間、返事をしなければと思うのに、指が止まる夜があります。",
            "cta_plan": "三つの返信習慣から一つ選ぶ",
            "planning_quality_gate": {"first_insight_before_35s": True, "first_major_payoff_before_5m": True, "no_duplicate_sections": True, "every_section_advances_state": True, "psychology_is_spine": True, "no_plot_or_character_arc": True, "ending_creates_self_understanding": True},
        }

    def write_script(self, contract: dict, plan: dict, source_pack: dict, psychology_brief: dict | None = None) -> str:
        return _demo_script()

    def review_script(self, contract: dict, plan: dict, source_pack: dict, draft: str, competitor_context: str = "") -> dict:
        # Schema rule v9: bản tái cấu trúc hoàn chỉnh (PHẦN 1–5). Demo giữ nguyên draft.
        verified = non_whitespace_chars(draft)
        return {
            "decision": "pass",
            "optimization_report": "フック、進行、重複表現に問題はない。",
            "score_report": {
                "retention_impact": 10,
                "style_tone": 10,
                "pacing_structure": 10,
                "total": 100,
                "drop_off_points": [],
            },
            "psychology_scorecard": {
                "psychology_spine": 9,
                "mechanism_depth": 9,
                "insight_density": 8,
                "recognition": 8,
                "story_dominance": 1,
                "example_dependency": 1,
                "reframe_signature_count": 2,
                "reasoning": {
                    "psychology_spine": "psychology is the organizing structure",
                    "mechanism_depth": "mechanism explains behavior and inner process",
                    "insight_density": "sections add psychological understanding",
                    "recognition": "behavior is recognizable without plot",
                    "story_dominance": "no chronological story spine",
                    "example_dependency": "examples are supplementary",
                    "reframe_signature": "two clear reframes",
                },
            },
            "restructure_map": [],
            "cut_list": [],
            "revised_draft_clean": draft,
            "revised_draft_vi": "",
            "tts_tag_anchors": [],
            "title_thumbnail_advisory": {"note": "Giữ nguyên title/thumbnail trong contract."},
            "format_alignment": {
                "classification": "A",
                "rationale": "Psychological profile / behavioral pattern analysis.",
            },
            "issues": [],
            "required_changes": [],
            "char_report": {
                "chars": verified,
                "method": "manual_block_count_demo",
                "target_min_chars": target_min_chars_from_contract(contract),
                "status": "ok",
                "shortfall": 0,
            },
        }

    def apply_review(self, contract: dict, plan: dict, source_pack: dict, draft: str, review: dict) -> str:
        return draft

    def audit_script(self, auditor: str, contract: dict, plan: dict, source_pack: dict, script: str) -> dict:
        return {"auditor": auditor, "overall_score": 100, "decision": "pass", "source_alignment": True, "outline_coverage": True, "title_alignment": True, "language_alignment": True, "unsupported_claims": [], "missing_outline_points": [], "issues": [], "summary": "Demo resource is consistent."}

    def repair_script(self, contract: dict, plan: dict, source_pack: dict, script: str, findings: dict) -> dict:
        return {"optimization_report": "Demo repair", "final_script": script}

    def translate_to_vietnamese(self, script: str) -> str:
        return "【Bản dịch tiếng Việt (DEMO) — production dịch đầy đủ qua DeepSeek】\n" + script[:300]

    def create_thumbnail(self, contract: dict, script: str, competitor_context: str = "") -> dict:
        return {
            "concepts": [
                {"mode": "SELF_RECOGNITION", "text": "胸の重さ", "scene": "通知を見る女性", "emotion": "罪悪感", "score": 88},
                {"mode": "CONTRADICTION", "text": "返せない", "scene": "小さな通知と大きな影", "emotion": "緊張", "score": 85},
                {"mode": "CONSEQUENCE_OR_RELIEF", "text": "もう背負わない", "scene": "携帯を置いて息をする", "emotion": "安堵", "score": 82},
            ],
            "chosen_mode": "SELF_RECOGNITION",
            "thumbnail_text": "胸の重さ",
            "title_carries": "返信できない夜の状況",
            "thumbnail_carries": "言葉にできない重さ",
            "text_color": "#FFFFFF",
            "background_color": "#1A2332",
            "image_prompt": "A fictional anonymous gender-neutral illustrated character looking at a phone notification with visible hesitation, flat illustrated cartoon style, thick black outline, solid colors, no gradients or realistic shading, navy #1A2332 background, subject on the right with clean negative space on the left, 16:9 full bleed, no text, no logo, no watermark, not resembling any identifiable real person.",
            "negative_prompt": "text, logo, watermark, recognizable public figure, exact likeness, extra fingers, distorted hands, low contrast, cluttered background",
            "overlay_spec": {"lines": 1, "font_weight": "heavy", "height_percent": 14, "position": "left", "safe_margin_percent": 5},
            "manual_squint_test": "PENDING_USER",
        }

    def create_image_strategy(self, contract: dict, plan: dict, thumbnail: dict) -> dict:
        beats = []
        # 49 beats / 42 ảnh unique = mật độ tối thiểu cho 9-11 phút theo
        # derive_visual_density_targets (front-loaded schedule), để demo tự vượt qua validation.
        for index in range(1, 50):
            image_number = index if index <= 42 else ((index - 43) % 42) + 1
            beats.append({"id": "B%02d" % index, "time": "DRAFT_TIMING", "script_section": "S%d" % min(8, ((index - 1) // 6) + 1), "visual_information": "視覚情報%d" % index, "mode": "literal" if index % 3 else "contrast", "new_image": index <= 42, "reuse_image_id": None if index <= 42 else "IMG-%02d" % image_number})
        return {"style_bible": "flat illustrated cartoon, thick black outline, solid colors, no gradients, navy #1A2332 background, strong readable contrast", "character_bible": "anonymous gender-neutral illustrated character, simple flat shapes, no facial detail beyond expression", "environment_bible": "minimal flat Japanese interior, solid color blocks", "opening_visual_contract": {"thumbnail_scene": thumbnail["concepts"][0]["scene"], "first_frame_scene": "通知を見る女性", "first_15s_visuals": ["phone detail", "frozen hand", "large shadow"]}, "estimated_unique_images": 42, "estimated_total_visual_events": 49, "mascot_ratio": 0.0, "density_check": True, "no_filler_check": True, "visual_beats": beats}

    def create_image_prompts(self, strategy: dict, contract: dict) -> dict:
        images = []
        for beat in strategy["visual_beats"]:
            if not beat["new_image"]:
                continue
            images.append({"image_id": beat["image_id"], "beat_ids": [beat["id"]], "prompt": "%s: an anonymous gender-neutral illustrated character in a minimal flat Japanese interior, one clear psychological action, flat illustrated cartoon style, thick black outline, solid colors, no gradients or realistic shading, navy #1A2332 background, consistent character design, 16:9 full bleed. Negative: text, logo, watermark, extra fingers, distorted hands, duplicate subject, photorealism, gradients, realistic shading, low contrast, clutter." % beat["visual_information"]})
        storyboard = []
        for index, beat in enumerate(strategy["visual_beats"], start=1):
            storyboard.append({"event_id": "E%02d" % index, "time": beat.get("time", "DRAFT_TIMING"), "beat_id": beat["id"], "image_id": beat["image_id"], "new_image": bool(beat["new_image"]), "motion": "slow push-in" if index % 2 else "gentle pan", "visual_information": beat["visual_information"]})
        return {"images": images, "storyboard": storyboard}

    def create_publish_draft(self, contract: dict, source_pack: dict) -> dict:
        return {"description_draft": "返事を後回しにしたあと、罪悪感で画面を開けなくなることはありませんか。\nこの動画では、課題の分離という考え方から、背負いすぎた責任を見直します。", "chapters_status": "DRAFT_OMITTED", "pinned_comment": "返事をする時、今の自分に近いのはどれですか？ ①すぐ返す ②時間を決める ③落ち着いてから返す", "hashtags": ["#人間関係", "#アドラー心理学", "#メンタルケア"], "tags": ["返信", "罪悪感", "課題の分離", "人間関係"], "source_note": "参考：岸見一郎・古賀史健『嫌われる勇気』"}