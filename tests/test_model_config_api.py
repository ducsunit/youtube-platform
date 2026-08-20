from fastapi.testclient import TestClient

from youtube_pipeline.api import create_app
from youtube_pipeline.api import paths


def test_model_config_api_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUTUBE_BACKEND_ROOT", str(tmp_path))
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test")
    client = TestClient(create_app())
    response = client.get("/api/model-config")
    assert response.status_code == 200
    data = response.json()
    assert "writer" in data["profiles"]
    assert data["profiles"]["writer"]["api_key_configured"] is True

    profiles = data["profiles"]
    profiles["writer"]["provider"] = "openai_compatible"
    profiles["writer"]["model"] = "gpt-test"
    profiles["writer"]["base_url"] = "https://example.invalid/v1"
    saved = client.put("/api/model-config", json={"profiles": profiles, "role_profiles": data["role_profiles"]})
    assert saved.status_code == 200
    assert saved.json()["profiles"]["writer"]["model"] == "gpt-test"
