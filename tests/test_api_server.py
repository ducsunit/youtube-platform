"""Test API server — mọi test dùng TemporaryDirectory làm backend root
(patch youtube_pipeline.api.paths._BACKEND_ROOT) để không đụng repo thật.
Test E2E demo thật gated sau YT_API_INTEGRATION=1.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from youtube_pipeline.api import app
from youtube_pipeline.api import paths
from youtube_pipeline.api.runner import (
    build_new_run_command,
    build_resume_command,
    runner as app_r,
)

STAGE_NAMES = [
    "ingest", "performance", "topic_research", "topic_candidates", "topic_selection",
    "source_lock", "claim_ledger", "narrative_brief", "writing", "script_audit",
    "script_qa", "structure_check", "psychology_format_check", "translate_script_vi", "sections", "thumbnail_contract", "image_strategy", "image_prompts",
    "publish_draft", "resource_pack",
]


def _make_state(
    run_id: str,
    status: str = "complete",
    stage_statuses=None,
    topic: str = "テストの題材",
    updated_at: str = "2026-08-09T01:00:00+00:00",
    artifact_refs: dict | None = None,
) -> dict:
    stage_statuses = stage_statuses or {}
    records = {}
    for idx, (name, st) in enumerate(stage_statuses.items()):
        records[name] = {
            "stage_name": name,
            "stage_version": "1",
            "status": st,
            "attempts": 1,
            "input_fingerprint": "fp-%d" % idx,
            "started_at": None,
            "finished_at": None,
            "artifacts": [],
            "metrics": {},
            "warnings": [],
            "error": None,
        }
    return {
        "schema_version": 2,
        "run_id": run_id,
        "profile": "resource_pack",
        "topic": topic,
        "status": status,
        "created_at": "2026-08-09T00:00:00+00:00",
        "updated_at": updated_at,
        "config_snapshot": {
            "minimax_tts_profile": {"speed": 1.02, "pitch": -1, "volume": 1.02},
            "target_duration_minutes": [6, 12],
            "target_chars": [2300, 6000],
        },
        "input_artifacts": {"channel_input": "abc"},
        "stage_records": records,
        "artifact_index": artifact_refs or {},
        "warnings": [],
        "errors": [],
    }


def _write_state(root: Path, run_id: str, **kw) -> None:
    run_dir = root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_state.json").write_text(
        json.dumps(_make_state(run_id, **kw), ensure_ascii=False), encoding="utf-8"
    )


def _write_file(root: Path, run_id: str, rel: str, content) -> None:
    f = root / "runs" / run_id / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, (dict, list)):
        content = json.dumps(content, ensure_ascii=False, indent=2)
    f.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))


class ApiServerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.patcher = mock.patch.object(paths, "_BACKEND_ROOT", self.root)
        self.patcher.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.patcher.stop()
        self._tmp.cleanup()


class TestSystem(ApiServerTestCase):
    def test_health(self) -> None:
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        # backend_root() trả nguyên _BACKEND_ROOT (không resolve) — so với str(self.root)
        self.assertEqual(body["backend_root"], str(self.root))

    def test_config(self) -> None:
        (self.root / "data/channels").mkdir(parents=True)
        (self.root / "data/channels/youtube_data.json").write_text(
            json.dumps({"schema_version": 2, "videos": {}}), encoding="utf-8"
        )
        r = self.client.get("/api/config")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["stage_order"], STAGE_NAMES)
        self.assertTrue(body["minimax_profile"]["reference_cpm_min"] == 380)
        names = [f["name"] for f in body["input_files"]]
        self.assertIn("data/channels/youtube_data.json", names)
        self.assertIsNone(body["active_run"])
        self.assertFalse(body["busy"])

    def test_cors_header(self) -> None:
        r = self.client.get("/api/health", headers={"Origin": "http://localhost:5173"})
        self.assertIn("access-control-allow-origin", r.headers)

    def test_platform_reindex_rebuilds_sqlite_from_run_state(self) -> None:
        _write_state(self.root, "completed-run", status="complete", stage_statuses={"ingest": "passed"})
        _write_file(self.root, "completed-run", "research/topic-selection.json", {"selected_topic": "旧テーマ"})
        _write_file(self.root, "completed-run", "script/contract.json", {"chosen_title": "旧タイトル"})
        r = self.client.post("/api/platform/reindex")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["indexed"], 1)
        database = sqlite3.connect(self.root / "runtime/platform.sqlite3")
        self.assertEqual(database.execute("SELECT run_id FROM runs").fetchone()[0], "completed-run")
        self.assertEqual(database.execute("SELECT topic FROM topic_history").fetchone()[0], "旧テーマ")


class TestRuns(ApiServerTestCase):
    def test_list_runs_empty(self) -> None:
        r = self.client.get("/api/runs")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"runs": []})

    def test_list_runs_summary_and_sort(self) -> None:
        _write_state(
            self.root, "run-a",
            stage_statuses={name: "passed" for name in STAGE_NAMES},
            updated_at="2026-08-09T01:00:00+00:00",
        )
        _write_state(
            self.root, "run-b",
            stage_statuses={"ingest": "failed"},
            status="failed",
            updated_at="2026-08-09T02:00:00+00:00",
        )
        (self.root / "runs" / "run-a" / "resource_manifest.json").write_text(
            json.dumps({"timeline_status": "DRAFT_TIMING"}), encoding="utf-8"
        )
        # Dir không có run_state.json + .DS_Store bị bỏ qua
        (self.root / "runs" / "no-state").mkdir()
        _write_file(self.root, "run-b", ".DS_Store", "")
        r = self.client.get("/api/runs")
        self.assertEqual(r.status_code, 200)
        runs = r.json()["runs"]
        self.assertEqual([x["run_id"] for x in runs], ["run-b", "run-a"])
        a = runs[1]
        self.assertEqual(a["stage_counts"]["total"], len(STAGE_NAMES))
        self.assertEqual(a["stage_counts"]["passed"], len(STAGE_NAMES))
        self.assertTrue(a["has_manifest"])
        self.assertEqual(a["timeline_status"], "DRAFT_TIMING")
        b = runs[0]
        self.assertEqual(b["status"], "failed")
        self.assertEqual(b["stage_counts"], {"total": 1, "passed": 0, "failed": 1, "pending": 0, "running": 0})

    def test_run_detail_and_404(self) -> None:
        _write_state(self.root, "run-a", stage_statuses={"ingest": "passed"})
        r = self.client.get("/api/runs/run-a")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["run_id"], "run-a")
        self.assertEqual(body["state"]["status"], "complete")
        self.assertIsNone(body["manifest"])
        r = self.client.get("/api/runs/nope")
        self.assertEqual(r.status_code, 404)
        # %2F có thể 404 (route không match) hoặc 400 (regex) — cả hai đều chặn được
        r = self.client.get("/api/runs/bad%2Fid")
        self.assertIn(r.status_code, (400, 404))

    def test_run_diagnostics_falls_back_to_state_without_creating_db(self) -> None:
        _write_state(self.root, "run-a", stage_statuses={"ingest": "passed"})
        r = self.client.get("/api/runs/run-a/diagnostics")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["source"], "run_state")
        self.assertFalse(body["indexed"])
        self.assertFalse((self.root / "runtime" / "platform.sqlite3").exists())

    def test_run_diagnostics_reads_sqlite_metadata_without_model_content(self) -> None:
        from youtube_pipeline.core.artifacts import ArtifactStore
        from youtube_pipeline.core.state import RunState
        from youtube_pipeline.infrastructure.model_trace import start_run, trace_parsed_response, trace_request

        root = self.root / "runs" / "indexed-run"
        store = ArtifactStore(root)
        store.save_state(RunState(
            run_id="indexed-run", profile="resource_pack", topic="",
            config_snapshot={"model_routing": {"profiles": {"writer": {"model": "frozen-model"}}}},
        ))
        start_run("indexed-run", {"output_dir": str(root)})
        trace_request("RP_TEST", "test", "openai_compatible", "frozen-model", "private system", "private prompt", 0.2)
        trace_parsed_response("RP_TEST", "test", {"private": "response"})

        r = self.client.get("/api/runs/indexed-run/diagnostics")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["source"], "sqlite")
        self.assertEqual(body["routing_snapshot"]["profiles"]["writer"]["model"], "frozen-model")
        self.assertEqual(body["model_calls"]["calls"][0]["label"], "RP_TEST")
        self.assertNotIn("private prompt", json.dumps(body))

    def test_run_status_active_stage(self) -> None:
        _write_state(
            self.root, "run-a",
            status="running",
            stage_statuses={"ingest": "passed", "performance": "running", "topic_research": "pending"},
        )
        r = self.client.get("/api/runs/run-a/status")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "running")
        self.assertEqual(body["active_stage"], {"index": 1, "name": "performance", "status": "running"})
        self.assertEqual(body["stage_counts"], {"total": 3, "passed": 1, "failed": 0, "pending": 1, "running": 1})
        self.assertFalse(body["finished"])


class TestArtifacts(ApiServerTestCase):
    def _setup_run(self, run_id: str = "run-a") -> None:
        _write_state(self.root, run_id, stage_statuses={"ingest": "passed"})

    def test_artifact_json_pretty(self) -> None:
        self._setup_run()
        _write_file(self.root, "run-a", "script/review-report.json", {"a": 1, "nested": {"b": [1, 2]}})
        r = self.client.get("/api/runs/run-a/artifact", params={"path": "script/review-report.json"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("application/json", r.headers["content-type"])
        self.assertEqual(json.loads(r.content), {"a": 1, "nested": {"b": [1, 2]}})
        self.assertIn(b"\n  \"a\"", r.content)

    def test_artifact_text_and_download(self) -> None:
        self._setup_run()
        _write_file(self.root, "run-a", "script/script.txt", "こんにちは\n二行目")
        r = self.client.get("/api/runs/run-a/artifact", params={"path": "script/script.txt"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/plain", r.headers["content-type"])
        self.assertIn("inline", r.headers["content-disposition"])
        self.assertIn("こんにちは", r.text)
        r = self.client.get("/api/runs/run-a/artifact", params={"path": "script/script.txt", "download": 1})
        self.assertIn("attachment", r.headers["content-disposition"])

    def test_artifact_traversal_blocked(self) -> None:
        self._setup_run()
        for bad in ("../.env", "/etc/passwd", "a/../../x"):
            r = self.client.get("/api/runs/run-a/artifact", params={"path": bad})
            self.assertIn(r.status_code, (400, 404), bad)
        # Percent-encoded .. cũng bị chặn (decode -> .. hoặc resolve lạc -> 404)
        r = self.client.get("/api/runs/run-a/artifact", params={"path": "%2E%2E%2F.env"})
        self.assertIn(r.status_code, (400, 404))
        r = self.client.get("/api/runs/run-a/artifact", params={"path": ""})
        self.assertEqual(r.status_code, 400)

    def test_artifact_symlink_escape_blocked(self) -> None:
        self._setup_run()
        outside = self.root / "secret.txt"
        outside.write_text("secret", encoding="utf-8")
        link = self.root / "runs" / "run-a" / "escape.txt"
        link.symlink_to(outside)
        r = self.client.get("/api/runs/run-a/artifact", params={"path": "escape.txt"})
        self.assertEqual(r.status_code, 404)

    def test_artifact_404(self) -> None:
        self._setup_run()
        r = self.client.get("/api/runs/run-a/artifact", params={"path": "script/missing.txt"})
        self.assertEqual(r.status_code, 404)
        r = self.client.get("/api/runs/ghost/artifact", params={"path": "script/script.txt"})
        self.assertEqual(r.status_code, 404)

    def test_artifacts_tree(self) -> None:
        self._setup_run()
        _write_file(self.root, "run-a", "script/script.txt", "x")
        _write_file(self.root, "run-a", "research/topic-candidates.json", "{}")
        _write_file(self.root, "run-a", "input/youtube_data.json", "{}")
        _write_file(self.root, "run-a", "resource_manifest.json", "{}")
        r = self.client.get("/api/runs/run-a/artifacts")
        self.assertEqual(r.status_code, 200)
        tree = r.json()["tree"]
        self.assertIn("script", tree)
        self.assertIn("script.txt", tree["script"])
        self.assertIn("research", tree)
        self.assertIn("input", tree)
        self.assertIn("", tree)  # file gốc
        self.assertIn("resource_manifest.json", tree[""])
        self.assertNotIn("run_state.json", tree[""])


class TestLog(ApiServerTestCase):
    def test_log_tail(self) -> None:
        log_dir = self.root / "logs" / "api-runs"
        log_dir.mkdir(parents=True)
        (log_dir / "run-a.log").write_text("\n".join("line%d" % i for i in range(5)) + "\n", encoding="utf-8")
        r = self.client.get("/api/runs/run-a/log", params={"offset": 2, "limit": 2})
        body = r.json()
        self.assertEqual(body["lines"], ["line2", "line3"])
        self.assertEqual(body["next_offset"], 4)
        self.assertFalse(body["eof"])
        self.assertTrue(body["log_exists"])
        r = self.client.get("/api/runs/run-a/log", params={"offset": 4, "limit": 10})
        body = r.json()
        self.assertEqual(body["lines"], ["line4"])
        self.assertTrue(body["eof"])
        r = self.client.get("/api/runs/run-a/log", params={"offset": 0, "limit": 2, "download": 1})
        self.assertEqual(r.status_code, 200)
        self.assertIn("attachment", r.headers["content-disposition"])
        self.assertIn(b"line0", r.content)

    def test_log_missing(self) -> None:
        r = self.client.get("/api/runs/ghost/log")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body["log_exists"])
        self.assertEqual(body["lines"], [])
        r = self.client.get("/api/runs/ghost/log", params={"download": 1})
        self.assertEqual(r.status_code, 404)


class TestStartResumeCancel(ApiServerTestCase):
    def test_start_run_busy_409(self) -> None:
        fake_proc = mock.Mock()
        fake_proc.poll.return_value = None
        with mock.patch.object(app_r, "_proc", fake_proc), mock.patch.object(app_r, "_run_id", "busy-run"):
            r = self.client.post("/api/runs", json={"mode": "demo", "run_id": "other"})
        self.assertEqual(r.status_code, 409)
        detail = r.json()["detail"]
        self.assertEqual(detail["key"], "busy")
        self.assertEqual(detail["active_run_id"], "busy-run")

    def test_start_run_validation(self) -> None:
        r = self.client.post("/api/runs", json={"mode": "hack"})
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/runs", json={"mode": "production"})
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/runs", json={"mode": "production", "input_file": "no-such.json"})
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/runs", json={"mode": "demo", "run_id": "bad/run"})
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/runs", json={"mode": "demo", "run_id": "x", "output_dir": "../evil"})
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/runs", json={"mode": "demo", "run_id": "x", "output_dir": "runs/not-x"})
        self.assertEqual(r.status_code, 400)
        outside = self.root.parent / "outside-input.json"
        outside.write_text("{}", encoding="utf-8")
        r = self.client.post("/api/runs", json={"mode": "production", "run_id": "x", "input_file": "../outside-input.json"})
        self.assertEqual(r.status_code, 400)

    def test_start_run_existing_run_id_400(self) -> None:
        _write_state(self.root, "run-a")
        r = self.client.post("/api/runs", json={"mode": "demo", "run_id": "run-a"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("đã tồn tại", r.json()["detail"])

    def test_resume_404_and_running_400(self) -> None:
        r = self.client.post("/api/runs/ghost/resume", json={})
        self.assertEqual(r.status_code, 404)
        _write_state(self.root, "run-a", status="running")
        r = self.client.post("/api/runs/run-a/resume", json={})
        self.assertEqual(r.status_code, 400)

    def test_cancel(self) -> None:
        r = self.client.post("/api/runs/ghost/cancel", json={})
        self.assertEqual(r.status_code, 404)
        fake_proc = mock.Mock()
        fake_proc.poll.return_value = None
        fake_proc.pid = 999999999  # pid chắc chắn không tồn tại -> ProcessLookupError -> coi như đã signal
        with mock.patch.object(app_r, "_proc", fake_proc), mock.patch.object(app_r, "_run_id", "run-a"):
            r = self.client.post("/api/runs/run-a/cancel", json={})
        self.assertEqual(r.status_code, 202)
        self.assertTrue(r.json()["cancelled"])

    def test_command_builders(self) -> None:
        demo = build_new_run_command("r1", Path("/abs/runs/r1"), "demo")
        self.assertIn("--demo", demo)
        self.assertNotIn("--input-file", demo)
        prod = build_new_run_command("r2", Path("/abs/runs/r2"), "production", Path("/abs/input.json"))
        self.assertIn("--input-file", prod)
        self.assertIn("/abs/input.json", prod)
        self.assertNotIn("--demo", prod)
        manual = build_new_run_command("r-manual", Path("/abs/runs/r-manual"), "production", manual_topic="休めない理由")
        self.assertIn("--manual-topic", manual)
        self.assertIn("休めない理由", manual)
        self.assertNotIn("--input-file", manual)
        competitor = build_new_run_command("r-competitor", Path("/abs/runs/r-competitor"), "production", no_channel_data=True)
        self.assertIn("--no-channel-data", competitor)
        self.assertNotIn("--input-file", competitor)
        resume = build_resume_command("r3", Path("/abs/runs/r3"))
        self.assertIn("--resume", resume)
        self.assertIn("/abs/runs/r3/run_state.json", resume)
        self.assertIn("/abs/runs/r3", resume)  # --output-dir

    def test_start_manual_topic_run_without_dataset(self) -> None:
        with mock.patch("youtube_pipeline.api.routes.runner.start_new", return_value=self.root / "logs" / "manual.log") as start:
            response = self.client.post(
                "/api/runs",
                json={
                    "mode": "production",
                    "channel_data_mode": "none",
                    "manual_topic": "休むほど落ち着かなくなる理由",
                    "run_id": "manual-topic",
                },
            )
        self.assertEqual(response.status_code, 202, response.text)
        self.assertIsNone(start.call_args.args[3])
        self.assertEqual(start.call_args.args[4], "休むほど落ち着かなくなる理由")

    def test_start_competitor_topic_run_without_dataset(self) -> None:
        with mock.patch("youtube_pipeline.api.routes.runner.start_new", return_value=self.root / "logs" / "competitor.log") as start:
            response = self.client.post(
                "/api/runs",
                json={"mode": "production", "channel_data_mode": "none", "run_id": "competitor-topic"},
            )
        self.assertEqual(response.status_code, 202, response.text)
        self.assertIsNone(start.call_args.args[3])
        self.assertIsNone(start.call_args.args[4])
        self.assertTrue(start.call_args.args[5])

    def test_none_string_is_not_a_manual_topic(self) -> None:
        with mock.patch("youtube_pipeline.api.routes.runner.start_new", return_value=self.root / "logs" / "competitor.log") as start:
            response = self.client.post(
                "/api/runs",
                json={"mode": "production", "channel_data_mode": "none", "manual_topic": "None", "run_id": "competitor-sentinel"},
            )
        self.assertEqual(response.status_code, 202, response.text)
        self.assertIsNone(start.call_args.args[4])
        self.assertTrue(start.call_args.args[5])


@unittest.skipUnless(os.environ.get("YT_API_INTEGRATION") == "1", "YT_API_INTEGRATION=1 để chạy demo E2E thật")
class TestIntegration(ApiServerTestCase):
    def test_demo_run_end_to_end(self) -> None:
        """Spawn CLI demo thật qua API, poll tới complete, đọc artifact."""
        import time

        r = self.client.post("/api/runs", json={"mode": "demo", "run_id": "it-demo"})
        self.assertEqual(r.status_code, 202, r.text)
        run_id = r.json()["run_id"]
        deadline = 180
        body = None
        while deadline > 0:
            resp = self.client.get("/api/runs/%s/status" % run_id)
            # run_state.json chưa kịp ghi -> 404 — vẫn chờ
            if resp.status_code == 200:
                body = resp.json()
                if body.get("finished"):
                    break
            time.sleep(1)
            deadline -= 1
        self.assertIsNotNone(body, "Demo run không hoàn thành trong 180s")
        self.assertEqual(body["status"], "complete", body)
        r = self.client.get("/api/runs/%s/artifact" % run_id, params={"path": "script/script.txt"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(len(r.text) > 100)
        r = self.client.get("/api/runs/%s/artifact" % run_id, params={"path": "script/review-report.json"})
        self.assertEqual(r.status_code, 200)


class TestServeFrontend(unittest.TestCase):
    """YT_SERVE_FRONTEND: mount bản build tĩnh + SPA fallback cho deep-link."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dist = Path(self._tmp.name)
        (self.dist / "index.html").write_text(
            "<!doctype html><title>YT UI</title><div id=root></div>", encoding="utf-8"
        )
        os.environ["YT_SERVE_FRONTEND"] = str(self.dist)

    def tearDown(self) -> None:
        os.environ.pop("YT_SERVE_FRONTEND", None)
        self._tmp.cleanup()

    def test_spa_fallback(self) -> None:
        from youtube_pipeline.api import create_app

        client = TestClient(create_app())
        r = client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("YT UI", r.text)
        # Deep-link: refresh /runs/<id> phải trả index.html chứ không 404
        r = client.get("/runs/abc123")
        self.assertEqual(r.status_code, 200)
        self.assertIn("YT UI", r.text)
        # API vẫn ưu tiên (router đăng ký trước mount)
        r = client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")
