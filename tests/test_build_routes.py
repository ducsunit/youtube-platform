"""Test API Dựng video (/api/build/*) — check trạng thái tài nguyên + job.

Fixture chung: 1 run demo thật (DemoResourceProvider — chạy nhanh) trong
TemporaryDirectory làm backend root, patch paths._BACKEND_ROOT một lần cho cả
class. Job spawn được mock — không chạy subprocess thật trong test.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from youtube_pipeline.api import app, paths
from youtube_pipeline.api.build_runner import build_runner
from youtube_pipeline.resource_pipeline import ResourcePackPipeline
from youtube_pipeline.resource_provider import DemoResourceProvider


class BuildApiTestCase(unittest.TestCase):
    """Chung: backend root là tmp chứa 1 run demo đầy đủ artifact."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        # Run demo thật — sinh đủ artifact pipeline (planning, sections, storyboard…).
        # Pipeline demo ghi state ở root (CLI --output-dir); API đọc theo layout
        # runs/<run_id>/ nên copy nguyên cây artifact vào đúng chỗ.
        pipeline = ResourcePackPipeline(
            DemoResourceProvider(), cls.root, max_retries=1, retry_delay=0,
            progress=lambda _message: None,
        )
        state = pipeline.create_state(
            json.dumps({"schema_version": 2, "videos": {}}, ensure_ascii=False),
            run_id="demo-run",
        )
        pipeline.run(state)
        run_dir = cls.root / "runs" / "demo-run"
        run_dir.mkdir(parents=True, exist_ok=True)
        for child in cls.root.iterdir():
            if child.name == "runs":
                continue
            if child.is_dir():
                shutil.copytree(child, run_dir / child.name, dirs_exist_ok=True)
            else:
                shutil.copy2(child, run_dir / child.name)
        cls._patcher = mock.patch.object(paths, "_BACKEND_ROOT", cls.root)
        cls._patcher.start()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._patcher.stop()
        cls._tmp.cleanup()


class TestBuildStatus(BuildApiTestCase):
    def test_status_run_not_found(self) -> None:
        r = self.client.get("/api/build/runs/ghost/status")
        self.assertEqual(r.status_code, 404)

    def test_status_missing_artifacts(self) -> None:
        run_dir = self.root / "runs" / "bare-run"
        run_dir.mkdir(parents=True)
        (run_dir / "run_state.json").write_text(
            json.dumps({"schema_version": 2, "run_id": "bare-run", "status": "running",
                        "stage_records": {}}), encoding="utf-8"
        )
        r = self.client.get("/api/build/runs/bare-run/status")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body["pipeline_ready"])
        self.assertTrue(body["missing_artifacts"])
        self.assertIn("missing_reason", body)
        self.assertIsNone(body["timeline_status"])

    def test_status_demo_run_waits_for_audio(self) -> None:
        r = self.client.get("/api/build/runs/demo-run/status")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["pipeline_ready"])
        self.assertEqual(body["timeline_status"], "DRAFT_TIMING")
        self.assertFalse(body["audio_ready"])
        self.assertIsNone(body["audio"])
        self.assertGreater(body["sections_count"], 0)
        self.assertGreater(body["events_count"], 0)
        self.assertGreater(body["unique_images"], 0)
        self.assertTrue(body["images"]["missing"])
        self.assertFalse(body["images_ready"])
        self.assertFalse(body["pack_ready"])
        self.assertIsNone(body["last_report"])
        # Skeleton thư mục được tạo sẵn cho người dùng bỏ file vào.
        self.assertTrue((self.root / "runs" / "demo-run" / "audio").is_dir())
        self.assertTrue(body["tts_chunks"]["available"])
        self.assertGreater(body["tts_chunks"]["total"], 0)
        self.assertEqual(body["tts_chunks"]["generated"], 0)
        self.assertTrue((self.root / "runs" / "demo-run" / "script" / "audio-chunks" / "manifest.json").is_file())
        self.assertTrue((self.root / "runs" / "demo-run" / "video-build" / "images").is_dir())

    def test_status_run_id_invalid(self) -> None:
        r = self.client.get("/api/build/runs/bad%2Fid/status")
        self.assertIn(r.status_code, (400, 404))

    def test_status_tool_and_pack_files_flow_moi(self) -> None:
        """Flow mới: tool chỉ còn build_video_script (không edit_video_root);
        pack_files chỉ 2 file tự sinh (không script_txt)."""
        r = self.client.get("/api/build/runs/demo-run/status")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertNotIn("edit_video_root", body["tool"])
        self.assertIn("build-video.py", body["tool"]["build_video_script"])
        self.assertEqual(set(body["pack_files"]), {"prompts_build", "marks_tsv"})


