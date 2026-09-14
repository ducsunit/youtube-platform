"""Unified router for ALL model interactions across modalities."""
from __future__ import annotations

import os
import threading
import time
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Callable, TypeVar
from contextlib import contextmanager

from .dynamic_config import DynamicSettings, ModelAssignment, ProviderConfig
from .infrastructure.model_trace import trace_request, trace_raw_response, trace_parsed_response

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ModelClient(Protocol):
    """Protocol for all model clients."""
    def generate_json(self, system: str, prompt: str, temperature: float, max_tokens: Optional[int], **kwargs) -> Dict[str, Any]: ...
    def generate_text(self, system: str, prompt: str, temperature: float, max_tokens: Optional[int], **kwargs) -> str: ...
    def generate_image(self, prompt: str, **params) -> bytes: ...
    def generate_video(self, prompt: str, image: Optional[bytes], **params) -> bytes: ...
    def generate_audio(self, text: str, voice: str, **params) -> bytes: ...
    def lip_sync(self, video: bytes, audio: bytes, **params) -> bytes: ...


@dataclass
class ClientFactory:
    """Factory for creating provider-specific clients."""
    settings: DynamicSettings
    _clients: Dict[str, Any] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def get_client(self, assignment: ModelAssignment) -> ModelClient:
        key = f"{assignment.provider}:{assignment.model}"
        with self._lock:
            if key in self._clients:
                return self._clients[key]
            
            provider = self.settings.get_provider(assignment.provider)
            if not provider:
                raise ConfigurationError(f"Provider not configured: {assignment.provider}")
            
            client = self._build_client(provider, assignment)
            self._clients[key] = client
            return client

    def _build_client(self, provider: ProviderConfig, assignment: ModelAssignment) -> ModelClient:
        ptype = provider.type
        
        if ptype == "gemini":
            return self._build_gemini_client(provider, assignment)
        elif ptype == "openai_compatible":
            return self._build_openai_compatible_client(provider, assignment)
        elif ptype == "anthropic":
            return self._build_anthropic_client(provider, assignment)
        elif ptype == "comfyui":
            return self._build_comfyui_client(provider, assignment)
        elif ptype in ("kling", "hailuo", "runway"):
            return self._build_video_client(provider, assignment)
        elif ptype in ("hedra", "liveportrait"):
            return self._build_lip_sync_client(provider, assignment)
        elif ptype in ("voicevox", "edge_tts", "google_cloud"):
            return self._build_audio_client(provider, assignment)
        else:
            raise ConfigurationError(f"Unsupported provider type: {ptype}")

    def _build_gemini_client(self, provider: ProviderConfig, assignment: ModelAssignment) -> ModelClient:
        from google import genai
        from google.genai import types
        
        api_key = self.settings.resolve_api_key(provider.name)
        client = genai.Client(api_key=api_key)
        
        class GeminiClient:
            def generate_json(self, system: str, prompt: str, temperature: float, max_tokens: Optional[int], **kwargs) -> Dict[str, Any]:
                config = types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    temperature=temperature,
                    thinking_config=types.ThinkingConfig(thinking_level="high"),
                )
                if max_tokens:
                    config.max_output_tokens = max_tokens
                resp = client.models.generate_content(model=assignment.model, contents=prompt, config=config)
                import json
                return json.loads(resp.text)
            
            def generate_text(self, system: str, prompt: str, temperature: float, max_tokens: Optional[int], **kwargs) -> str:
                config = types.GenerateContentConfig(
                    system_instruction=system, temperature=temperature,
                    thinking_config=types.ThinkingConfig(thinking_level="high"),
                )
                if max_tokens:
                    config.max_output_tokens = max_tokens
                resp = client.models.generate_content(model=assignment.model, contents=prompt, config=config)
                return resp.text or ""
            
            def generate_image(self, prompt: str, **params) -> bytes:
                raise NotImplementedError("Gemini doesn't support image generation in this config")
            
            def generate_video(self, prompt: str, image: Optional[bytes], **params) -> bytes:
                raise NotImplementedError("Gemini doesn't support video generation in this config")
            
            def generate_audio(self, text: str, voice: str, **params) -> bytes:
                raise NotImplementedError("Gemini doesn't support audio generation in this config")
            
            def lip_sync(self, video: bytes, audio: bytes, **params) -> bytes:
                raise NotImplementedError("Gemini doesn't support lip-sync in this config")
        
        return GeminiClient()

    def _build_openai_compatible_client(self, provider: ProviderConfig, assignment: ModelAssignment) -> ModelClient:
        from openai import OpenAI
        
        api_key = self.settings.resolve_api_key(provider.name)
        client = OpenAI(
            api_key=api_key or "dummy",
            base_url=provider.base_url or None,
            timeout=180.0,
            max_retries=0,
        )
        
        class OpenAICompatibleClient:
            def generate_json(self, system: str, prompt: str, temperature: float, max_tokens: Optional[int], **kwargs) -> Dict[str, Any]:
                kwargs["response_format"] = {"type": "json_object"}
                return self._call(system, prompt, temperature, max_tokens, **kwargs)
            
            def generate_text(self, system: str, prompt: str, temperature: float, max_tokens: Optional[int], **kwargs) -> str:
                return self._call(system, prompt, temperature, max_tokens, **kwargs)
            
            def _call(self, system: str, prompt: str, temperature: float, max_tokens: Optional[int], **extra) -> Any:
                messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
                params = {
                    "model": assignment.model,
                    "messages": messages,
                    "temperature": temperature,
                    **extra,
                }
                if max_tokens:
                    params["max_tokens"] = max_tokens
                resp = client.chat.completions.create(**params)
                content = resp.choices[0].message.content or ""
                if "response_format" in extra and extra["response_format"].get("type") == "json_object":
                    import json
                    return json.loads(content)
                return content
            
            def generate_image(self, prompt: str, **params) -> bytes:
                raise NotImplementedError("OpenAI compatible doesn't support image generation in this config")
            
            def generate_video(self, prompt: str, image: Optional[bytes], **params) -> bytes:
                raise NotImplementedError("OpenAI compatible doesn't support video generation in this config")
            
            def generate_audio(self, text: str, voice: str, **params) -> bytes:
                raise NotImplementedError("OpenAI compatible doesn't support audio generation in this config")
            
            def lip_sync(self, video: bytes, audio: bytes, **params) -> bytes:
                raise NotImplementedError("OpenAI compatible doesn't support lip-sync in this config")
        
        return OpenAICompatibleClient()

    def _build_anthropic_client(self, provider: ProviderConfig, assignment: ModelAssignment) -> ModelClient:
        import anthropic
        api_key = self.settings.resolve_api_key(provider.name)
        client = anthropic.Anthropic(api_key=api_key, base_url=provider.base_url or None)
        
        class AnthropicClient:
            def generate_json(self, system: str, prompt: str, temperature: float, max_tokens: Optional[int], **kwargs) -> Dict[str, Any]:
                import json
                resp = client.messages.create(
                    model=assignment.model,
                    system=system,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=temperature,
                    max_tokens=max_tokens or 4096,
                )
                return json.loads(resp.content[0].text)
            
            def generate_text(self, system: str, prompt: str, temperature: float, max_tokens: Optional[int], **kwargs) -> str:
                resp = client.messages.create(
                    model=assignment.model,
                    system=system,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=temperature,
                    max_tokens=max_tokens or 4096,
                )
                return resp.content[0].text
            
            def generate_image(self, prompt: str, **params) -> bytes:
                raise NotImplementedError("Anthropic doesn't support image generation")
            
            def generate_video(self, prompt: str, image: Optional[bytes], **params) -> bytes:
                raise NotImplementedError("Anthropic doesn't support video generation")
            
            def generate_audio(self, text: str, voice: str, **params) -> bytes:
                raise NotImplementedError("Anthropic doesn't support audio generation")
            
            def lip_sync(self, video: bytes, audio: bytes, **params) -> bytes:
                raise NotImplementedError("Anthropic doesn't support lip-sync")
        
        return AnthropicClient()

    def _build_comfyui_client(self, provider: ProviderConfig, assignment: ModelAssignment) -> ModelClient:
        # Import here to avoid circular imports
        from .provider_clients.image_clients import ComfyUIClient
        workflows_dir = provider.extra.get("workflows_dir", "./workflows")
        return ComfyUIClient(base_url=provider.base_url, workflows_dir=workflows_dir)

    def _build_video_client(self, provider: ProviderConfig, assignment: ModelAssignment) -> ModelClient:
        ptype = provider.type
        if ptype == "kling":
            from .provider_clients.video_clients import KlingClient
            return KlingClient(api_key=self.settings.resolve_api_key(provider.name), base_url=provider.base_url)
        elif ptype == "hailuo":
            from .provider_clients.video_clients import HailuoClient
            return HailuoClient(api_key=self.settings.resolve_api_key(provider.name), base_url=provider.base_url)
        elif ptype == "runway":
            from .provider_clients.video_clients import RunwayClient
            return RunwayClient(api_key=self.settings.resolve_api_key(provider.name), base_url=provider.base_url)
        raise ConfigurationError(f"Unknown video provider: {ptype}")

    def _build_lip_sync_client(self, provider: ProviderConfig, assignment: ModelAssignment) -> ModelClient:
        ptype = provider.type
        if ptype == "hedra":
            from .provider_clients.lip_sync_clients import HedraClient
            return HedraClient(api_key=self.settings.resolve_api_key(provider.name), base_url=provider.base_url)
        elif ptype == "liveportrait":
            from .provider_clients.lip_sync_clients import LivePortraitClient
            return LivePortraitClient(base_url=provider.base_url)
        raise ConfigurationError(f"Unknown lip-sync provider: {ptype}")

    def _build_audio_client(self, provider: ProviderConfig, assignment: ModelAssignment) -> ModelClient:
        ptype = provider.type
        if ptype == "voicevox":
            from .provider_clients.audio_clients import VoicevoxClient
            return VoicevoxClient(base_url=provider.base_url)
        elif ptype == "edge_tts":
            from .provider_clients.audio_clients import EdgeTTSClient
            return EdgeTTSClient()
        elif ptype == "google_cloud":
            from .provider_clients.audio_clients import GoogleCloudTTSClient
            credentials_path = self.settings.resolve_api_key(provider.name)
            return GoogleCloudTTSClient(credentials_path=credentials_path)
        raise ConfigurationError(f"Unknown audio provider: {ptype}")


