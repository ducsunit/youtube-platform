"""Dynamic configuration system for model registry."""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Literal
import yaml

from .config import ConfigurationError


@dataclass(frozen=True)
class ProviderConfig:
    """Provider-level configuration."""
    name: str
    type: Literal["gemini", "openai_compatible", "anthropic", "comfyui",
                  "kling", "hailuo", "runway", "hedra", "liveportrait",
                  "elevenlabs", "voicevox", "edge_tts", "google_cloud", "custom"]
    api_key_env: str = ""
    base_url: str = ""
    default_headers: Dict[str, str] = field(default_factory=dict)
    rate_limit_rpm: int = 1000
    models: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelAssignment:
    """Single model assignment with parameters."""
    provider: str
    model: str
    temperature: float = 0.2
    max_tokens: Optional[int] = None
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RoleConfig:
    """Role configuration with fallback chain."""
    name: str
    primary: ModelAssignment
    fallback: List[ModelAssignment] = field(default_factory=list)

    def all_assignments(self) -> List[ModelAssignment]:
        return [self.primary] + self.fallback


@dataclass
class DynamicSettings:
    """Runtime settings loaded from YAML."""
    providers: Dict[str, ProviderConfig]
    roles: Dict[str, RoleConfig]
    pipeline_stages: Dict[str, str]
    settings: Dict[str, Any]

    # ─────────────────────────────────────────────────────────────
    # LOADING
    # ─────────────────────────────────────────────────────────────
    @classmethod
    def load(cls, config_path: Optional[Path] = None) -> "DynamicSettings":
        if config_path is None:
            config_path = Path(__file__).resolve().parents[1] / "config" / "model-registry.yaml"
        
        if not config_path.exists():
            raise ConfigurationError(f"Config file not found: {config_path}")
        
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: Dict[str, Any]) -> "DynamicSettings":
        providers = {}
        for name, pdata in data.get("providers", {}).items():
            providers[name] = ProviderConfig(
                name=name, type=pdata["type"], api_key_env=pdata.get("api_key_env", ""),
                base_url=pdata.get("base_url", ""), default_headers=pdata.get("default_headers", {}),
                rate_limit_rpm=pdata.get("rate_limit_rpm", 1000), models=pdata.get("models", []),
                extra=pdata.get("extra", {}),
            )
        
        roles = {}
        for name, rdata in data.get("roles", {}).items():
            primary_data = rdata["primary"]
            primary = ModelAssignment(
                provider=primary_data["provider"], model=primary_data["model"],
                temperature=primary_data.get("temperature", 0.2),
                max_tokens=primary_data.get("max_tokens"),
                params=primary_data.get("params", {}),
            )
            fallback = []
            for fb in rdata.get("fallback", []):
                fallback.append(ModelAssignment(
                    provider=fb["provider"], model=fb["model"],
                    temperature=fb.get("temperature", 0.2),
                    max_tokens=fb.get("max_tokens"),
                    params=fb.get("params", {}),
                ))
            roles[name] = RoleConfig(name=name, primary=primary, fallback=fallback)
        
        pipeline_stages = data.get("pipeline_stages", {})
        settings = data.get("settings", {})
        
        return cls(providers=providers, roles=roles, pipeline_stages=pipeline_stages, settings=settings)

    # ─────────────────────────────────────────────────────────────
    # QUERY METHODS
    # ─────────────────────────────────────────────────────────────
    def get_role(self, role_name: str) -> Optional[RoleConfig]:
        return self.roles.get(role_name)

    def get_stage_role(self, stage: str) -> Optional[str]:
        return self.pipeline_stages.get(stage)

    def get_provider(self, provider_name: str) -> Optional[ProviderConfig]:
        return self.providers.get(provider_name)

    def resolve_api_key(self, provider_name: str) -> str:
        provider = self.providers.get(provider_name)
        if not provider:
            raise ConfigurationError(f"Provider not found: {provider_name}")
        if provider.api_key_env:
            value = os.getenv(provider.api_key_env, "").strip()
            if value:
                return value
        return provider.extra.get("api_key", "")

    def get_effective_assignment(self, role_name: str, attempt: int = 0) -> Optional[ModelAssignment]:
        role = self.roles.get(role_name)
        if not role:
            return None
        assignments = role.all_assignments()
        if attempt < len(assignments):
            return assignments[attempt]
        return None

    def validate(self) -> List[str]:
        warnings = []
        for role_name, role in self.roles.items():
            for i, assignment in enumerate(role.all_assignments()):
                provider = self.providers.get(assignment.provider)
                if not provider:
                    warnings.append(f"Role '{role_name}' assignment #{i}: unknown provider '{assignment.provider}'")
                elif assignment.model not in provider.models and provider.models:
                    warnings.append(f"Role '{role_name}' assignment #{i}: model '{assignment.model}' not in provider '{assignment.provider}' known models")
        return warnings


# ─────────────────────────────────────────────────────────────
# MIGRATION ADAPTER
# ─────────────────────────────────────────────────────────────
def migrate_from_old_settings(old_settings: Any, config_path: Optional[Path] = None) -> DynamicSettings:
    """Create DynamicSettings from legacy Settings object."""
    new = DynamicSettings.load(config_path)
    
    # Override with keys from old settings if present
    if hasattr(old_settings, 'gemini_api_key') and old_settings.gemini_api_key:
        os.environ["GEMINI_API_KEY"] = old_settings.gemini_api_key
    if hasattr(old_settings, 'deepseek_api_key') and old_settings.deepseek_api_key:
        os.environ["DEEPSEEK_API_KEY"] = old_settings.deepseek_api_key
    
    # Override model names if different from defaults
    overrides = {
        "analysis": ("gemini", getattr(old_settings, 'gemini_analysis_model', None)),
        "reviewer": ("gemini", getattr(old_settings, 'gemini_review_model', None)),
        "auditor": ("gemini", getattr(old_settings, 'gemini_audit_model', None)),
        "writer": ("deepseek", getattr(old_settings, 'deepseek_model', None)),
        "editor": ("deepseek", getattr(old_settings, 'deepseek_model', None)),
        "packaging": ("deepseek", getattr(old_settings, 'deepseek_model', None)),
    }
    
    for role_name, (provider, model) in overrides.items():
        if model and role_name in _roles:
            _override_role_model(_roles, role_name, provider, model)
    
    return DynamicSettings(
        providers=_providers,
        roles=_roles,
        pipeline_stages=_pipeline_stages,
        settings=_settings
    )

def _override_role_model(roles: Dict, role_name: str, provider: str, model: str):
    if role_name in roles:
        role = roles[role_name]
        if role.primary.provider == provider:
            # Rebuild role with new primary (frozen dataclass)
            new_primary = ModelAssignment(
                provider=provider, model=model,
                temperature=role.primary.temperature,
                max_tokens=role.primary.max_tokens,
                params=role.primary.params
            )
            roles[role_name] = RoleConfig(name=role_name, primary=new_primary, fallback=role.fallback)


# Module-level cache for migration
_providers = {}
_roles = {}
_pipeline_stages = {}
_settings = {}

def _init_migration_cache():
    global _providers, _roles, _pipeline_stages, _settings
    try:
        settings = DynamicSettings.load()
        _providers = settings.providers
        _roles = settings.roles
        _pipeline_stages = settings.pipeline_stages
        _settings = settings.settings
    except Exception:
        pass

_init_migration_cache()