class TestStartBuild(BuildApiTestCase):
    def _fake_start(self, job: dict):
        return mock.patch.object(
            build_runner, "start",
            return_value={"id": job["id"], "run_id": "demo-run", "started_at": "t"},
        )

    def test_start_validation(self) -> None:
        for bad, label in (
            ({"transition": "x"}, "transition string"),
            ({"transition": 5}, "transition quá 2s"),
            ({"resolution": [100]}, "resolution 1 phần tử"),
            ({"resolution": ["a", 1]}, "resolution không phải int"),
            ({"resolution": [1, 2]}, "resolution nhỏ hơn 64"),
            ({"render": "yes"}, "render không boolean"),
            ({"animation": "spin"}, "animation sai giá trị"),
            ({"animation": 5}, "animation không phải str"),
            ({"dry_run": "yes"}, "dry_run không boolean"),
            ({"subtitles": 1}, "subtitles không boolean"),
        ):
            r = self.client.post("/api/build/runs/demo-run/build", json=bad)
            self.assertEqual(r.status_code, 400, label)

    def test_start_run_not_found(self) -> None:
        r = self.client.post("/api/build/runs/ghost/build", json={})
        self.assertEqual(r.status_code, 404)

    def test_start_busy_409(self) -> None:
        fake_proc = mock.Mock()
        fake_proc.poll.return_value = None
        with mock.patch.object(build_runner, "_proc", fake_proc), mock.patch.object(
            build_runner, "_job", {"id": "busy-job", "run_id": "x", "started_at": "t", "log_path": "p"}
        ):
            r = self.client.post("/api/build/runs/demo-run/build", json={})
        self.assertEqual(r.status_code, 409)
        detail = r.json()["detail"]
        self.assertEqual(detail["key"], "busy")
        self.assertEqual(detail["active_job_id"], "busy-job")

    def test_start_spawns_job(self) -> None:
        with self._fake_start({"id": "job-abc"}) as start_mock, mock.patch.object(
            build_runner, "_active_unlocked", return_value=None
        ):
            r = self.client.post(
                "/api/build/runs/demo-run/build",
                json={"motion": False, "transition": 0.3, "resolution": [720, 1280], "render": True},
            )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["job_id"], "job-abc")
        argv = start_mock.call_args.args[1]
        self.assertEqual(argv[0], mock.ANY)
        self.assertIn("-m", argv)
        self.assertIn("youtube_pipeline.build_service", argv)
        self.assertIn("--no-motion", argv)
        self.assertIn("--transition", argv)
        self.assertIn("--resolution", argv)
        self.assertIn("720x1280", argv)

    def test_start_prepare_only_flag(self) -> None:
        with self._fake_start({"id": "job-prep"}) as start_mock, mock.patch.object(
            build_runner, "_active_unlocked", return_value=None
        ):
            r = self.client.post("/api/build/runs/demo-run/build", json={"render": False})
        self.assertEqual(r.status_code, 200)
        argv = start_mock.call_args.args[1]
        self.assertIn("--prepare-only", argv)

    def test_start_new_options_flags(self) -> None:
        with self._fake_start({"id": "job-anim"}) as start_mock, mock.patch.object(
            build_runner, "_active_unlocked", return_value=None
        ):
            r = self.client.post(
                "/api/build/runs/demo-run/build",
                json={"animation": "pan-h", "dry_run": True, "subtitles": True},
            )
        self.assertEqual(r.status_code, 200, r.text)
        argv = start_mock.call_args.args[1]
        self.assertIn("--animation", argv)
        self.assertIn("pan-h", argv)
        self.assertIn("--dry-run", argv)
        self.assertIn("--subtitles", argv)

    def test_start_logo_cleanup_flags(self) -> None:
        with self._fake_start({"id": "job-logo"}) as start_mock, mock.patch.object(
            build_runner, "_active_unlocked", return_value=None
        ):
            r = self.client.post(
                "/api/build/runs/demo-run/build",
                json={"logo_cleanup": True, "logo_mode": "blur"},
            )
        self.assertEqual(r.status_code, 200)
        argv = start_mock.call_args.args[1]
        self.assertIn("--logo-cleanup", argv)
        self.assertIn("--logo-mode", argv)
        self.assertIn("blur", argv)