class UnifiedRouter:
    """Single router for ALL model interactions across modalities."""
    
    def __init__(self, settings: Optional[DynamicSettings] = None, config_path: Optional[Path] = None):
        self.settings = settings or DynamicSettings.load(config_path)
        self.factory = ClientFactory(self.settings)
        self._validate()
    
    def _validate(self):
        warnings = self.settings.validate()
        for w in warnings:
            logger.warning("Config validation: %s", w)
    
    # ─────────────────────────────────────────────────────────────
    # TEXT / JSON GENERATION
    # ─────────────────────────────────────────────────────────────
    def generate_json(self, stage: str, system: str, prompt: str, **kwargs) -> Dict[str, Any]:
        role = self.settings.get_stage_role(stage)
        if not role:
            raise ConfigurationError(f"No role mapped for stage: {stage}")
        return self._execute_with_fallback(role, "generate_json", system, prompt, **kwargs)
    
    def generate_text(self, stage: str, system: str, prompt: str, **kwargs) -> str:
        role = self.settings.get_stage_role(stage)
        if not role:
            raise ConfigurationError(f"No role mapped for stage: {stage}")
        return self._execute_with_fallback(role, "generate_text", system, prompt, **kwargs)
    
    # ─────────────────────────────────────────────────────────────
    # IMAGE GENERATION
    # ─────────────────────────────────────────────────────────────
    def generate_image(self, stage: str, prompt: str, **params) -> bytes:
        role = self.settings.get_stage_role(stage)
        if not role:
            raise ConfigurationError(f"No role mapped for stage: {stage}")
        return self._execute_with_fallback(role, "generate_image", prompt, **params)
    
    # ─────────────────────────────────────────────────────────────
    # VIDEO / ANIMATION GENERATION
    # ─────────────────────────────────────────────────────────────
    def generate_video(self, stage: str, prompt: str, image: Optional[bytes] = None, **params) -> bytes:
        role = self.settings.get_stage_role(stage)
        if not role:
            raise ConfigurationError(f"No role mapped for stage: {stage}")
        return self._execute_with_fallback(role, "generate_video", prompt, image, **params)
    
    # ─────────────────────────────────────────────────────────────
    # AUDIO / TTS / LIP-SYNC
    # ─────────────────────────────────────────────────────────────
    def generate_audio(self, stage: str, text: str, voice: str, **params) -> bytes:
        role = self.settings.get_stage_role(stage)
        if not role:
            raise ConfigurationError(f"No role mapped for stage: {stage}")
        return self._execute_with_fallback(role, "generate_audio", text, voice, **params)
    
    def lip_sync(self, stage: str, video: bytes, audio: bytes, **params) -> bytes:
        role = self.settings.get_stage_role(stage)
        if not role:
            raise ConfigurationError(f"No role mapped for stage: {stage}")
        return self._execute_with_fallback(role, "lip_sync", video, audio, **params)
    
    # ─────────────────────────────────────────────────────────────
    # INTERNAL: Fallback Execution
    # ─────────────────────────────────────────────────────────────
    def _execute_with_fallback(self, role_name: str, method: str, *args, **kwargs) -> Any:
        role = self.settings.get_role(role_name)
        if not role:
            raise ConfigurationError(f"Role not found: {role_name}")
        
        fallback_enabled = self.settings.settings.get("fallback_enabled", True)
        max_fallback = self.settings.settings.get("fallback_max_attempts", 3) if fallback_enabled else 1
        
        last_error = None
        for attempt in range(min(max_fallback, len(role.all_assignments()))):
            assignment = role.all_assignments()[attempt]
            try:
                client = self.factory.get_client(assignment)
                func = getattr(client, method)
                
                # Trace
                trace_request(
                    f"{role_name}_{method}",
                    stage=role_name,
                    provider=assignment.provider,
                    model=assignment.model,
                    system=args[0] if method in ("generate_json", "generate_text") and args else "",
                    prompt=args[1] if method in ("generate_json", "generate_text") and len(args) > 1 else (args[0] if args else ""),
                    temperature=assignment.temperature,
                )
                
                result = func(*args, **kwargs, temperature=assignment.temperature, max_tokens=assignment.max_tokens, **assignment.params)
                
                trace_raw_response(f"{role_name}_{method}", role_name, str(result)[:2000])
                trace_parsed_response(f"{role_name}_{method}", role_name, result if isinstance(result, dict) else {"text": str(result)[:500]})
                
                return result
            
            except Exception as e:
                last_error = e
                logger.warning(
                    "Model call failed | role=%s | attempt=%d/%d | provider=%s | model=%s | error=%s",
                    role_name, attempt + 1, max_fallback, assignment.provider, assignment.model, e
                )
                if attempt == max_fallback - 1:
                    break
        
        raise ConfigurationError(f"All fallback attempts exhausted for role '{role_name}', method '{method}': {last_error}")
    
    # ─────────────────────────────────────────────────────────────
    # UTILITY
    # ─────────────────────────────────────────────────────────────
    def get_assignment(self, stage: str, attempt: int = 0) -> Optional[ModelAssignment]:
        role = self.settings.get_stage_role(stage)
        if role:
            return self.settings.get_effective_assignment(role, attempt)
        return None
    
    def snapshot(self) -> Dict[str, Any]:
        return {
            "roles": {name: {"primary": {"provider": r.primary.provider, "model": r.primary.model}} for name, r in self.settings.roles.items()},
            "providers": list(self.settings.providers.keys()),
        }


# ─────────────────────────────────────────────────────────────
# CONVENIENCE FUNCTIONS
# ─────────────────────────────────────────────────────────────
_default_router: Optional[UnifiedRouter] = None
_router_lock = threading.Lock()

def get_router(config_path: Optional[Path] = None) -> UnifiedRouter:
    global _default_router
    with _router_lock:
        if _default_router is None:
            _default_router = UnifiedRouter(config_path=config_path)
        return _default_router

def reset_router():
    global _default_router
    with _router_lock:
        _default_router = None