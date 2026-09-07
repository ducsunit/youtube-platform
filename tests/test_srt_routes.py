from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from youtube_pipeline.api import app, paths


class SrtRoutesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.run_dir = self.root / "runs" / "srt-run"
        self.run_dir.mkdir(parents=True)
        (self.run_dir / "run_state.json").write_text(
            json.dumps({"run_id": "srt-run", "status": "complete"}), encoding="utf-8"
        )
        self.patch = mock.patch.object(paths, "_BACKEND_ROOT", self.root)
        self.patch.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.patch.stop()
        self.tmp.cleanup()

    def test_status_exposes_supported_options(self) -> None:
        response = self.client.get("/api/srt/status")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("large-v3", body["models"])
        self.assertEqual(set(body["modes"]), {"fast", "accurate"})
        self.assertFalse(body["busy"])

    def test_inputs_report_missing_script_and_audio(self) -> None:
        response = self.client.get("/api/srt/runs/srt-run/inputs")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["script_exists"])
        self.assertFalse(body["audio_exists"])
        self.assertFalse(body["srt_exists"])

    def test_generate_requires_script_and_audio(self) -> None:
        response = self.client.post("/api/srt/runs/srt-run/generate", json={})
        self.assertEqual(response.status_code, 400)
        self.assertIn("script", response.json()["detail"])

    def test_generate_rejects_invalid_options(self) -> None:
        script_dir = self.run_dir / "script"
        audio_dir = self.run_dir / "audio"
        script_dir.mkdir()
        audio_dir.mkdir()
        (script_dir / "script.txt").write_text("テストです。", encoding="utf-8")
        (audio_dir / "narration.wav").write_bytes(b"audio")
        response = self.client.post(
            "/api/srt/runs/srt-run/generate",
            json={"model": "invalid", "device": "cpu", "mode": "fast", "max_chars": 24},
        )
        self.assertEqual(response.status_code, 400)

    def test_scoped_runner_isolates_active_jobs(self) -> None:
        from youtube_pipeline.api.srt_runner import SrtRunner

        runner = SrtRunner()
        proc = mock.Mock()
        proc.poll.return_value = None
        runner._jobs[("dev-user", "channel-a")] = (
            proc,
            {"id": "job-a", "run_id": "run-a", "user_id": "dev-user", "channel_id": "channel-a"},
        )
        self.assertTrue(runner.busy(user_id="dev-user", channel_id="channel-a"))
        self.assertFalse(runner.busy(user_id="dev-user", channel_id="channel-b"))

    def test_generate_starts_runner_without_running_whisper(self) -> None:
        script_dir = self.run_dir / "script"
        audio_dir = self.run_dir / "audio"
        script_dir.mkdir()
        audio_dir.mkdir()
        (script_dir / "script.txt").write_text("テストです。", encoding="utf-8")
        (audio_dir / "narration.wav").write_bytes(b"audio")
        fake = {"id": "job-1", "run_id": "srt-run", "started_at": "now", "output_path": "subtitles/subtitles.srt"}
        with mock.patch("youtube_pipeline.api.srt_routes.srt_runner.start", return_value=fake):
            response = self.client.post(
                "/api/srt/runs/srt-run/generate",
                json={"model": "large-v3", "device": "cpu", "mode": "fast", "max_chars": 24},
            )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["job_id"], "job-1")


if __name__ == "__main__":
    unittest.main()