class TestBuildJobs(BuildApiTestCase):
    def _write_job_log(self, job_id: str, lines: list[str], exit_code: int | None = None) -> Path:
        log_dir = self.root / "logs" / "api-build"
        log_dir.mkdir(parents=True, exist_ok=True)
        log = log_dir / ("%s.log" % job_id)
        text = "=== start t kind=build job=%s ===\n" % job_id + "\n".join(lines) + "\n"
        if exit_code is not None:
            text += "=== exit code %d ===\n" % exit_code
        log.write_text(text, encoding="utf-8")
        return log

    def test_job_status_404(self) -> None:
        r = self.client.get("/api/build/jobs/nope")
        self.assertEqual(r.status_code, 404)

    def test_job_status_disk_complete(self) -> None:
        self._write_job_log("job-ok", ["line1"], exit_code=0)
        r = self.client.get("/api/build/jobs/job-ok")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "complete")
        self.assertEqual(body["exit_code"], 0)

    def test_job_status_disk_failed(self) -> None:
        self._write_job_log("job-fail", ["boom"], exit_code=1)
        r = self.client.get("/api/build/jobs/job-fail")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "failed")

    def test_job_log_paging(self) -> None:
        # Log có dòng header `=== start … ===`; offset = số dòng bỏ qua.
        self._write_job_log("job-log", ["l%d" % i for i in range(5)])
        r = self.client.get("/api/build/jobs/job-log/log", params={"offset": 1, "limit": 2})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["lines"], ["l0", "l1"])
        self.assertEqual(body["next_offset"], 3)
        r = self.client.get("/api/build/jobs/job-log/log", params={"download": 1})
        self.assertEqual(r.status_code, 200)
        self.assertIn("attachment", r.headers["content-disposition"])

    def test_job_log_missing(self) -> None:
        r = self.client.get("/api/build/jobs/nope/log")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["log_exists"])
        r = self.client.get("/api/build/jobs/nope/log", params={"download": 1})
        self.assertEqual(r.status_code, 404)

    def test_cancel(self) -> None:
        r = self.client.post("/api/build/jobs/nope/cancel", json={})
        self.assertEqual(r.status_code, 404)
        with mock.patch.object(build_runner, "cancel", return_value=True):
            r = self.client.post("/api/build/jobs/xyz/cancel", json={})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["cancelled"])

    def test_build_command_builder(self) -> None:
        from youtube_pipeline.api.build_runner import build_job_command

        argv = build_job_command(Path("/abs/runs/r1"), {"render": True, "motion": True})
        self.assertNotIn("--prepare-only", argv)
        self.assertNotIn("--no-motion", argv)
        argv = build_job_command(Path("/abs/runs/r1"), {"render": False})
        self.assertIn("--prepare-only", argv)
        argv = build_job_command(Path("/abs/runs/r1"), {"resolution": [1920, 1080]})
        self.assertIn("1920x1080", argv)
        argv = build_job_command(
            Path("/abs/runs/r1"),
            {"animation": "zoom-out", "dry_run": True, "subtitles": True},
        )
        self.assertIn("--animation", argv)
        self.assertIn("zoom-out", argv)
        self.assertIn("--dry-run", argv)
        self.assertIn("--subtitles", argv)
        argv = build_job_command(Path("/abs/runs/r1"), {"animation": None})
        self.assertNotIn("--animation", argv)


