from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Mapping, Protocol, Sequence, TypeVar

from ..config import Settings
from ..model_router import ModelRouter, ModelProfile
from .metrics import non_whitespace_chars
from .sections import split_tts_chunks
from .validation import derive_visual_density_targets
from ..infrastructure.model_trace import (
    restore_trace_context,
    snapshot_trace_context,
    trace_parsed_response,
    trace_raw_response,
    trace_request,
)
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
    image_strategy_foundation_prompt,
    image_strategy_chunk_prompt,
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
    writing_movement_prompt,
    writing_prompt,
)

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

# Class-level guard so instances built via ``__new__`` (tests, hot reloads)
# still get a working lock around the shared client cache.
_CLIENT_CREATE_LOCK = threading.Lock()

# Independent provider calls (translation chunks, image-prompt batches,
# per-movement audits/repairs) have no cross-item reasoning dependency, so they
# run concurrently. 4 workers keeps useful overlap while staying polite with
# provider rate limits; each task is one bounded request.
_PARALLEL_MODEL_WORKERS = 4


def _run_provider_tasks_parallel(tasks: Sequence[Callable[[], _T]]) -> list[_T]:
    """Run independent model calls concurrently, preserving input order.

    Order preservation matters: translation chunks are joined in sequence and
    image batches must keep their beat order. The first raised exception is
    re-raised so the stage engine keeps its single retry-owner contract.
    """
    if not tasks:
        return []
    if len(tasks) == 1:
        return [tasks[0]()]
    snapshot = snapshot_trace_context()
    results: list[Any] = [None] * len(tasks)

    def _worker(index: int, task: Callable[[], _T]) -> None:
        restore_trace_context(snapshot)
        results[index] = task()

    workers = min(_PARALLEL_MODEL_WORKERS, len(tasks))
    first_error: BaseException | None = None
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_worker, index, task) for index, task in enumerate(tasks)]
        for future in futures:
            try:
                future.result()
            except BaseException as exc:  # noqa: BLE001 - re-raised below in order
                if first_error is None:
                    first_error = exc
    if first_error is not None:
        raise first_error
    return results


def _image_strategy_contract(contract: dict) -> dict:
    """Keep image-strategy requests focused on visual decisions, not sources."""
    return {
        key: contract[key]
        for key in (
            "chosen_title",
            "core_psychological_question",
            "psychological_identity",
            "central_emotion",
            "main_tension",
            "selected_mechanisms",
            "content_spine",
            "recognition_device",
            "thumbnail_brief",
            "format_lock",
            "visual_duration_seconds",
            "visual_duration_source",
        )
        if key in contract
    }


def _thumbnail_context(thumbnail: dict) -> dict:
    """Pass only the thumbnail facts that establish visual continuity."""
    return {
        key: thumbnail[key]
        for key in ("thumbnail_text", "image_prompt", "negative_prompt", "concepts", "overlay_spec")
        if key in thumbnail
    }


def _image_strategy_section(section: dict) -> dict:
    return {
        key: section[key]
        for key in (
            "id", "segment_function", "psychological_job", "behavior_link",
            "new_information", "state_advance", "so_what_next", "mechanisms_used",
        )
        if key in section
    }


def _allocate_visual_events(total: int, weights: list[Any]) -> list[int]:
    """Allocate the validated floor exactly, with every movement represented."""
    count = len(weights)
    if count == 0:
        return []
    total = max(total, count)
    normalized = []
    for weight in weights:
        try:
            normalized.append(max(0.1, float(weight)))
        except (TypeError, ValueError):
            normalized.append(1.0)
    base = [1] * count
    remaining = total - count
    weight_total = sum(normalized)
    raw = [remaining * weight / weight_total for weight in normalized]
    allocation = [minimum + int(value) for minimum, value in zip(base, raw)]
    remainder = remaining - sum(int(value) for value in raw)
    for index in sorted(
        range(count), key=lambda item: (raw[item] - int(raw[item]), -item), reverse=True
    )[:remainder]:
        allocation[index] += 1
    return allocation


