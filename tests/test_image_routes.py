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

    def test_scoped_prompts_resolve_channel_run_only(self) -> None:
        scoped = self.root / "users" / "dev-user" / "channels" / "channel-a" / "runs" / "image-run"
        (scoped / "visuals").mkdir(parents=True)
        (scoped / "video-build" / "images").mkdir(parents=True)
        (scoped / "run_state.json").write_text(json.dumps({"run_id": "image-run", "status": "complete"}), encoding="utf-8")
        (scoped / "visuals" / "prompt-pack.json").write_text(json.dumps({"images": [{"image_id": "IMG-07", "prompt": "Scoped prompt."}]}), encoding="utf-8")
        response = self.client.get("/api/images/runs/image-run/prompts?user_id=dev-user&channel_id=channel-a")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["prompts"][0]["image_id"], "IMG-07")

    def test_image_routes_reject_partial_scope(self) -> None:
        response = self.client.get("/api/images/status?user_id=dev-user")
        self.assertEqual(response.status_code, 400)

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

    def test_image_config_isolated_by_channel(self) -> None:
        scope_a = "?user_id=dev-user&channel_id=channel-a"
        scope_b = "?user_id=dev-user&channel_id=channel-b"
        saved = self.client.put("/api/images/config" + scope_a, json={
            "model": "gpt-image-2",
            "base_url": "https://channel-a.invalid/v1",
            "api_key_env": "CHANNEL_A_KEY",
            "default_size": "1152x2048",
            "default_quality": "high",
        })
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(self.client.get("/api/images/config" + scope_a).json()["base_url"], "https://channel-a.invalid/v1")
        self.assertEqual(self.client.get("/api/images/config" + scope_b).json()["base_url"], "https://api.openai.com/v1")
        self.assertEqual(self.client.get("/api/images/config").json()["base_url"], "https://api.openai.com/v1")
        self.assertTrue((self.root / "users/dev-user/channels/channel-a/config/image-generation.json").is_file())

    def test_image_config_rejects_partial_scope(self) -> None:
        self.assertEqual(self.client.get("/api/images/config?user_id=dev-user").status_code, 400)
        self.assertEqual(self.client.put("/api/images/config?channel_id=channel-a", json={}).status_code, 400)

    def test_scoped_runner_isolates_active_jobs_and_job_files(self) -> None:
        runner = ImageRunner()
        proc = mock.Mock()
        proc.poll.return_value = None
        runner._jobs[("dev-user", "channel-a")] = (
            proc,
            {"id": "job-a", "run_id": "run-a", "user_id": "dev-user", "channel_id": "channel-a"},
        )
        self.assertTrue(runner.busy(user_id="dev-user", channel_id="channel-a"))
        self.assertFalse(runner.busy(user_id="dev-user", channel_id="channel-b"))
        self.assertEqual(
            runner.jobs_dir("dev-user", "channel-a"),
            self.root / "users" / "dev-user" / "channels" / "channel-a" / "runtime" / "image-jobs",
        )

    def test_scoped_runner_rejects_partial_scope(self) -> None:
        runner = ImageRunner()
        with self.assertRaises(ValueError):
            runner.busy(user_id="dev-user")

    def test_scoped_job_status_and_log_do_not_fall_back_to_legacy(self) -> None:
        legacy_jobs = self.root / "runtime" / "logs" / "api-image-gen"
        legacy_jobs.mkdir(parents=True)
        (legacy_jobs / "shared.log").write_text("legacy log\n", encoding="utf-8")
        runner = ImageRunner()
        self.assertIsNone(runner.job_status("shared", user_id="dev-user", channel_id="channel-a"))
        self.assertFalse(runner.get_log("shared", 0, 20, user_id="dev-user", channel_id="channel-a")["log_exists"])

    def test_image_job_status_recovers_timestamped_exit_marker(self) -> None:
        jobs = self.root / "runtime" / "logs" / "api-image-gen"
        jobs.mkdir(parents=True)
        (jobs / "finished.log").write_text(
            "=== exit 2026-08-19T00:00:00+00:00 code=0 ===\n", encoding="utf-8"
        )
        status = ImageRunner().job_status("finished")
        self.assertEqual(status["status"], "complete")
        self.assertEqual(status["exit_code"], 0)
