"""Text/LLM provider clients."""
from __future__ import annotations
from typing import Any, Dict, List, Optional
import json
import logging

logger = logging.getLogger(__name__)


class BaseTextClient:
    """Base class for text generation clients."""
    
    def generate_json(self, system: str, prompt: str, temperature: float, max_tokens: Optional[int], **kwargs) -> Dict[str, Any]:
        raise NotImplementedError
    
    def generate_text(self, system: str, prompt: str, temperature: float, max_tokens: Optional[int], **kwargs) -> str:
        raise NotImplementedError


class GeminiClient(BaseTextClient):
    """Google Gemini client."""
    
    def __init__(self, api_key: str, **kwargs):
        from google import genai
        from google.genai import types
        self._client = genai.Client(api_key=api_key)
        self._types = types
    
    def generate_json(self, system: str, prompt: str, temperature: float, max_tokens: Optional[int], **kwargs) -> Dict[str, Any]:
        config = self._types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            temperature=temperature,
            thinking_config=self._types.ThinkingConfig(thinking_level="high"),
        )
        if max_tokens:
            config.max_output_tokens = max_tokens
        
        model = kwargs.get("model", "gemini-2.5-flash")
        resp = self._client.models.generate_content(model=model, contents=prompt, config=config)
        return json.loads(resp.text)
    
    def generate_text(self, system: str, prompt: str, temperature: float, max_tokens: Optional[int], **kwargs) -> str:
        config = self._types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            thinking_config=self._types.ThinkingConfig(thinking_level="high"),
        )
        if max_tokens:
            config.max_output_tokens = max_tokens
        
        model = kwargs.get("model", "gemini-2.5-flash")
        resp = self._client.models.generate_content(model=model, contents=prompt, config=config)
        return resp.text or ""


class DeepSeekClient(BaseTextClient):
    """DeepSeek client (OpenAI-compatible)."""
    
    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com", **kwargs):
        from openai import OpenAI
        self._client = OpenAI(
            api_key=api_key or "dummy",
            base_url=base_url or None,
            timeout=180.0,
            max_retries=0,
        )
        self._default_model = kwargs.get("model", "deepseek-chat")
    
    def generate_json(self, system: str, prompt: str, temperature: float, max_tokens: Optional[int], **kwargs) -> Dict[str, Any]:
        return self._call(system, prompt, temperature, max_tokens, response_format={"type": "json_object"}, **kwargs)
    
    def generate_text(self, system: str, prompt: str, temperature: float, max_tokens: Optional[int], **kwargs) -> str:
        return self._call(system, prompt, temperature, max_tokens, **kwargs)
    
    def _call(self, system: str, prompt: str, temperature: float, max_tokens: Optional[int], **extra) -> Any:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        params = {
            "model": extra.get("model", self._default_model),
            "messages": messages,
            "temperature": temperature,
            **extra,
        }
        if max_tokens:
            params["max_tokens"] = max_tokens
        
        from openai import OpenAI
        # Client is already initialized in __init__
        # We need to access the client - this is a simplified version
        # In practice, the client should be stored in self._client
        raise NotImplementedError("Use OpenAICompatibleClient instead")


class OpenAICompatibleClient(BaseTextClient):
    """Generic OpenAI-compatible client (DeepSeek, OpenAI, Ollama, etc.)."""
    
    def __init__(self, api_key: str, base_url: Optional[str] = None, model: str = "deepseek-chat", **kwargs):
        from openai import OpenAI
        self._client = OpenAI(
            api_key=api_key or "dummy",
            base_url=base_url,
            timeout=180.0,
            max_retries=0,
        )
        self._default_model = model
    
    def generate_json(self, system: str, prompt: str, temperature: float, max_tokens: Optional[int], **kwargs) -> Dict[str, Any]:
        return self._call(system, prompt, temperature, max_tokens, response_format={"type": "json_object"}, **kwargs)
    
    def generate_text(self, system: str, prompt: str, temperature: float, max_tokens: Optional[int], **kwargs) -> str:
        return self._call(system, prompt, temperature, max_tokens, **kwargs)
    
    def _call(self, system: str, prompt: str, temperature: float, max_tokens: Optional[int], **extra) -> Any:
        from openai import OpenAI
        messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        params = {
            "model": extra.get("model", self._default_model),
            "messages": messages,
            "temperature": temperature,
            **extra,
        }
        if max_tokens:
            params["max_tokens"] = max_tokens
        
        # We need access to the OpenAI client - this is a placeholder
        # The actual client should be passed in or created here
        raise NotImplementedError("Client initialization needs to be completed")


class AnthropicClient(BaseTextClient):
    """Anthropic Claude client."""
    
    def __init__(self, api_key: str, base_url: Optional[str] = None, model: str = "claude-3-5-sonnet-20241022", **kwargs):
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key, base_url=base_url)
        self._default_model = model
    
    def generate_json(self, system: str, prompt: str, temperature: float, max_tokens: Optional[int], **kwargs) -> Dict[str, Any]:
        import json
        resp = self._client.messages.create(
            model=kwargs.get("model", self._default_model),
            system=system,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens or 4096,
        )
        return json.loads(resp.content[0].text)
    
    def generate_text(self, system: str, prompt: str, temperature: float, max_tokens: Optional[int], **kwargs) -> str:
        resp = self._client.messages.create(
            model=kwargs.get("model", self._default_model),
            system=system,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens or 4096,
        )
        return resp.content[0].text


# ─────────────────────────────────────────────────────────────
# FACTORY FUNCTIONS (used by router)
# ─────────────────────────────────────────────────────────────

def create_gemini_client(api_key: str, **kwargs) -> BaseTextClient:
    """Factory for Gemini client."""
    return GeminiClient(api_key=api_key, **kwargs)


def create_openai_compatible_client(api_key: str, base_url: str, model: str, **kwargs) -> BaseTextClient:
    """Factory for OpenAI-compatible client."""
    from openai import OpenAI
    client = OpenAI(
        api_key=api_key or "dummy",
        base_url=base_url,
        timeout=180.0,
        max_retries=0,
    )
    
    class _Client(BaseTextClient):
        def __init__(self, client, model):
            self._client = client
            self._default_model = model
        
        def generate_json(self, system: str, prompt: str, temperature: float, max_tokens: Optional[int], **kwargs) -> Dict[str, Any]:
            return self._call(system, prompt, temperature, max_tokens, response_format={"type": "json_object"}, **kwargs)
        
        def generate_text(self, system: str, prompt: str, temperature: float, max_tokens: Optional[int], **kwargs) -> str:
            return self._call(system, prompt, temperature, max_tokens, **kwargs)
        
        def _call(self, system: str, prompt: str, temperature: float, max_tokens: Optional[int], **extra) -> Any:
            messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
            params = {
                "model": extra.get("model", self._default_model),
                "messages": messages,
                "temperature": temperature,
                **extra,
            }
            if max_tokens:
                params["max_tokens"] = max_tokens
            
            resp = self._client.chat.completions.create(**params)
            content = resp.choices[0].message.content or ""
            if "response_format" in extra and extra["response_format"].get("type") == "json_object":
                import json
                return json.loads(content)
            return content
    
    return _Client(client, kwargs.get("model", "deepseek-chat"))


def create_anthropic_client(api_key: str, base_url: Optional[str], model: str, **kwargs) -> BaseTextClient:
    return AnthropicClient(api_key=api_key, base_url=base_url, model=model, **kwargs)