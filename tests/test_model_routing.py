import json
import os
from pathlib import Path

from youtube_pipeline.config import Settings
from youtube_pipeline.model_router import ModelRouter
from youtube_pipeline.resource_pack.pipeline import ResourcePackPipeline
from youtube_pipeline.resource_pack.providers import DemoResourceProvider


def _settings():
    return Settings.from_env(require_keys=False)


def test_default_router_and_role_mapping(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "d")
    router = ModelRouter(_settings(), tmp_path)
    assert router.profile_for("analysis").provider == "gemini"
    assert router.profile_for("writer").provider == "openai_compatible"
    assert (tmp_path / "config" / "model-routing.json").exists()


def test_update_router_is_atomic_and_persistent(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    router = ModelRouter(_settings(), tmp_path)
    data = router.update({
        "profiles": {
            **router.snapshot()["profiles"],
            "writer": {
                "provider": "openai_compatible",
                "model": "gpt-test",
                "base_url": "https://example.invalid/v1",
                "api_key_env": "OPENAI_API_KEY",
                "temperature": 0.4,
                "max_output_tokens": 4096,
            },
        },
        "role_profiles": {**router.snapshot()["role_profiles"], "writer": "writer"},
    })
    assert data["profiles"]["writer"]["model"] == "gpt-test"
    reloaded = ModelRouter(_settings(), tmp_path)
    assert reloaded.profile_for("writer").model == "gpt-test"


def test_existing_router_reloads_changes_from_ui(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    router = ModelRouter(_settings(), tmp_path)
    writer = router.snapshot()["profiles"]["writer"]
    updater = ModelRouter(_settings(), tmp_path)
    writer["model"] = "gpt-updated"
    updater.update({"profiles": {**updater.snapshot()["profiles"], "writer": writer}, "role_profiles": updater.snapshot()["role_profiles"]})
    assert router.profile_for("writer").model == "gpt-updated"


def test_frozen_router_keeps_route_after_ui_config_changes(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    router = ModelRouter(_settings(), tmp_path)
    frozen = ModelRouter.from_snapshot(_settings(), router.snapshot(), tmp_path)
    updater = ModelRouter(_settings(), tmp_path)
    profiles = updater.snapshot()["profiles"]
    profiles["writer"]["model"] = "new-live-model"
    updater.update({"profiles": profiles, "role_profiles": updater.snapshot()["role_profiles"]})
    assert router.profile_for("writer").model == "new-live-model"
    assert frozen.profile_for("writer").model != "new-live-model"


def test_new_state_stores_redacted_routing_snapshot(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    router = ModelRouter(_settings(), tmp_path)
    profiles = router.snapshot()["profiles"]
    profiles["writer"]["api_key"] = "must-not-be-persisted"
    router.update({"profiles": profiles, "role_profiles": router.snapshot()["role_profiles"]})

    class Provider:
        pass

    provider = Provider()
    provider.router = router
    pipeline = ResourcePackPipeline(provider, tmp_path / "runs" / "routing-snapshot")
    state = pipeline.create_state('{"schema_version": 2, "videos": {}}', run_id="routing-snapshot")
    snapshot = state.config_snapshot["model_routing"]
    assert snapshot["profiles"]["writer"]["model"]
    assert all("api_key" not in profile for profile in snapshot["profiles"].values())


def test_production_review_does_not_require_score_telemetry(tmp_path):
    class NoScoreProvider(DemoResourceProvider):
        def review_script(self, contract, plan, source_pack, draft, competitor_context=""):
            return {
                "decision": "pass",
                "optimization_report": "問題なし。",
                "issues": [],
                "required_changes": [],
                "revised_draft_clean": draft,
                "tts_tag_anchors": [],
                "char_report": {},
            }

    run_dir = tmp_path / "runs" / "no-score"
    pipeline = ResourcePackPipeline(NoScoreProvider(), run_dir, max_retries=1, retry_delay=0, progress=lambda _message: None)
    state = pipeline.create_state('{"schema_version": 2, "videos": {}}', run_id="no-score")
    completed = pipeline.run(state)
    assert completed.status == "complete"
    report = json.loads((run_dir / "script/review-report.json").read_text(encoding="utf-8"))
    assert "score_report" not in report


def test_missing_api_key_reports_env_name(tmp_path, monkeypatch):
    for name in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    router = ModelRouter(_settings(), tmp_path)
    try:
        router.resolve_api_key(router.profile_for("writer"))
    except RuntimeError as exc:
        assert "DEEPSEEK_API_KEY" in str(exc)
    else:
        raise AssertionError("expected missing API key error")


def test_runtime_api_key_is_saved_but_never_exposed(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    router = ModelRouter(_settings(), tmp_path)
    data = router.update({
        "profiles": {
            **router.snapshot()["profiles"],
            "writer": {
                "provider": "openai_compatible",
                "model": "gpt-runtime",
                "base_url": "https://example.invalid/v1",
                "api_key_env": "OPENAI_API_KEY",
                "api_key": "runtime-secret",
                "temperature": 0.2,
                "max_output_tokens": 1024,
            },
        },
        "role_profiles": router.snapshot()["role_profiles"],
    })
    assert "api_key" not in data["profiles"]["writer"]
    assert router.resolve_api_key(router.profile_for("writer")) == "runtime-secret"
    assert router.profile_api_key_configured("writer") is True

    # A blank form value keeps the existing secret instead of deleting it.
    current = router.snapshot()
    current["profiles"]["writer"]["api_key"] = ""
    router.update({"profiles": current["profiles"], "role_profiles": current["role_profiles"]})
    assert router.resolve_api_key(router.profile_for("writer")) == "runtime-secret"