class TestSubStyle(BuildApiTestCase):
    """Style phụ đề: GET defaults / PUT validate + ghi video-build/sub-style.json."""

    def test_get_defaults_when_missing(self) -> None:
        r = self.client.get("/api/build/runs/demo-run/sub-style")
        self.assertEqual(r.status_code, 200)
        style = r.json()["style"]
        self.assertEqual(style["font"], "Hiragino Kaku Gothic Pro")
        self.assertEqual(style["fontsize"], 44)
        self.assertEqual(style["color"], "#FFFFFF")
        self.assertEqual(style["outline"], 3)
        self.assertEqual(style["position"], "bottom")

    def test_put_and_get_roundtrip(self) -> None:
        body = {
            "font": "Hiragino Mincho ProN", "fontsize": 56, "color": "#FFD700",
            "outline": 5, "outline_color": "#111111", "shadow": 2,
            "bold": True, "position": "top", "margin_v": 48,
        }
        r = self.client.put("/api/build/runs/demo-run/sub-style", json=body)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["saved"])
        path = self.root / "runs/demo-run/video-build/sub-style.json"
        self.assertTrue(path.is_file())
        saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(saved["fontsize"], 56)
        self.assertEqual(saved["bold"], True)
        r = self.client.get("/api/build/runs/demo-run/sub-style")
        self.assertEqual(r.json()["style"]["fontsize"], 56)
        self.assertEqual(r.json()["style"]["position"], "top")

    def test_put_validation(self) -> None:
        for bad in (
            {"fontsize": 500}, {"fontsize": "big"}, {"fontsize": 10},
            {"color": "red"}, {"color": "#GGGGGG"}, {"outline": 9}, {"outline": -1},
            {"shadow": 7}, {"bold": "yes"}, {"position": "left"},
            {"font": "Arial"}, {"margin_v": -5},
        ):
            r = self.client.put("/api/build/runs/demo-run/sub-style", json=bad)
            self.assertEqual(r.status_code, 400, bad)

    def test_corrupt_file_falls_back_to_defaults(self) -> None:
        path = self.root / "runs/demo-run/video-build/sub-style.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{broken", encoding="utf-8")
        r = self.client.get("/api/build/runs/demo-run/sub-style")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["style"]["fontsize"], 44)


