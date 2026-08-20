from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from youtube_pipeline.api import app, paths
from youtube_pipeline.api.image_runner import ImageRunner


class ImageRoutesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        run = self.root / "runs" / "image-run"
        (run / "visuals").mkdir(parents=True)
        (run / "video-build" / "images").mkdir(parents=True)
        (run / "run_state.json").write_text(json.dumps({"run_id": "image-run", "status": "complete"}), encoding="utf-8")
        (run / "visuals" / "prompt-pack.json").write_text(json.dumps({"images": [{"image_id": "IMG-01", "prompt": "A Japanese editorial illustration, 16:9."}, {"image_id": "IMG-02", "prompt": "A quiet illustrated room, 16:9."}]}), encoding="utf-8")
        self.patch = mock.patch.object(paths, "_BACKEND_ROOT", self.root)
        self.patch.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.patch.stop()
        self.tmp.cleanup()

    def test_prompt_pack_is_loaded_and_generated_state_is_reported(self) -> None:
        response = self.client.get("/api/images/runs/image-run/prompts")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 2)
        self.assertEqual(body["generated"], 0)
        self.assertEqual(body["prompts"][0]["image_id"], "IMG-01")

    def test_generation_requires_key(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            response = self.client.post("/api/images/runs/image-run/generate", json={"images": ["IMG-01"]})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["key"], "images.noKey")

    def test_image_config_is_persistent_and_redacts_key(self) -> None:
        response = self.client.get("/api/images/config")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["model"], "gpt-image-2")
        self.assertNotIn("api_key", response.json())

        saved = self.client.put("/api/images/config", json={
            "model": "gpt-image-2",
            "base_url": "https://example.invalid/v1",
            "api_key_env": "TEST_IMAGE_KEY",
            "api_key": "runtime-secret",
            "default_size": "576x1024",
            "default_quality": "high",
        })
        self.assertEqual(saved.status_code, 200)
        self.assertTrue(saved.json()["api_key_configured"])
        self.assertNotIn("api_key", saved.json())
        self.assertEqual(self.client.get("/api/images/config").json()["default_size"], "576x1024")

    def test_image_config_rejects_invalid_defaults(self) -> None:
        response = self.client.put("/api/images/config", json={"default_size": "4:3"})
        self.assertEqual(response.status_code, 400)

    def test_image_job_status_recovers_timestamped_exit_marker(self) -> None:
        jobs = self.root / "runtime" / "logs" / "api-image-gen"
        jobs.mkdir(parents=True)
        (jobs / "finished.log").write_text(
            "=== exit 2026-08-19T00:00:00+00:00 code=0 ===\n", encoding="utf-8"
        )
        status = ImageRunner().job_status("finished")
        self.assertEqual(status["status"], "complete")
        self.assertEqual(status["exit_code"], 0)
