"""Test tab "Gen video" (api/veo/*) — Veo API KHÔNG bao giờ được gọi thật.

Job spawn bằng python thật (sys.executable) nhưng `veo_gen_command` bị patch
thành script giả in log rồi exit — nên test nhanh, không cần mạng, không tốn
quota Veo. Phần parse prompts-video.txt + tìm ảnh nguồn test trực tiếp.
"""
from __future__ import annotations

import json
import os
import struct
import sys
import tempfile
import time
import unittest
import zlib
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from youtube_pipeline.api import app, paths, veo_routes
from youtube_pipeline.api.veo_runner import veo_runner
from youtube_pipeline.veo_gen import (
    _build_veo_prompt,
    _find_image,
    _parse_prompts_video,
)

# Script giả thay cho veo_gen: in log rồi exit theo env.
FAKE_FAST = (
    "import sys;"
    "print('[IMG-01] fake clip ok', flush=True);"
    "sys.exit(int(__import__('os').environ.get('YT_VEO_STUB_EXIT', '0')))"
)
FAKE_SLOW = "import time; print('start', flush=True); time.sleep(60)"

PROMPTS_TXT = """\
# AUTO-GENERATED bởi stage image_prompts — comment phải bị bỏ qua.
# Dòng thứ hai cũng là comment.

IMG-01 | slow push-in across the table — A cinematic photorealistic scene, dark library, warm tungsten light.
IMG-02 | static hold with subtle glow — Another cinematic photorealistic scene.
IMG-47 | lateral tracking shot — Final CTA screen, cinematic photorealistic, black-brown-gold palette.
"""


def _tiny_png() -> bytes:
    """PNG 1x1 hợp lệ tối thiểu — đủ để _find_image thấy file."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
        + chunk(b"IEND", b"")
    )


class VeoParseTestCase(unittest.TestCase):
    """Parse prompts-video.txt + ghép prompt — thuần logic, không spawn gì."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_parse_skips_comments_and_blank_lines(self) -> None:
        f = self.dir / "prompts-video.txt"
        f.write_text(PROMPTS_TXT, encoding="utf-8")
        parsed = _parse_prompts_video(f)
        self.assertEqual(sorted(parsed), ["01", "02", "47"])

    def test_parse_splits_motion_and_prompt(self) -> None:
        f = self.dir / "prompts-video.txt"
        f.write_text(PROMPTS_TXT, encoding="utf-8")
        parsed = _parse_prompts_video(f)
        self.assertEqual(parsed["01"]["motion"], "slow push-in across the table")
        self.assertTrue(parsed["01"]["prompt"].startswith("A cinematic photorealistic scene"))
        self.assertNotIn("—", parsed["01"]["prompt"])

    def test_parse_missing_file_returns_empty(self) -> None:
        self.assertEqual(_parse_prompts_video(self.dir / "nope.txt"), {})

    def test_build_prompt_prefixes_motion(self) -> None:
        self.assertEqual(_build_veo_prompt("slow push-in", "A scene."), "slow push-in. A scene.")
        self.assertEqual(_build_veo_prompt("", "A scene."), "A scene.")

    def test_find_image_tries_known_extensions(self) -> None:
        (self.dir / "IMG-03.jpg").write_bytes(b"x")
        self.assertIsNotNone(_find_image(self.dir, "03"))
        self.assertIsNone(_find_image(self.dir, "04"))


