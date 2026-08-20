from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class ConfigurationError(RuntimeError):
    """Raised when required runtime configuration is missing or invalid."""


def channel_data_path_from_env() -> Optional[Path]:
    value = os.getenv("YOUTUBE_CHANNEL_DATA_FILE", "").strip()
    return Path(value).expanduser() if value else None


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str
    deepseek_api_key: str
    gemini_analysis_model: str = "gemini-2.5-flash"
    gemini_review_model: str = "gemini-2.5-pro"
    gemini_audit_model: str = "gemini-2.5-flash"
    deepseek_model: str = "deepseek-chat"
    deepseek_audit_model: str = "deepseek-chat"
    deepseek_base_url: str = "https://api.deepseek.com"
    max_retries: int = 3
    consistency_min_score: int = 90
    consistency_max_rounds: int = 2
    duration_tolerance: float = 0.25

    @classmethod
    def from_env(cls, require_keys: bool = True) -> "Settings":
        gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        deepseek_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        # Runtime routing resolves credentials per profile; the resource-pack CLI
        # therefore calls this with require_keys=False when keys live in routing.
        if require_keys:
            missing = [
                name
                for name, value in (
                    ("GEMINI_API_KEY", gemini_key),
                    ("DEEPSEEK_API_KEY", deepseek_key),
                )
                if not value
            ]
            if missing:
                raise ConfigurationError(
                    "Thieu bien moi truong: %s. Hay tao file .env tu .env.example."
                    % ", ".join(missing)
                )
        try:
            max_retries = int(os.getenv("API_MAX_RETRIES", "3"))
        except ValueError as exc:
            raise ConfigurationError("API_MAX_RETRIES phai la so nguyen.") from exc
        if max_retries < 1:
            raise ConfigurationError("API_MAX_RETRIES phai lon hon hoac bang 1.")
        try:
            consistency_min_score = int(os.getenv("CONSISTENCY_MIN_SCORE", "90"))
            consistency_max_rounds = int(os.getenv("CONSISTENCY_MAX_ROUNDS", "2"))
            duration_tolerance = float(os.getenv("DURATION_TOLERANCE", "0.25"))
        except ValueError as exc:
            raise ConfigurationError("Cấu hình consistency phải là số hợp lệ.") from exc
        if not 0 <= consistency_min_score <= 100:
            raise ConfigurationError("CONSISTENCY_MIN_SCORE phải từ 0 đến 100.")
        if consistency_max_rounds < 1:
            raise ConfigurationError("CONSISTENCY_MAX_ROUNDS phải lớn hơn hoặc bằng 1.")
        if not 0 <= duration_tolerance <= 1:
            raise ConfigurationError("DURATION_TOLERANCE phải từ 0 đến 1.")
        return cls(
            gemini_api_key=gemini_key,
            deepseek_api_key=deepseek_key,
            gemini_analysis_model=os.getenv(
                "GEMINI_ANALYSIS_MODEL", "gemini-2.5-flash"
            ),
            gemini_review_model=os.getenv("GEMINI_REVIEW_MODEL", "gemini-2.5-pro"),
            gemini_audit_model=os.getenv(
                "GEMINI_AUDIT_MODEL",
                os.getenv("GEMINI_ANALYSIS_MODEL", "gemini-2.5-flash"),
            ),
            deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            deepseek_audit_model=os.getenv(
                "DEEPSEEK_AUDIT_MODEL", os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
            ),
            deepseek_base_url=os.getenv(
                "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
            ),
            max_retries=max_retries,
            consistency_min_score=consistency_min_score,
            consistency_max_rounds=consistency_max_rounds,
            duration_tolerance=duration_tolerance,
        )