class TestImportImages(BuildApiTestCase):
    """Import ảnh đã gen — chạy đúng mode --import-images của build-video.py."""

    IMAGE_COUNT = 42

    def setUp(self) -> None:
        from youtube_pipeline.video import service as _service
        self._order_patcher = mock.patch.object(
            _service,
            "_img_order_for_import",
            return_value=["IMG-%02d" % index for index in range(1, self.IMAGE_COUNT + 1)],
        )
        self._order_patcher.start()

    def tearDown(self) -> None:
        self._order_patcher.stop()

    @staticmethod
    def _fake_pack(root: Path) -> Path:
        """video-build/prompts-build.py giả: 42 IMG theo thứ tự beat."""
        build_dir = root / "runs/demo-run/video-build"
        build_dir.mkdir(parents=True, exist_ok=True)
        rows = [
            '    ("IMG-%02d","B%02d","0:00-0:05",%d),' % (index, index, index)
            for index in range(1, 43)
        ]
        (build_dir / "prompts-build.py").write_text(
            "BEATS = [\n" + "\n".join(rows) + "\n]\n",
            encoding="utf-8",
        )
        return build_dir

    def _images(self, dirname: str, names: list[str], *, fill: bool = True) -> Path:
        """Thư mục ảnh nguồn — mtime tăng dần = thứ tự names."""
        source = self.root / dirname
        source.mkdir(parents=True, exist_ok=True)
        names = list(names)
        if fill:
            names.extend(
                "extra-%02d.jpg" % index
                for index in range(len(names) + 1, self.IMAGE_COUNT + 1)
            )
        for index, name in enumerate(names):
            path = source / name
            path.write_bytes(b"fake")
            os.utime(path, (1_600_000_000 + index, 1_600_000_000 + index))
        return source

    @staticmethod
    def _source_names(source: Path) -> list[str]:
        return [
            path.name
            for path in sorted(source.iterdir(), key=lambda item: item.stat().st_mtime)
            if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
        ]

    def _manifest(self, source: Path, overrides: dict[int, str] | None = None,
                  omit: set[str] | None = None) -> str:
        overrides = overrides or {}
        omit = omit or set()
        lines = []
        for index, filename in enumerate(self._source_names(source), 1):
            if filename in omit:
                continue
            filename = overrides.get(index, filename)
            lines.append("IMG-%02d | %s | scene %02d" % (index, filename, index))
        return "\n".join(lines) + "\n"

    def _clean_images(self, build_dir: Path) -> None:
        images_dir = build_dir / "images"
        if images_dir.is_dir():
            for p in images_dir.glob("IMG-*"):
                p.unlink()

    def test_preview_shows_mapping_without_moving(self) -> None:
        build_dir = self._fake_pack(self.root)
        self._clean_images(build_dir)  # test_apply_moves chạy trước (alphabet)
        source = self._images("gen-preview", ["a.jpg", "b.jpg", "c.jpg"])
        r = self.client.post(
            "/api/build/runs/demo-run/import-images",
            json={"source_dir": str(source), "apply": False},
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertTrue(body["ok"])
        self.assertEqual([m["img"] for m in body["mapping"]][:3],
                         ["IMG-01", "IMG-02", "IMG-03"])
        self.assertEqual([m["file"] for m in body["mapping"]][:3],
                         ["a.jpg", "b.jpg", "c.jpg"])
        self.assertEqual(len(body["mapping"]), self.IMAGE_COUNT)
        self.assertFalse(body["apply"])
        # Xem trước — không move, không đổi tên ảnh (manifest khung được ghi thêm).
        source_names = sorted(p.name for p in source.glob("*.jpg"))
        self.assertEqual(source_names[:3], ["a.jpg", "b.jpg", "c.jpg"])
        self.assertEqual(len(source_names), self.IMAGE_COUNT)
        self.assertFalse(list((build_dir / "images").glob("IMG-*")))

    def test_apply_moves_renamed_files_into_images(self) -> None:
        build_dir = self._fake_pack(self.root)
        self._clean_images(build_dir)
        source = self._images("gen-apply", ["a.jpg", "b.jpg", "c.jpg"])
        r = self.client.post(
            "/api/build/runs/demo-run/import-images",
            json={"source_dir": str(source), "apply": True},
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["apply"])
        self.assertEqual(len(body["mapping"]), self.IMAGE_COUNT)
        images = sorted(p.name for p in (build_dir / "images").glob("IMG-*"))
        self.assertEqual(len(images), self.IMAGE_COUNT)
        self.assertEqual(images[:3], ["IMG-01.jpg", "IMG-02.jpg", "IMG-03.jpg"])
        self.assertEqual(list(source.iterdir()), [])  # đã move hết

    def test_insert_assigns_specific_image(self) -> None:
        build_dir = self._fake_pack(self.root)
        self._clean_images(build_dir)
        source = self._images("gen-insert", ["a.jpg", "b.jpg", "c.jpg"])
        r = self.client.post(
            "/api/build/runs/demo-run/import-images",
            json={"source_dir": str(source), "insert": "IMG-02:b.jpg", "apply": True},
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertTrue(body["ok"])
        by_img = {m["img"]: m["file"] for m in body["mapping"]}
        self.assertEqual(by_img["IMG-01"], "a.jpg")
        self.assertEqual(by_img["IMG-02"], "b.jpg")
        self.assertEqual(by_img["IMG-03"], "c.jpg")
        self.assertTrue((build_dir / "images/IMG-02.jpg").is_file())

    def test_missing_images_fails_with_error(self) -> None:
        self._fake_pack(self.root)
        source = self._images("gen-missing", ["a.jpg", "b.jpg"], fill=False)  # cần 42
        r = self.client.post(
            "/api/build/runs/demo-run/import-images",
            json={"source_dir": str(source), "apply": True},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body["ok"])
        self.assertIn("Thieu anh", body["error"])

    def test_apply_refuses_when_images_dir_has_files(self) -> None:
        build_dir = self._fake_pack(self.root)
        (build_dir / "images").mkdir(exist_ok=True)
        (build_dir / "images" / "IMG-01.jpg").write_bytes(b"old")
        source = self._images("gen-existing", ["a.jpg", "b.jpg", "c.jpg"])
        r = self.client.post(
            "/api/build/runs/demo-run/import-images",
            json={"source_dir": str(source), "apply": True},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body["ok"])
        self.assertIn("da co", body["error"])

    def test_manifest_overrides_file_order(self) -> None:
        """IMPORT_MANIFEST.txt trong source_dir quyết định mapping, không phải mtime."""
        build_dir = self._fake_pack(self.root)
        self._clean_images(build_dir)
        source = self._images("gen-manifest", ["a.jpg", "b.jpg", "c.jpg"])
        # Mapping đảo: a->IMG-03, b->IMG-01, c->IMG-02.
        (source / "IMPORT_MANIFEST.txt").write_text(
            self._manifest(source, {1: "b.jpg", 2: "c.jpg", 3: "a.jpg"}),
            encoding="utf-8",
        )
        r = self.client.post(
            "/api/build/runs/demo-run/import-images",
            json={"source_dir": str(source), "apply": True},
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertTrue(body["ok"], body)
        self.assertEqual(body.get("source"), "manifest")
        by_img = {m["img"]: m["file"] for m in body["mapping"]}
        self.assertEqual(by_img["IMG-01"], "b.jpg")
        self.assertEqual(by_img["IMG-02"], "c.jpg")
        self.assertEqual(by_img["IMG-03"], "a.jpg")

    def test_manifest_warns_on_file_not_listed(self) -> None:
        build_dir = self._fake_pack(self.root)
        self._clean_images(build_dir)
        source = self._images("gen-manifest-warn", ["a.jpg", "b.jpg", "c.jpg"])
        (source / "IMPORT_MANIFEST.txt").write_text(
            self._manifest(source, omit={"c.jpg"}), encoding="utf-8"
        )
        r = self.client.post(
            "/api/build/runs/demo-run/import-images",
            json={"source_dir": str(source), "apply": False},
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertTrue(any("c.jpg" in w for w in body.get("warnings", [])), body)

    def test_preview_writes_manifest_skeleton(self) -> None:
        """Chưa có manifest + apply=false -> ghi khung IMPORT_MANIFEST.txt."""
        build_dir = self._fake_pack(self.root)
        self._clean_images(build_dir)
        source = self._images("gen-skeleton", ["a.jpg", "b.jpg", "c.jpg"])
        r = self.client.post(
            "/api/build/runs/demo-run/import-images",
            json={"source_dir": str(source), "apply": False},
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertTrue(body["ok"], body)
        self.assertEqual(body["source"], "auto")
        self.assertEqual(body.get("manifest_written"), "IMPORT_MANIFEST.txt")
        manifest = source / "IMPORT_MANIFEST.txt"
        self.assertTrue(manifest.is_file())
        # Khung phải parse lại được và phủ đủ 42 ảnh.
        from youtube_pipeline.video.service import _read_manifest

        order, warns = _read_manifest(source)
        self.assertEqual(len(order), self.IMAGE_COUNT)
        self.assertEqual(order[:3], ["IMG-01", "IMG-02", "IMG-03"])
        self.assertEqual(warns, [])

    def test_preview_does_not_overwrite_edited_manifest(self) -> None:
        """Manifest user đã sửa là nguồn sự thật — preview không ghi đè."""
        build_dir = self._fake_pack(self.root)
        self._clean_images(build_dir)
        source = self._images("gen-nooverwrite", ["a.jpg", "b.jpg", "c.jpg"])
        edited = self._manifest(source, {1: "c.jpg", 2: "a.jpg", 3: "b.jpg"})
        (source / "IMPORT_MANIFEST.txt").write_text(edited, encoding="utf-8")
        r = self.client.post(
            "/api/build/runs/demo-run/import-images",
            json={"source_dir": str(source), "apply": False},
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["source"], "manifest")
        self.assertNotIn("manifest_written", body)
        self.assertEqual((source / "IMPORT_MANIFEST.txt").read_text(encoding="utf-8"), edited)
        by_img = {m["img"]: m["file"] for m in body["mapping"]}
        self.assertEqual(by_img["IMG-01"], "c.jpg")

    def test_apply_does_not_write_manifest(self) -> None:
        """apply=true: ảnh đã move nên không ghi manifest."""
        build_dir = self._fake_pack(self.root)
        self._clean_images(build_dir)
        source = self._images("gen-applynomanifest", ["a.jpg", "b.jpg", "c.jpg"])
        r = self.client.post(
            "/api/build/runs/demo-run/import-images",
            json={"source_dir": str(source), "apply": True},
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["ok"])
        self.assertNotIn("manifest_written", r.json())
        self.assertFalse((source / "IMPORT_MANIFEST.txt").exists())

    def test_busy_409(self) -> None:
        with mock.patch.object(build_runner, "busy", return_value=True):
            r = self.client.post(
                "/api/build/runs/demo-run/import-images", json={"source_dir": "/tmp"}
            )
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["detail"]["key"], "busy")

    def test_validation_400(self) -> None:
        r = self.client.post("/api/build/runs/demo-run/import-images", json={})
        self.assertEqual(r.status_code, 400)
        r = self.client.post(
            "/api/build/runs/demo-run/import-images", json={"source_dir": 5}
        )
        self.assertEqual(r.status_code, 400)
        r = self.client.post(
            "/api/build/runs/demo-run/import-images",
            json={"source_dir": "/tmp", "insert": "IMG-01"},
        )
        self.assertEqual(r.status_code, 400)
        r = self.client.post(
            "/api/build/runs/demo-run/import-images",
            json={"source_dir": "/tmp", "apply": "yes"},
        )
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
