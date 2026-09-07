"""Persistent runtime configuration for the GPT image generation service."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


DEFAULT_IMAGE_CONFIG = {
    "model": "gpt-image-2",
    "base_url": "https://api.openai.com/v1",
    "api_key_env": "OPENAI_API_KEY",
    "api_key": "",
    "default_size": "1024x576",
    "default_quality": "medium",
}
SUPPORTED_MODELS = ("gpt-image-2",)
SUPPORTED_SIZES = (
    "1024x1024", "1024x576", "576x1024",
    "2048x2048", "2048x1152", "1152x2048",
    "3840x3840", "3840x2160", "2160x3840",
)
SUPPORTED_QUALITIES = ("low", "medium", "high")


def normalize_base_url(value: Any) -> str:
    """OpenAI SDK expects the API root, not /images/generations itself."""
    url = str(value or "").strip().rstrip("/")
    suffix = "/images/generations"
    if url.endswith(suffix):
        url = url[: -len(suffix)].rstrip("/")
    return url or DEFAULT_IMAGE_CONFIG["base_url"]


def config_path(root: Path) -> Path:
    return root / "config" / "image-generation.json"


def scoped_config_path(root: Path, user_id: str, channel_id: str) -> Path:
    """Return the per-channel image config path under the channel root."""
    from .api.paths import channel_config_dir

    return channel_config_dir(user_id, channel_id) / "image-generation.json"


def _validate(data: dict[str, Any]) -> None:
    if str(data.get("model", "")).strip() not in SUPPORTED_MODELS:
        raise ValueError("GPT image model không được hỗ trợ.")
    if str(data.get("default_size", "")).strip() not in SUPPORTED_SIZES:
        raise ValueError("default_size không hợp lệ.")
    if str(data.get("default_quality", "")).strip() not in SUPPORTED_QUALITIES:
        raise ValueError("default_quality không hợp lệ.")
    if not str(data.get("api_key_env", "")).strip():
        raise ValueError("api_key_env không được để trống.")


def _load_path(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return dict(DEFAULT_IMAGE_CONFIG)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Không đọc được image-generation.json.") from exc
    merged = {**DEFAULT_IMAGE_CONFIG, **data}
    merged["base_url"] = normalize_base_url(merged.get("base_url"))
    _validate(merged)
    return merged


def load(root: Path, user_id: str | None = None, channel_id: str | None = None) -> dict[str, Any]:
    if bool(user_id) != bool(channel_id):
        raise ValueError("user_id và channel_id phải được truyền cùng nhau")
    if user_id and channel_id:
        # A selected channel must never inherit the legacy global config: it
        # may contain another channel's saved API key and provider settings.
        # Channels begin with safe defaults and must be configured explicitly.
        return _load_path(scoped_config_path(root, user_id, channel_id))
    return _load_path(config_path(root))


def snapshot(root: Path, user_id: str | None = None, channel_id: str | None = None) -> dict[str, Any]:
    data = load(root, user_id, channel_id)
    saved_key = str(data.get("api_key", "")).strip()
    data.pop("api_key", None)
    env_name = str(data.get("api_key_env", "OPENAI_API_KEY"))
    data["api_key_configured"] = bool(saved_key or os.environ.get(env_name, "").strip())
    data["models"] = list(SUPPORTED_MODELS)
    data["sizes"] = list(SUPPORTED_SIZES)
    data["qualities"] = list(SUPPORTED_QUALITIES)
    return data


def update(root: Path, payload: dict[str, Any], user_id: str | None = None, channel_id: str | None = None) -> dict[str, Any]:
    current = load(root, user_id, channel_id)
    if bool(user_id) != bool(channel_id):
        raise ValueError("user_id và channel_id phải được truyền cùng nhau")
    path = scoped_config_path(root, user_id, channel_id) if user_id and channel_id else config_path(root)
    merged = {**current, **{key: value for key, value in payload.items() if key in DEFAULT_IMAGE_CONFIG}}
    merged["base_url"] = normalize_base_url(merged.get("base_url"))
    if not str(merged.get("api_key", "")).strip():
        merged["api_key"] = current.get("api_key", "")
    _validate(merged)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="image-generation-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(merged, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
    return snapshot(root, user_id, channel_id)


def resolve_api_key(root: Path, user_id: str | None = None, channel_id: str | None = None) -> str:
    data = load(root, user_id, channel_id)
    saved = str(data.get("api_key", "")).strip()
    if saved:
        return saved
    env_name = str(data.get("api_key_env", "OPENAI_API_KEY")).strip()
    value = os.environ.get(env_name, "").strip()
    if value:
        return value
    env_file = root / ".env"
    if env_file.is_file():
        try:
            from dotenv import dotenv_values

            return str(dotenv_values(env_file).get(env_name) or "").strip()
        except Exception:
            return ""
    return ""