def _renumber_visual_chunk(chunk_beats: list[dict], start: int, section_id: str) -> list[dict]:
    """Turn chunk-local IDs into one globally ordered, reusable beat sequence."""
    local_to_global: dict[str, str] = {}
    for offset, beat in enumerate(chunk_beats):
        local_id = str(beat.get("id") or "")
        if not local_id:
            raise ValueError("Visual chunk chứa beat không có id.")
        if local_id in local_to_global:
            raise ValueError("Visual chunk chứa beat id trùng: %s." % local_id)
        local_to_global[local_id] = "B%03d" % (start + offset)

    normalized: list[dict] = []
    for offset, raw in enumerate(chunk_beats):
        beat = dict(raw)
        local_id = str(beat["id"])
        beat["id"] = local_to_global[local_id]
        beat["script_section"] = section_id
        if bool(beat.get("new_image")):
            beat["reuse_image_id"] = None
        else:
            reuse = str(beat.get("reuse_image_id") or "")
            target = local_to_global.get(reuse)
            if target is None:
                raise ValueError(
                    "Visual chunk %s reuse ảnh ngoài chunk hoặc không tồn tại: %s."
                    % (local_id, reuse)
                )
            if list(local_to_global).index(reuse) >= offset:
                raise ValueError("Visual chunk %s chỉ được reuse beat đứng trước." % local_id)
            beat["reuse_image_id"] = target
        normalized.append(beat)
    return normalized


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
    def create_contract(self, topic: str, source_pack: dict, performance: dict, psychology_brief: dict, validation_feedback: str = "") -> dict: ...
    def create_plan(self, contract: dict, source_pack: dict, psychology_brief: dict, validation_feedback: str = "") -> dict: ...
    def write_script(self, contract: dict, plan: dict, source_pack: dict, psychology_brief: dict | None = None) -> str: ...
    def write_script_movements(self, contract: dict, plan: dict, source_pack: dict, psychology_brief: dict | None = None) -> list[dict]: ...
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
    def __init__(self, settings: Settings, routing_snapshot: dict[str, Any] | None = None) -> None:
        try:
            from openai import OpenAI
        except ImportError:
            OpenAI = None
        self.settings = settings
        self.router = (
            ModelRouter.from_snapshot(settings, routing_snapshot)
            if routing_snapshot
            else ModelRouter(settings)
        )
        self._OpenAI = OpenAI
        self._clients: dict[tuple[str, str, str], Any] = {}

    @property
    def max_retries(self) -> int:
        return self.settings.max_retries

    def _legacy_router(self):
        if not hasattr(self, "router"):
            self.router = ModelRouter(self.settings)
        return self.router

    def _gemini_json(self, label: str, system: str, prompt: str, temperature: float = 0.2, model: str | None = None) -> dict:
        """Backward-compatible test/integration hook; production routes through ModelRouter."""
        router = self._legacy_router()
        profile = router.profile_for("analysis")
        if model:
            profile = ModelProfile("gemini", model, profile.base_url, profile.api_key_env, temperature, profile.max_output_tokens, profile.api_key, profile.profile_name)
        trace_request(label, label, "Gemini", profile.model, system, prompt, temperature)
        response = self._gemini_generate(profile, prompt, system, label, True)
        raw = response.text
        trace_raw_response(label, label, raw)
        value = parse_json_object(raw)
        trace_parsed_response(label, label, value)
        return value

    def _deepseek_json(self, label: str, system: str, prompt: str, temperature: float = 0.0) -> dict:
        self._legacy_router()
        return self._call_json("writer", label, system, prompt)

    def _deepseek_text(self, label: str, system: str, prompt: str, temperature: float = 0.7) -> str:
        return self._call_text("writer", label, system, prompt, temperature)

    def _deepseek_text_messages(
        self,
        label: str,
        system: str,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
    ) -> str:
        return self._call_text_messages("editor", label, system, messages, temperature)

    def _client_for(self, profile: ModelProfile) -> Any:
        api_key = self.router.resolve_api_key(profile)
        key = (profile.provider, api_key, profile.base_url)
        with _CLIENT_CREATE_LOCK:
            if key in self._clients:
                return self._clients[key]
        client = self._build_client(profile, api_key)
        with _CLIENT_CREATE_LOCK:
            self._clients.setdefault(key, client)
            return self._clients[key]

    def _build_client(self, profile: ModelProfile, api_key: str) -> Any:
        if profile.provider == "gemini":
            from google import genai
            return genai.Client(api_key=api_key)
        if profile.provider == "openai_compatible":
            if self._OpenAI is None:
                raise RuntimeError("Thiếu SDK openai; cài package openai để dùng provider openai_compatible.")
            # The engine owns retries. Bound a stalled upstream request so a
            # run records a retryable failure instead of remaining "running"
            # for the SDK's multi-minute default timeout.
            return self._OpenAI(api_key=api_key, base_url=profile.base_url or None, timeout=180.0, max_retries=0)
        raise ValueError(f"Provider không hỗ trợ: {profile.provider}")

    def _gemini_generate(self, profile: ModelProfile, contents: str, system: str, label: str, json_mode: bool) -> Any:
        from google.genai import types
        # The stage engine is the sole retry owner. Retrying here as well used
        # to multiply a 3-attempt stage into up to 9 model calls and minutes of
        # hidden backoff, while giving the UI no truthful retry budget.
        client = self._client_for(profile)
        config_kwargs = {
            "system_instruction": system,
            "response_mime_type": "application/json" if json_mode else None,
            "temperature": profile.temperature,
            "thinking_config": types.ThinkingConfig(thinking_level="high"),
        }
        if profile.max_output_tokens:
            config_kwargs["max_output_tokens"] = profile.max_output_tokens
        return client.models.generate_content(
            model=profile.model,
            contents=contents,
            config=types.GenerateContentConfig(**config_kwargs),
        )

    def _call_json(self, role: str, label: str, system: str, prompt: str) -> dict:
        if not hasattr(self, "router"):
            legacy = {"analysis": "_gemini_json", "reviewer": "_gemini_json", "auditor": "_gemini_json", "writer": "_deepseek_json", "editor": "_deepseek_json", "packaging": "_deepseek_json"}[role]
            return getattr(self, legacy)(label, system, prompt)
        profile = self.router.profile_for(role)
        trace_request(label, label, profile.provider, profile.model, system, prompt, profile.temperature)
        if profile.provider == "gemini":
            response = self._gemini_generate(profile, prompt, system, label, True)
            raw = response.text
        else:
            client = self._client_for(profile)
            kwargs = {
                "model": profile.model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                "temperature": profile.temperature,
                "response_format": {"type": "json_object"},
            }
            # Large visual JSON is the one stage where an uncapped response can
            # run for many minutes and be cut inside a quoted prompt. Respect
            # the UI-configured cap; otherwise apply a bounded stage default.
            # Image prompts are requested in bounded batches below. Do not
            # impose a hard token budget on those calls; batching is the size
            # control and avoids truncating a valid JSON string.
            output_limit = (
                None
                if label.startswith(("RP_IMAGE_STRATEGY", "RP_IMAGE_PROMPTS"))
                else profile.max_output_tokens
            )
            if output_limit:
                kwargs["max_tokens"] = int(output_limit)
            response = client.chat.completions.create(**kwargs)
            raw = response.choices[0].message.content or ""
        trace_raw_response(label, label, raw)
        value = parse_json_object(raw)
        trace_parsed_response(label, label, value)
        logger.info("Resource provider complete | stage=%s | role=%s | provider=%s | model=%s", label, role, profile.provider, profile.model)
        return value

    def _call_text(self, role: str, label: str, system: str, prompt: str, temperature_override: float | None = None) -> str:
        if not hasattr(self, "router"):
            self._legacy_router()
        profile = self.router.profile_for(role)
        temperature = profile.temperature if temperature_override is None else temperature_override
        trace_request(label, label, profile.provider, profile.model, system, prompt, temperature)
        if profile.provider == "gemini":
            response = self._gemini_generate(
                ModelProfile(profile.provider, profile.model, profile.base_url, profile.api_key_env, temperature, profile.max_output_tokens, profile.api_key, profile.profile_name),
                prompt, system, label, False
            )
            value = response.text or ""
        else:
            client = self._client_for(profile)
            kwargs = {
                "model": profile.model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                "temperature": temperature,
            }
            if profile.max_output_tokens:
                kwargs["max_tokens"] = profile.max_output_tokens
            response = client.chat.completions.create(**kwargs)
            value = response.choices[0].message.content or ""
        if not value.strip():
            raise ValueError(f"{label}: model trả nội dung rỗng.")
        result = value.strip()
        trace_raw_response(label, label, result)
        trace_parsed_response(label, label, result)
        logger.info("Resource provider complete | stage=%s | role=%s | provider=%s | model=%s", label, role, profile.provider, profile.model)
        return result

    def _call_text_messages(self, role: str, label: str, system: str, messages: list[dict[str, str]], temperature_override: float | None = None) -> str:
        if not hasattr(self, "router"):
            if "_deepseek_text_messages" in self.__dict__:
                return self.__dict__["_deepseek_text_messages"](label, system, messages, temperature_override or 0.2)
            self._legacy_router()
        profile = self.router.profile_for(role)
        temperature = profile.temperature if temperature_override is None else temperature_override
        trace_request(label, label, profile.provider, profile.model, system, json.dumps(messages, ensure_ascii=False), temperature)
        if profile.provider == "gemini":
            # A Gemini follow-up is represented as one prompt to keep the provider abstraction portable.
            merged = "\n\n".join(f"{m.get('role','user').upper()}: {m.get('content','')}" for m in messages)
            response = self._gemini_generate(
                ModelProfile(profile.provider, profile.model, profile.base_url, profile.api_key_env, temperature, profile.max_output_tokens, profile.api_key, profile.profile_name),
                merged, system, label, False
            )
            value = response.text or ""
        else:
            client = self._client_for(profile)
            response = client.chat.completions.create(
                model=profile.model,
                messages=[{"role": "system", "content": system}, *messages],
                temperature=temperature,
            )
            value = response.choices[0].message.content or ""
        if not value.strip():
            raise ValueError(f"{label}: model trả nội dung rỗng.")
        result = value.strip()
        trace_raw_response(label, label, result)
        trace_parsed_response(label, label, result)
        return result

    def research_topics(self, snapshot: dict, performance: dict) -> dict:
        return self._call_json("analysis", "RP_TOPIC_RESEARCH", TOPIC_RESEARCH_SYSTEM, topic_research_prompt(snapshot, performance))

    def create_topic_candidates(self, research: dict, snapshot: dict, performance: dict, competitor_context: str = "") -> dict:
        return self._call_json("analysis", "RP_TOPIC_CANDIDATES", TOPIC_RESEARCH_SYSTEM, topic_candidates_prompt(research, snapshot, performance, competitor_context))

    def select_topic(self, candidates: dict, research: dict, performance: dict) -> dict:
        return self._call_json("analysis", "RP_TOPIC_SELECTION", TOPIC_SELECTION_SYSTEM, topic_selection_prompt(candidates, research, performance))

    def lock_source(self, topic: str, snapshot: dict, performance: dict) -> dict:
        return self._call_json("analysis", "RP_SOURCE_LOCK", SOURCE_SYSTEM, source_prompt(topic, snapshot, performance))

    def create_psychology_brief(self, topic: str, source_pack: dict, performance: dict) -> dict:
        return self._call_json("analysis", "RP_PSYCHOLOGY_BRIEF", PSYCHOLOGY_BRIEF_SYSTEM, psychology_brief_prompt(topic, source_pack, performance))

    def create_contract(self, topic: str, source_pack: dict, performance: dict, psychology_brief: dict | None = None, validation_feedback: str = "") -> dict:
        brief = _normalize_psychology_context(psychology_brief)
        label = "RP_SCRIPT_CONTRACT_REPAIR" if validation_feedback else "RP_SCRIPT_CONTRACT"
        return self._call_json(
            "writer",
            label,
            CONTRACT_SYSTEM,
            contract_prompt(topic, source_pack, performance, brief, validation_feedback),
        )

    def create_plan(self, contract: dict, source_pack: dict, psychology_brief: dict | None = None, validation_feedback: str = "") -> dict:
        brief = _normalize_psychology_context(psychology_brief)
        label = "RP_PLANNING_REPAIR" if validation_feedback else "RP_PLANNING"
        return self._call_json(
            "writer", label, PLANNING_SYSTEM,
            planning_prompt(contract, source_pack, brief, validation_feedback),
        )

    def write_script_movements(self, contract: dict, plan: dict, source_pack: dict, psychology_brief: dict | None = None) -> list[dict]:
        brief = _normalize_psychology_context(psychology_brief)
        target_min = int(contract.get("target_char_min") or 0)
        sections = [section for section in plan.get("sections", []) if isinstance(section, dict)]
        # Long-form targets exceed the reliable single-response budget of several
        # OpenAI-compatible providers. Generate coherent movements instead of
        # letting an otherwise valid script die as truncated output.
        if target_min >= 8000 and len(sections) >= 2:
            try:
                target_total = int(contract.get("target_char_max") or target_min)
            except (TypeError, ValueError):
                target_total = target_min
            target_total = max(target_min, target_total)
            weights = []
            for section in sections:
                try:
                    weights.append(max(0.1, float(section.get("relative_weight", 1.0))))
                except (TypeError, ValueError):
                    weights.append(1.0)
            weight_total = sum(weights)
            previous_tail = ""
            movements: list[dict] = []
            for index, (section, weight) in enumerate(zip(sections, weights)):
                # 1,200 chars leaves enough room for a meaningful movement while
                # preserving the relative weights selected by planning.
                movement_target = max(1200, round(target_total * weight / weight_total))
                logger.info(
                    "Long-form writing movement | %d/%d | section=%s | target_chars=%d",
                    index + 1, len(sections), section.get("id", "S%d" % (index + 1)), movement_target,
                )
                movement = self._call_text(
                    "writer",
                    "RP_WRITING_MOVEMENT_%02d" % (index + 1),
                    WRITING_SYSTEM,
                    writing_movement_prompt(
                        contract, source_pack, brief, section, previous_tail,
                        movement_target, index == 0, index == len(sections) - 1,
                    ),
                    0.7,
                ).strip()
                if not movement:
                    raise ValueError("Writing movement %d trả về rỗng." % (index + 1))
                movements.append({
                    "id": str(section.get("id") or "S%d" % (index + 1)),
                    "target_chars": movement_target,
                    "text": movement,
                })
                previous_tail = movement[-900:]
            return movements
        text = self._call_text("writer", "RP_WRITING", WRITING_SYSTEM, writing_prompt(contract, plan, source_pack, brief), 0.7)
        return [{"id": "S1", "target_chars": target_min, "text": text.strip()}]

    def write_script(self, contract: dict, plan: dict, source_pack: dict, psychology_brief: dict | None = None) -> str:
        """Compatibility API for callers that only consume a joined draft."""
        return "\n\n".join(
            str(item.get("text") or "").strip()
            for item in self.write_script_movements(contract, plan, source_pack, psychology_brief)
            if str(item.get("text") or "").strip()
        )

    def review_script(self, contract: dict, plan: dict, source_pack: dict, draft: str, competitor_context: str = "") -> dict:
        return self._call_json("reviewer", "RP_REVIEW", REVIEW_SYSTEM, review_prompt(contract, plan, source_pack, draft, competitor_context))

    def apply_review(self, contract: dict, plan: dict, source_pack: dict, draft: str, review: dict) -> str:
        original_prompt = writing_prompt(contract, plan, source_pack, {
            "psychological_identity": contract.get("psychological_identity"),
            "core_psychological_question": contract.get("core_psychological_question"),
            "main_tension": contract.get("main_tension"),
            "route": contract.get("route"),
            "selected_mechanisms": [{"name": name} for name in contract.get("selected_mechanisms", [])],
        })
        follow_up = apply_review_prompt(contract, plan, source_pack, draft, review)
        return self._call_text_messages("editor", "RP_APPLY_REVIEW", WRITING_SYSTEM, [
            {"role": "user", "content": original_prompt},
            {"role": "assistant", "content": draft},
            {"role": "user", "content": follow_up},
        ], 0.2)

    def audit_script(self, auditor: str, contract: dict, plan: dict, source_pack: dict, script: str) -> dict:
        if auditor != "auditor":
            raise ValueError("audit_script chỉ nhận logical role 'auditor'.")
        prompt = audit_prompt(auditor, contract, plan, source_pack, script)
        result = self._call_json("auditor", "RP_AUDIT", AUDIT_SYSTEM, prompt)
        if hasattr(self, "router"):
            profile = self.router.profile_for("auditor")
            result["routing"] = {
                "role": "auditor",
                "profile": profile.profile_name,
                "provider": profile.provider,
                "model": profile.model,
            }
        return result

    def repair_script(self, contract: dict, plan: dict, source_pack: dict, script: str, findings: dict) -> dict:
        return self._call_json("editor", "RP_REPAIR", REPAIR_SYSTEM, repair_prompt(contract, plan, source_pack, script, findings))

    def translate_to_vietnamese(self, script: str) -> str:
        # A 35-45 minute Japanese narration can exceed 18k characters. Sending
        # it as one translation request regularly exceeds gateway timeouts even
        # though the writer model is healthy. Translation has no cross-chunk
        # reasoning dependency, so use conservative sentence-safe requests and
        # run the chunks concurrently.
        if non_whitespace_chars(script) <= 3600:
            return self._call_text("writer", "RP_TRANSLATE_VI", TRANSLATE_SYSTEM, vietnamese_translation_prompt(script), 0.3)
        chunks = split_tts_chunks(script, max_chars=3200)

        def _translate_chunk(chunk: object) -> str:
            label = "RP_TRANSLATE_VI_CHUNK_%03d" % chunk.index
            logger.info(
                "Vietnamese translation chunk start | %d/%d | chars=%s",
                chunk.index, len(chunks), chunk.chars,
            )
            return self._call_text(
                "writer", label, TRANSLATE_SYSTEM, vietnamese_translation_prompt(chunk.text), 0.3
            )

        translated = _run_provider_tasks_parallel(
            [lambda chunk=chunk: _translate_chunk(chunk) for chunk in chunks]
        )
        return "\n\n".join(translated)

    def create_thumbnail(self, contract: dict, script: str, competitor_context: str = "") -> dict:
        return self._call_json("packaging", "RP_THUMBNAIL", THUMBNAIL_SYSTEM, thumbnail_prompt(contract, script, competitor_context))

    def create_image_strategy(self, contract: dict, plan: dict, thumbnail: dict) -> dict:
        # Long-form runs may require 100+ beats. A single JSON response for
        # all of them regularly exceeds gateway timeouts or truncates inside a
        # quoted visual description. Keep a small shared foundation and make
        # one bounded request per planning movement instead.
        foundation = self._call_json(
            "packaging",
            "RP_IMAGE_STRATEGY_FOUNDATION",
            IMAGE_SYSTEM,
            image_strategy_foundation_prompt(_image_strategy_contract(contract), _thumbnail_context(thumbnail)),
        )
        sections = [section for section in plan.get("sections", []) if isinstance(section, dict)]
        if not sections:
            sections = [{"id": "S1", "psychological_job": "visual coverage", "relative_weight": 1.0}]
        targets = derive_visual_density_targets(contract, plan)
        allocations = _allocate_visual_events(
            int(targets["minimum_visual_events"]),
            [section.get("relative_weight", 1.0) for section in sections],
        )
        logger.info(
            "Image strategy chunk plan | chunks=%d | target_events=%d | allocation=%s",
            len(sections), targets["minimum_visual_events"], allocations,
        )
        beats: list[dict] = []

        def _render_strategy_chunk(index: int, section: dict, target_events: int) -> list[dict]:
            logger.info(
                "Image strategy chunk start | chunk=%d/%d | section=%s | target_events=%d",
                index, len(sections), section.get("id", "S1"), target_events,
            )
            result = self._call_json(
                "packaging",
                "RP_IMAGE_STRATEGY_CHUNK_%02d" % index,
                IMAGE_SYSTEM,
                image_strategy_chunk_prompt(
                    _image_strategy_contract(contract),
                    _image_strategy_section(section),
                    foundation,
                    target_events,
                    index,
                ),
            )
            chunk_beats = result.get("visual_beats")
            if not isinstance(chunk_beats, list) or len(chunk_beats) != target_events:
                actual = len(chunk_beats) if isinstance(chunk_beats, list) else "invalid"
                raise ValueError(
                    "RP_IMAGE_STRATEGY_CHUNK_%02d phải trả đúng %d visual_beats, nhận %s."
                    % (index, target_events, actual)
                )
            logger.info(
                "Image strategy chunk complete | chunk=%d/%d | section=%s | beats=%d",
                index, len(sections), section.get("id", "S1"), len(chunk_beats),
            )
            return chunk_beats

        # Chunks share only the read-only foundation; numbering is applied
        # afterwards in section order so concurrency cannot reorder IDs.
        chunk_results = _run_provider_tasks_parallel([
            lambda index=index, section=section, target_events=target_events: _render_strategy_chunk(
                index, section, target_events
            )
            for index, (section, target_events) in enumerate(zip(sections, allocations), start=1)
        ])
        for section, chunk_beats in zip(sections, chunk_results):
            beats.extend(_renumber_visual_chunk(chunk_beats, len(beats) + 1, str(section.get("id") or "S1")))
        return {
            "style_bible": str(foundation.get("style_bible", "")),
            "character_bible": str(foundation.get("character_bible", "")),
            "environment_bible": str(foundation.get("environment_bible", "")),
            "opening_visual_contract": foundation.get("opening_visual_contract") or {},
            "estimated_unique_images": 0,
            "estimated_total_visual_events": len(beats),
            "mascot_ratio": 0.25,
            "density_check": True,
            "no_filler_check": True,
            "visual_beats": beats,
            "generation_policy": {
                "mode": "section_chunks",
                "chunk_count": len(sections),
                "target_visual_events": int(targets["minimum_visual_events"]),
            },
        }

    def create_image_prompts(self, strategy: dict, contract: dict) -> dict:
        beats = [beat for beat in strategy.get("visual_beats", []) if bool(beat.get("new_image"))]
        if not beats:
            return {"images": [], "storyboard": []}

        # Keep each provider response deliberately small. The strategy is the
        # authoritative research/editorial output; this stage only translates
        # locked visual_information into image-model syntax. Storyboard rows
        # are generated locally from the full strategy. Batches share no state,
        # so they run concurrently; results stay in beat order.
        batch_size = 4
        total_batches = (len(beats) + batch_size - 1) // batch_size

        def _render_batch(batch_number: int, batch: list[dict]) -> list[dict]:
            batch_strategy = {
                "style_bible": strategy.get("style_bible", ""),
                "character_bible": strategy.get("character_bible", ""),
                "environment_bible": strategy.get("environment_bible", ""),
                "visual_beats": batch,
            }
            label = "RP_IMAGE_PROMPTS_%03d" % batch_number
            expected_ids = [str(beat["image_id"]) for beat in batch]
            logger.info(
                "Image prompts batch start | batch=%d | total_batches=%d | image_ids=%s",
                batch_number, total_batches, ",".join(expected_ids),
            )
            result = self._call_json(
                "packaging",
                label,
                IMAGE_SYSTEM,
                image_prompts_prompt(batch_strategy, _image_strategy_contract(contract)),
            )
            batch_images = result.get("images")
            if not isinstance(batch_images, list):
                raise ValueError("%s phải trả field images dạng list." % label)
            received_ids = [str(item.get("image_id", "")) for item in batch_images if isinstance(item, dict)]
            if received_ids != expected_ids:
                raise ValueError(
                    "%s phải trả đúng image IDs theo thứ tự %s, nhận %s."
                    % (label, ",".join(expected_ids), ",".join(received_ids) or "none")
                )
            logger.info(
                "Image prompts batch done | batch=%d | images=%d",
                batch_number, len(batch_images),
            )
            return batch_images

        batches = [
            (start // batch_size + 1, beats[start:start + batch_size])
            for start in range(0, len(beats), batch_size)
        ]
        batch_results = _run_provider_tasks_parallel(
            [lambda n=n, b=b: _render_batch(n, b) for n, b in batches]
        )
        images = [image for batch_images in batch_results for image in batch_images]
        return {"images": images, "storyboard": []}

    def create_publish_draft(self, contract: dict, source_pack: dict) -> dict:
        return self._call_json("packaging", "RP_PUBLISH_DRAFT", PUBLISH_SYSTEM, publish_prompt(contract, source_pack))


def _demo_script() -> str:
    paragraphs = [
        "通知を見た瞬間、返事をしなければと思うのに、指が止まってしまう夜があります。短い一文を送るだけなのに、胸の奥が重くなり、画面を閉じてしまう。時間がたつほど罪悪感は大きくなり、今さら何と返せばいいのか分からなくなる。これは、単に怠けているから起きるのでしょうか。",
        "実際には、返事を書く前から心の中で多くの仕事が始まっています。相手はどんな気持ちで送ったのか。短すぎると冷たく見えないか。絵文字を付けるべきか。すぐ会話が続いたら対応できるか。一つの通知の後ろにある可能性を先回りして考えるほど、返事は小さな作業ではなくなります。",
        "特に、人の表情や声の変化に敏感な人は、文章に書かれていない気持ちまで読み取ろうとします。相手を大切にしたい気持ちが強いからこそ、正しい返事を探し続けます。しかし、正解のないものに正解を求めると、心は動けなくなります。返せないのではなく、失敗しない返事を作ろうとして疲れているのです。",
        "ここで役に立つのが、アドラー心理学で語られる課題の分離という考え方です。岸見一郎と古賀史健の著書『嫌われる勇気』では、自分が引き受ける課題と、相手が引き受ける課題を見分ける大切さが説明されています。これは人を切り捨てるためではなく、関係を無理なく続けるための境界線です。",
        "返事をいつ、どのような言葉で送るかは、自分が選ぶ課題です。一方、その返事を読んで相手がどう感じるかは、最終的には相手の課題です。もちろん、乱暴な言葉を使わない配慮は必要です。しかし、どれほど丁寧に書いても、相手の受け取り方を完全に管理することはできません。",
        "私たちはしばしば、相手を悲しませないことまで自分の責任だと考えます。その瞬間、返事は会話ではなく、相手の感情を操作する仕事に変わります。遅れたことを何度も謝り、理由を長く説明し、嫌われていない証拠を言葉の中に詰め込もうとする。すると、一通の返事に必要なエネルギーがさらに大きくなります。",
        "この負担を見分けるには、返事の内容と、返事を読んだ相手の気持ちを分けて考える必要があります。内容には自分の配慮を反映できますが、相手がどう受け取るかまで完全に決めることはできません。そこを一つの仕事として抱えると、送信前の確認が増え、短く答えられる場面でも説明が長くなります。やがて、丁寧にしたいという意図そのものが、返事を遅らせる力に変わります。大切なのは配慮を捨てることではなく、自分が選べる部分と、相手に返す部分を同じ重さで扱わないことです。",
        "返事をする前に、まず自分へ二つだけ尋ねることもできます。今必要なのは、事実を伝えることなのか、それとも相手が悪く思わない保証を作ることなのか。前者なら一文で終えられます。後者まで自分の仕事にすると、どれだけ書いても不安は完全には消えません。確認するほど誠実になるとは限らず、確認の目的が相手の反応を管理することに変わった時、負担だけが増えていきます。",
        "この違いに気づくと、返事の遅れは性格の欠陥ではなく、責任の範囲が広がりすぎたサインとして見えてきます。必要な配慮は残しながら、相手の感情を自分の課題へ戻さない。その境界が、返事を始めるための余白になります。",
        "返事を急ぐことと、誠実に向き合うことも同じではありません。速さだけで誠実さを測る必要はないのです。短くても、できる範囲を正直に伝えれば十分です。焦らなくていいのです。今の余白を守ることも誠実さです。",
        "課題を分けるとは、冷たくなることではありません。自分にできるのは、今の状態を正直に伝え、必要なら返事を待ってもらうことです。相手が少し残念に思う可能性まで消すことではありません。相手にも、自分の感情を受け止め、関係について考える力があると信じることでもあります。",
        "まず試せるのは、完璧な返事ではなく、会話を一度止めるための短い返事です。今日は少し余裕がないので、落ち着いたら返します。この一文なら、相手を無視せず、自分の限界も隠しません。詳しく説明するのは、必要になった時で構いません。今すべてを解決しなくてもいいのです。",
        "次に、返事をする時間を自分で決めます。通知が来るたびに反応するのではなく、夜の二十分だけ確認する。急ぎの用事は電話で知らせてもらう。こうした小さなルールは、相手を遠ざける壁ではありません。いつなら落ち着いて向き合えるかを伝える、関係の案内板です。",
        "それでも罪悪感が出てきたら、心の中で一つだけ確認します。今、私は失礼なことをしているのか。それとも、相手が失望する可能性を恐れているだけなのか。この二つは似ていますが、同じではありません。必要な配慮をした後に残る不安まで、すべて責任として抱える必要はありません。",
        "返事が遅れるたびに自分を責める人は、関係を軽く考えているのではありません。むしろ、大切にしようとしすぎて、自分の余白を使い切っていることがあります。だから必要なのは、もっと頑張って早く返すことではなく、どこまでが自分の役割なのかを静かに見直すことです。",
        "今日から、返事の前に相手の気持ちを完璧に整えようとするのを少しだけやめてみてください。誠実な一文を送り、その先の受け取り方は相手に返す。課題を分けることは、関係を壊す勇気ではなく、無理をせず関係に戻るための勇気です。",
        "もし今、返せていないメッセージがあるなら、長い説明を完成させる必要はありません。今は余裕がないけれど、落ち着いたら返したい。その気持ちだけを短く届けてもいいのです。返事の速さではなく、無理のない形で関係に向き合おうとする姿勢が、あなたの誠実さを表します。",
        "あなたは、返事を急がなければならない場面と、少し待ってもらえる場面を分けられていますか。コメントでは、すぐ返す、時間を決めて返す、落ち着いてから返す、今の自分に近いものを一つだけ教えてください。自分の課題を大切にするところから、軽い関係の作り方は始まります。",
    ]
    text = "\n\n".join(paragraphs)
    return text


class DemoResourceProvider:
    is_demo_provider = True

    def research_topics(self, snapshot: dict, performance: dict) -> dict:
        return {
            "channel_positioning": "Tâm lý học ứng dụng cho những khoảnh khắc đời thường của người trưởng thành Nhật Bản.",
            "audience_pains": ["返信を後回しにした罪悪感", "相手の期待を背負いすぎる"],
            "content_gaps": ["応答の遅れを課題の分離で捉える具体例"],
            "trend_hypotheses": [{"hypothesis": "具体的な返信場面は抽象的な心理学より自己認識を生みやすい", "evidence": "既存動画のアドラー心理学関心", "confidence": "medium"}],
            "source_directions": [{"person": "岸見一郎", "work": "嫌われる勇気", "concept": "課題の分離"}],
            "research_notes": ["Demo fixture; production configured analysis model should validate current sources and competition."],
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
        return {"selected_topic": "返信を後回しにしたあとの罪悪感", "selected_candidate_id": "T01", "selection_reason": "最も具体的な視聴者瞬間と心理メカニズムの接続があり、短いfocus動画でも約束を完結しやすい。", "scores": {"channel_fit": 24, "audience_pain": 19, "packaging_potential": 18, "retention_fit": 14, "source_strength": 9, "novelty": 9, "total": 93}, "rejected_topics": [{"candidate_id": "T02", "reason": "状況が広く、thumbnail promise が弱い"}, {"candidate_id": "T03", "reason": "既存の承認欲求テーマと重なりやすい"}], "source_person": "岸見一郎", "source_work": "嫌われる勇気", "source_concept": "課題の分離", "audience_moment": "通知を見ても返事ができず、夜に自分を責める", "promise": "背負いすぎた責任を見分けて、短く誠実に返せる"}

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
            "editorial_dna": {
                "audience_pain": "短い返信なのに手が止まり、遅れるほど苦しくなる",
                "behavioral_entry": "通知を開いても、最初の一文が打てない",
                "contradiction": "関係を大切にしたいのに、返事が遅れる",
                "emotional_promise": "自分を責める前に、返信を重くしている境界を見直せる",
                "memory_line": "返信の重さは文面だけでなく、背負った責任の範囲でも決まる",
                "title_angle": "返信できない苦しさを行動から捉える",
                "thumbnail_conflict": "通知の前で止まる手と、膨らむ責任感",
            },
            "mechanism_candidates": [{"name": mechanism, "role": "responsibility boundary", "source_support": "verified source pack", "confidence": "high"}],
            "selected_mechanisms": [{"name": mechanism, "role": "separate controllable responsibility", "behavior_explained": "返信の過剰準備", "why": "自分の課題と相手の課題を見分けるという整理を、返信の場面に限定して用いる", "inner_process": "返信の負担を、背負う範囲として観察する", "evidence_status": "editorial", "source_boundary": "課題を分ける考え方を返信場面へ応用する範囲"}],
            "causal_chain": ["通知 -> 返信の場面で背負う範囲を観察する -> 返信を保留することがある"],
            "inner_process_map": [{"trigger": "通知", "thought_attention_body": "返信の負担を観察する", "response": "返信を保留", "function_or_cost": "遅れが残ることがある"}],
            "origin_status": "unsupported", "strength_status": "useful", "cost_status": "required",
            "practical_shift_status": "useful", "route": "PROCESS",
            "exclusions": ["childhood cause", "diagnosis", "fictional protagonist"],
        }

    def create_contract(self, topic: str, source_pack: dict, performance: dict, psychology_brief: dict | None = None, validation_feedback: str = "") -> dict:
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
            "title_hook_contract": {"title_behavior": "通知を見ても返事ができない", "title_pain": "短い返信なのに指が止まり、自分を責める", "opening_anchors": ["通知", "返事", "指が止まる"], "payoff_by_seconds": 20},
            "target_duration_minutes": "35-45",
            "target_char_min": 13600,
            "target_char_max": 17500,
            "hook_contract": {"recognition_by_seconds": 20, "misconception_or_tension_by_seconds": 45, "first_real_insight_by_seconds": 60, "core_question_by_seconds": 90},
            "thumbnail_brief": {"click_question": "なぜ短い返信が怖いのか", "visual_conflict": "通知は小さいのに心の影は大きい", "title_must_not_repeat": "返信できない"},
            "format_lock": {
                "primary_format": "symbolic long-form psychological deep-dive",
                "content_center": "một kiểu người — người căng thẳng vì tin nhắn chưa trả lời",
                "primary_narration": "symbolic psychological analysis with reflective narration",
                "secondary_device": "recurring symbolic vignette and behavioral recognition",
                "forbidden_spine": [
                    "fictional claim presented as evidence",
                    "chronological character biography",
                    "symbolic scene without psychological advance",
                ],
            },
        }

    def create_plan(self, contract: dict, source_pack: dict, psychology_brief: dict | None = None, validation_feedback: str = "") -> dict:
        psychology_brief = psychology_brief or {
            "route": contract.get("route", "EXPLANATION"),
            "selected_mechanisms": [{"name": name} for name in contract.get("selected_mechanisms", [])],
        }
        functions = ["recognition", "misconception_reframe", "mechanism", "contradiction", "practical_shift", "insight_landing"]
        mechanism = psychology_brief["selected_mechanisms"][0]["name"]
        sections = []
        for index, function in enumerate(functions, start=1):
            used = [mechanism] if function in {"mechanism", "inner_world", "contradiction", "integration", "practical_shift"} else []
            sections.append({"id": "S%d" % index, "purpose": function, "psychological_job": function, "behavior_link": "返信行動との接続", "relative_weight": 1.0, "why_answered": "なぜ返信負担が増えるか", "mechanisms_used": used, "example_budget": 1 if function in {"recognition", "mechanism"} else 0, "optional_reason": "core" if function not in {"practical_shift"} else "brief=useful", "new_information": "新しい情報%d" % index, "viewer_question_answered": "問い%d" % index, "state_advance": "理解%d -> 理解%d" % (index - 1, index), "so_what_next": "次の問い%d" % index, "segment_function": function})
        return {
            "route": psychology_brief["route"],
            "retention_blueprint": [
                {"movement": "cold_open", "new_information": "通知を見て手が止まる行動", "stay_reason": "自分を認識する", "psychological_progress": "behavior -> recognition"},
                {"movement": "early_reframe", "new_information": "怠けではなく返信に伴う責任負担", "stay_reason": "理解が反転する", "psychological_progress": "self-blame -> psychological interpretation"},
            ],
            "sections": sections,
            "redundancy_risks": ["同じ安心表現を繰り返さない"],
            "reassurance_lines_used": [],
            "core_question": "なぜ返事をする意図より、相手の反応を先回りする負担が先に選ばれるのか。",
            "hook_draft": "なぜ返事をする意図より、相手の反応を先回りする負担が先に選ばれるのでしょうか。通知を見ても指が止まるのは、怠けではなく、最初の一文に責任を背負わせているからです。",
            "cta_plan": "三つの返信習慣から一つ選ぶ",
            "planning_quality_gate": {"first_insight_before_30s": True, "first_insight_before_35s": True, "first_major_payoff_before_5m": True, "no_duplicate_sections": True, "every_section_advances_state": True, "psychology_is_spine": True, "no_plot_or_character_arc": True, "ending_creates_self_understanding": True},
        }

    def write_script(self, contract: dict, plan: dict, source_pack: dict, psychology_brief: dict | None = None) -> str:
        return _demo_script()

    def write_script_movements(self, contract: dict, plan: dict, source_pack: dict, psychology_brief: dict | None = None) -> list[dict]:
        return [{"id": "S1", "target_chars": int(contract.get("target_char_min") or 0), "text": self.write_script(contract, plan, source_pack, psychology_brief)}]

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
        return "【Bản dịch tiếng Việt (DEMO) — production dịch đầy đủ qua configured writer】\n" + script[:300]

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
            "image_prompt": "A fictional anonymous gender-neutral illustrated character looking at a phone notification with visible hesitation, flat illustrated cartoon style, thick black outline, solid colors, navy #1A2332 background, full-bleed 16:9 scene across the entire frame, main action weighted to the right, soft left-to-right navy atmospheric gradient fading into a low-detail text zone, no hard split or vertical divider, no text, no logo, no watermark, not resembling any identifiable real person.",
            "negative_prompt": "text, logo, watermark, recognizable public figure, exact likeness, extra fingers, distorted hands, low contrast, cluttered background",
            "overlay_spec": {"lines": 1, "font_weight": "heavy", "height_percent": 14, "position": "left", "safe_margin_percent": 5},
            "manual_squint_test": "PENDING_USER",
        }

    def create_image_strategy(self, contract: dict, plan: dict, thumbnail: dict) -> dict:
        beats = []
        # Demo giữ mật độ đủ cho validator; production vẫn derive floor động từ
        # contract + plan và không dùng số ảnh cố định.
        for index in range(1, 50):
            image_number = index if index <= 42 else ((index - 43) % 42) + 1
            beats.append({"id": "B%02d" % index, "time": "DRAFT_TIMING", "script_section": "S%d" % min(6, ((index - 1) // 8) + 1), "visual_information": "視覚情報%d" % index, "mode": "literal" if index % 3 else "contrast", "new_image": index <= 42, "image_id": "IMG-%02d" % image_number, "reuse_image_id": None if index <= 42 else "IMG-%02d" % image_number})
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
        return {"description_draft": "返事を後回しにしたあと、罪悪感で画面を開けなくなることはありませんか。\nこの動画では、短い返信が大きな負担になる心理を、課題の分離という考え方から整理します。相手の受け取り方まで自分の責任として抱えると、正解を探し続けて返信が遅れ、遅れるほど罪悪感が強くなります。動画では、どこまでが自分の課題なのかを見直し、誠実さと過剰な責任を分けて考えます。\n\nこの動画は教育・情報提供を目的としたもので、医療的助言ではありません。", "chapters_status": "DRAFT_OMITTED", "pinned_comment": "返事をする時、今の自分に近いのはどれですか？ ①すぐ返す ②時間を決める ③落ち着いてから返す", "hashtags": ["#人間関係", "#アドラー心理学", "#メンタルケア"], "tags": ["返信", "罪悪感", "課題の分離", "人間関係"], "source_note": "参考：岸見一郎・古賀史健『嫌われる勇気』"}
