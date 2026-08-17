from __future__ import annotations

import os

from youtube_pipeline.config import Settings


def test_quality_policy_is_single_production(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test")
    monkeypatch.setenv("PIPELINE_QUALITY_MODE", "max")
    monkeypatch.setenv("CONSISTENCY_MAX_ROUNDS", "9")

    settings = Settings.from_env()

    assert settings.quality_mode == "production"
    assert settings.consistency_max_rounds == 1