class VeoApiTestCase(unittest.TestCase):
    """Fixture: backend root giả + 1 run có prompts-video.txt và ảnh nguồn."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.run_id = "t-veo"
        self.run_dir = self.root / "runs" / self.run_id
        (self.run_dir / "visuals" / "prompts").mkdir(parents=True)
        self.images_dir = self.run_dir / "video-build" / "images"
        self.images_dir.mkdir(parents=True)
        (self.run_dir / "run_state.json").write_text(
            json.dumps({"run_id": self.run_id, "stages": []}), encoding="utf-8"
        )
        (self.run_dir / "visuals" / "prompts" / "prompts-video.txt").write_text(
            PROMPTS_TXT, encoding="utf-8"
        )
        for idx in ("01", "02"):
            (self.images_dir / ("IMG-%s.png" % idx)).write_bytes(_tiny_png())

        self.root_patcher = mock.patch.object(paths, "_BACKEND_ROOT", self.root)
        self.root_patcher.start()
        self.env_patcher = mock.patch.dict(os.environ, {"GEMINI_API_KEY": "fake-test-key"})
        self.env_patcher.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        deadline = time.monotonic() + 5
        while veo_runner.busy() and time.monotonic() < deadline:
            active = veo_runner.active_job()
            if active is not None:
                veo_runner.cancel(active["id"])
            time.sleep(0.05)
        self.env_patcher.stop()
        self.root_patcher.stop()
        self._tmp.cleanup()

    # -------------------------------------------------------------- helpers

    def patch_command(self, code: str):
        return mock.patch.object(
            veo_routes,
            "veo_gen_command",
            lambda run_dir, indices, model: [sys.executable, "-u", "-c", code],
        )

    def wait_job(self, job_id: str, timeout: float = 15.0) -> dict:
        deadline = time.monotonic() + timeout
        status = {}
        while time.monotonic() < deadline:
            status = self.client.get("/api/veo/jobs/%s" % job_id).json()
            if status.get("status") != "running":
                return status
            time.sleep(0.1)
        return status

    def start_job(self, images=("01",), **body):
        payload = {"images": list(images)}
        payload.update(body)
        return self.client.post(
            "/api/veo/runs/%s/generate" % self.run_id, json=payload
        )

    # --------------------------------------------------------------- status

    def test_status_reports_key_and_models(self) -> None:
        r = self.client.get("/api/veo/status")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["has_api_key"])
        self.assertIn("veo-3.1-generate-preview", body["models"])
        self.assertFalse(body["busy"])

    def test_status_detects_key_from_dotenv_file(self) -> None:
        """Server không load_dotenv — key trong .env vẫn phải được thấy."""
        (self.root / ".env").write_text("GOOGLE_API_KEY=from-dotenv\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GEMINI_API_KEY", None)
            os.environ.pop("GOOGLE_API_KEY", None)
            self.assertTrue(veo_routes._has_api_key())

    def test_status_without_key_is_unavailable(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GEMINI_API_KEY", None)
            os.environ.pop("GOOGLE_API_KEY", None)
            r = self.client.get("/api/veo/status")
            self.assertFalse(r.json()["has_api_key"])
            self.assertFalse(r.json()["available"])

    # ----------------------------------------------------------- candidates

    def test_candidates_lists_prompts_with_image_state(self) -> None:
        r = self.client.get("/api/veo/runs/%s/candidates" % self.run_id)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["prompts_file_exists"])
        self.assertEqual(body["total"], 3)
        self.assertEqual(body["images_ready"], 2)  # IMG-01, IMG-02 có ảnh
        self.assertEqual(body["clips_done"], 0)
        by_name = {c["name"]: c for c in body["candidates"]}
        self.assertTrue(by_name["IMG-01"]["image_exists"])
        self.assertFalse(by_name["IMG-47"]["image_exists"])
        self.assertEqual(by_name["IMG-01"]["motion"], "slow push-in across the table")

    def test_candidates_reports_existing_clip(self) -> None:
        clips = self.run_dir / "video-build" / "clips"
        clips.mkdir(parents=True)
        (clips / "IMG-01.mp4").write_bytes(b"fake-mp4-bytes")
        body = self.client.get("/api/veo/runs/%s/candidates" % self.run_id).json()
        img01 = next(c for c in body["candidates"] if c["name"] == "IMG-01")
        self.assertTrue(img01["clip_exists"])
        self.assertEqual(img01["clip_size_bytes"], len(b"fake-mp4-bytes"))
        self.assertEqual(img01["clip_path"], "video-build/clips/IMG-01.mp4")
        self.assertEqual(body["clips_done"], 1)

    def test_candidates_unknown_run_404(self) -> None:
        self.assertEqual(self.client.get("/api/veo/runs/nope/candidates").status_code, 404)

    def test_candidates_without_prompts_file(self) -> None:
        (self.run_dir / "visuals" / "prompts" / "prompts-video.txt").unlink()
        body = self.client.get("/api/veo/runs/%s/candidates" % self.run_id).json()
        self.assertFalse(body["prompts_file_exists"])
        self.assertEqual(body["candidates"], [])

    # ------------------------------------------------------------ validate

    def test_generate_rejects_empty_selection(self) -> None:
        r = self.start_job(images=())
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["detail"]["key"], "veo.noImages")

    def test_generate_rejects_bad_index(self) -> None:
        r = self.start_job(images=("../../etc/passwd",))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["detail"]["key"], "veo.badIndex")

    def test_generate_rejects_too_many(self) -> None:
        r = self.start_job(images=tuple("%02d" % i for i in range(1, 25)))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["detail"]["key"], "veo.tooMany")

    def test_generate_rejects_unknown_model(self) -> None:
        r = self.start_job(model="gpt-4-turbo")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["detail"]["key"], "veo.badModel")

    def test_generate_rejects_missing_source_image(self) -> None:
        r = self.start_job(images=("47",))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["detail"]["key"], "veo.missingImages")
        self.assertEqual(r.json()["detail"]["missing"], ["47"])

    def test_generate_rejects_without_api_key(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GEMINI_API_KEY", None)
            os.environ.pop("GOOGLE_API_KEY", None)
            r = self.start_job()
            self.assertEqual(r.status_code, 400)
            self.assertEqual(r.json()["detail"]["key"], "veo.noKey")

    def test_generate_accepts_img_prefixed_indices(self) -> None:
        with self.patch_command(FAKE_FAST):
            r = self.start_job(images=("IMG-01", "01"))
            self.assertEqual(r.status_code, 202)
            self.assertEqual(r.json()["images"], ["01"])  # dedupe + strip prefix
            self.wait_job(r.json()["job_id"])

    # ---------------------------------------------------------- job đầy đủ

    def test_job_runs_and_streams_log(self) -> None:
        with self.patch_command(FAKE_FAST):
            r = self.start_job()
            self.assertEqual(r.status_code, 202)
            job_id = r.json()["job_id"]
            status = self.wait_job(job_id)
        self.assertEqual(status["status"], "complete")
        self.assertEqual(status["exit_code"], 0)
        log = self.client.get("/api/veo/jobs/%s/log" % job_id).json()
        text = "\n".join(log["lines"])
        self.assertIn("fake clip ok", text)
        self.assertIn("exit code 0", text)

    def test_job_failure_surfaces_exit_code(self) -> None:
        with mock.patch.dict(os.environ, {"YT_VEO_STUB_EXIT": "1"}):
            with self.patch_command(FAKE_FAST):
                r = self.start_job()
                status = self.wait_job(r.json()["job_id"])
        self.assertEqual(status["status"], "failed")
        self.assertEqual(status["exit_code"], 1)

    def test_second_job_conflicts_with_409(self) -> None:
        with self.patch_command(FAKE_SLOW):
            first = self.start_job()
            self.assertEqual(first.status_code, 202)
            deadline = time.monotonic() + 5
            while not veo_runner.busy() and time.monotonic() < deadline:
                time.sleep(0.05)
            second = self.start_job(images=("02",))
            self.assertEqual(second.status_code, 409)
            self.assertEqual(second.json()["detail"]["key"], "busy")
            self.assertEqual(
                second.json()["detail"]["active_job_id"], first.json()["job_id"]
            )

    def test_cancel_stops_running_job(self) -> None:
        with self.patch_command(FAKE_SLOW):
            r = self.start_job()
            job_id = r.json()["job_id"]
            deadline = time.monotonic() + 5
            while not veo_runner.busy() and time.monotonic() < deadline:
                time.sleep(0.05)
            cancelled = self.client.post("/api/veo/jobs/%s/cancel" % job_id).json()
            self.assertTrue(cancelled["cancelled"])
            status = self.wait_job(job_id)
        self.assertEqual(status["status"], "failed")
        self.assertFalse(veo_runner.busy())

    def test_unknown_job_404(self) -> None:
        self.assertEqual(self.client.get("/api/veo/jobs/deadbeef").status_code, 404)


if __name__ == "__main__":
    unittest.main()
