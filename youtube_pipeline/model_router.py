from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import Settings


CONFIG_DIR_NAME = "config"
ROUTING_FILE_NAME = "model-routing.json"
ROLES = ("analysis", "writer", "reviewer", "editor", "auditor", "packaging")


@dataclass(frozen=True)
class ModelProfile:
    provider: str
    model: str
    base_url: str = ""
    api_key_env: str = ""
    temperature: float = 0.2
    max_output_tokens: int | None = None
    api_key: str = ""
    profile_name: str = ""


class ModelRouter:
    """Runtime model routing loaded from config/model-routing.json.

    Runtime keys may be stored in this local, gitignored file so the UI can
    change providers without editing `.env`. Public snapshots always redact them.
    """

    def __init__(
        self,
        settings: Settings,
        backend_root: Path | None = None,
        *,
        routing_data: dict[str, Any] | None = None,
        frozen: bool = False,
    ) -> None:
        self.settings = settings
        self.backend_root = Path(backend_root or _default_backend_root()).resolve()
        self.path = self.backend_root / CONFIG_DIR_NAME / ROUTING_FILE_NAME
        self._mtime_ns: int | None = None
        self._frozen = frozen
        if routing_data is not None:
            self._validate(routing_data)
            # The run snapshot deliberately never contains a runtime key.
            self._data = json.loads(json.dumps(routing_data, ensure_ascii=False))
        else:
            self._data = self._load_or_create()

    @classmethod
    def from_snapshot(
        cls, settings: Settings, snapshot: dict[str, Any], backend_root: Path | None = None
    ) -> "ModelRouter":
        return cls(settings, backend_root, routing_data=snapshot, frozen=True)

    def _default_data(self) -> dict[str, Any]:
        def profile_data(profile: ModelProfile) -> dict[str, Any]:
            value = asdict(profile)
            value.pop("profile_name", None)
            return value

        return {
            "version": 1,
            "profiles": {
                "analysis": profile_data(ModelProfile("gemini", self.settings.gemini_analysis_model, api_key_env="GEMINI_API_KEY")),
                "writer": profile_data(ModelProfile("openai_compatible", self.settings.deepseek_model, self.settings.deepseek_base_url, "DEEPSEEK_API_KEY")),
                "reviewer": profile_data(ModelProfile("gemini", self.settings.gemini_review_model, api_key_env="GEMINI_API_KEY")),
                "editor": profile_data(ModelProfile("openai_compatible", self.settings.deepseek_model, self.settings.deepseek_base_url, "DEEPSEEK_API_KEY")),
                "auditor": profile_data(ModelProfile("gemini", self.settings.gemini_audit_model, api_key_env="GEMINI_API_KEY")),
                "packaging": profile_data(ModelProfile("openai_compatible", self.settings.deepseek_model, self.settings.deepseek_base_url, "DEEPSEEK_API_KEY")),
            },
            "role_profiles": {role: role for role in ROLES},
        }

    def _load_or_create(self) -> dict[str, Any]:
        if not self.path.exists():
            data = self._default_data()
            self._write(data)
            return data
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Không đọc được model routing config: {self.path}") from exc
        self._validate(data)
        self._mtime_ns = self.path.stat().st_mtime_ns
        return data

    def _refresh(self) -> None:
        """Pick up UI changes without restarting a long-running pipeline."""
        if self._frozen:
            return
        try:
            mtime_ns = self.path.stat().st_mtime_ns
        except OSError:
            return
        if self._mtime_ns == mtime_ns:
            return
        self._data = self._load_or_create()

    @staticmethod
    def _validate(data: dict[str, Any]) -> None:
        if not isinstance(data, dict) or not isinstance(data.get("profiles"), dict):
            raise ValueError("model-routing.json phải có object 'profiles'.")
        for role in ROLES:
            profile_name = (data.get("role_profiles") or {}).get(role, role)
            if profile_name not in data["profiles"]:
                raise ValueError(f"Role '{role}' trỏ tới profile không tồn tại: {profile_name}")
        for name, profile in data["profiles"].items():
            if not isinstance(profile, dict):
                raise ValueError(f"Profile '{name}' phải là object.")
            for key in ("provider", "model"):
                if not str(profile.get(key, "")).strip():
                    raise ValueError(f"Profile '{name}' thiếu '{key}'.")
            provider = str(profile["provider"]).strip().lower()
            if provider not in {"gemini", "openai_compatible"}:
                raise ValueError(f"Provider '{provider}' không được hỗ trợ. Dùng gemini hoặc openai_compatible.")
            try:
                temperature = float(profile.get("temperature", 0.2))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Profile '{name}' có temperature không hợp lệ.") from exc
            if not 0 <= temperature <= 2:
                raise ValueError(f"Profile '{name}' có temperature ngoài khoảng 0-2.")
            max_tokens = profile.get("max_output_tokens")
            if max_tokens is not None:
                try:
                    if int(max_tokens) < 1:
                        raise ValueError
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"Profile '{name}' có max_output_tokens không hợp lệ.") from exc

    def _write(self, data: dict[str, Any]) -> None:
        self._validate(data)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="model-routing-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, self.path)
            try:
                self._mtime_ns = self.path.stat().st_mtime_ns
            except OSError:
                self._mtime_ns = None
        finally:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass

    def snapshot(self) -> dict[str, Any]:
        self._refresh()
        data = json.loads(json.dumps(self._data, ensure_ascii=False))
        for profile in data.get("profiles", {}).values():
            profile.pop("api_key", None)
        return data

    def profile_for(self, role: str) -> ModelProfile:
        self._refresh()
        if role not in ROLES:
            raise ValueError(f"Unknown model role: {role}")
        name = self._data["role_profiles"][role]
        raw = self._data["profiles"][name]
        allowed = {"provider", "model", "base_url", "api_key_env", "temperature", "max_output_tokens", "api_key"}
        profile = {key: value for key, value in raw.items() if key in allowed}
        profile["profile_name"] = name
        return ModelProfile(**profile)

    def profile_api_key_configured(self, name: str) -> bool:
        self._refresh()
        raw = self._data["profiles"].get(name)
        if not isinstance(raw, dict):
            return False
        if str(raw.get("api_key", "")).strip():
            return True
        env_name = str(raw.get("api_key_env", "")).strip()
        if not env_name:
            provider = str(raw.get("provider", "")).strip().lower()
            env_name = "GEMINI_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"
        return bool(os.getenv(env_name, "").strip())

    def update(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Payload phải là object.")
        self._refresh()
        merged = json.loads(json.dumps(self._data, ensure_ascii=False))
        profiles = payload.get("profiles", merged["profiles"])
        role_profiles = payload.get("role_profiles", merged["role_profiles"])
        if not isinstance(profiles, dict) or not isinstance(role_profiles, dict):
            raise ValueError("profiles và role_profiles phải là object.")
        normalized_profiles: dict[str, dict[str, Any]] = {}
        allowed = {"provider", "model", "base_url", "api_key_env", "temperature", "max_output_tokens", "api_key"}
        for name, profile in profiles.items():
            if not isinstance(profile, dict):
                raise ValueError(f"Profile '{name}' phải là object.")
            normalized = {key: value for key, value in profile.items() if key in allowed}
            if "provider" in normalized:
                normalized["provider"] = str(normalized["provider"]).strip().lower()
            if "model" in normalized:
                normalized["model"] = str(normalized["model"]).strip()
            old = merged["profiles"].get(name, {})
            # An empty key from the form means "keep the currently saved key".
            if not str(normalized.get("api_key", "")).strip() and old.get("api_key"):
                normalized["api_key"] = old["api_key"]
            normalized_profiles[name] = normalized
        merged["profiles"] = normalized_profiles
        merged["role_profiles"] = role_profiles
        self._write(merged)
        self._data = merged
        return self.snapshot()

    def resolve_api_key(self, profile: ModelProfile) -> str:
        if profile.api_key.strip():
            return profile.api_key.strip()
        env_name = profile.api_key_env.strip()
        if not env_name:
            env_name = "GEMINI_API_KEY" if profile.provider.strip().lower() == "gemini" else "OPENAI_API_KEY"
        value = os.getenv(env_name, "").strip()
        if not value:
            # A frozen run keeps its route but may use the latest locally stored
            # credential for that same profile name. Secrets never enter state/DB.
            if self._frozen and profile.profile_name:
                try:
                    live = ModelRouter(self.settings, self.backend_root)
                    current = live._data.get("profiles", {}).get(profile.profile_name, {})
                    key = str(current.get("api_key", "")).strip()
                    if key:
                        return key
                except (OSError, RuntimeError, ValueError):
                    pass
            raise RuntimeError(f"Thiếu API key trong biến môi trường {env_name} cho provider {profile.provider}.")
        return value


def _default_backend_root() -> Path:
    configured = os.getenv("YT_API_BACKEND_ROOT", "").strip() or os.getenv("YOUTUBE_BACKEND_ROOT", "").strip()
    return Path(configured).expanduser().resolve() if configured else Path(__file__).resolve().parents[1]
