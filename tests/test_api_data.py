"""Test tính năng "Kéo data YouTube" (api/data/*) — dùng pull_dir giả.

Puller thật KHÔNG được chạy: stub `youtube_pull.py` (python thật, ghi
sys.argv + cwd vào invocations.jsonl để assert) + token.json giả. Mọi job
spawn bằng python thật (sys.executable) nên chạy nhanh, không cần mạng.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from youtube_pipeline.api import app, datapull, paths

# Stub puller: ghi lại argv/cwd, có get_credentials (cho connect), exit code và
# độ dài có thể điều khiển qua env để test busy/cancel/failed.
STUB = r'''
import json, os, sys, time

def _record():
    rec = {"argv": sys.argv, "cwd": os.getcwd()}
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "invocations.jsonl"),
              "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")

def get_credentials():
    _record()
    print("stub: credentials ok")

if __name__ == "__main__":
    _record()
    print("stub: running")
    sys.stdout.flush()
    code = int(os.environ.get("YT_STUB_EXIT", "0"))
    if code:
        sys.exit(code)
    time.sleep(float(os.environ.get("YT_STUB_SLEEP", "0")))
    sys.exit(0)
'''

TOKEN_OK = {
    "token": "t",
    "refresh_token": "r",
    "token_uri": "https://oauth2.googleapis.com/token",
    "client_id": "c",
    "client_secret": "s",
    "scopes": [
        "https://www.googleapis.com/auth/youtube.force-ssl",
        "https://www.googleapis.com/auth/yt-analytics.readonly",
    ],
    "expiry": "2026-12-31T00:00:00Z",
}


class DataApiTestCase(unittest.TestCase):
    """Fixture chung: backend root giả + pull_dir giả + stub puller + env."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.pull_dir = self.root / "puller"
        self.pull_dir.mkdir()
        (self.pull_dir / "youtube_pull.py").write_text(STUB, encoding="utf-8")

        self.root_patcher = mock.patch.object(paths, "_BACKEND_ROOT", self.root)
        self.root_patcher.start()
        # Không để FALLBACK_PULL_DIRS trỏ vào puller thật trên máy.
        self.dir_patcher = mock.patch.object(datapull, "FALLBACK_PULL_DIRS", ())
        self.dir_patcher.start()
        # Bỏ qua kiểm tra googleapiclient thật — test dùng python hiện tại.
        self.venv_patcher = mock.patch.object(datapull, "_venv_has_googleapiclient", return_value=True)
        self.venv_patcher.start()
        self.env_patcher = mock.patch.dict(
            os.environ,
            {"YT_DATA_PULL_DIR": str(self.pull_dir), "YT_DATA_PULL_PYTHON": sys.executable},
        )
        self.env_patcher.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        # Dọn mọi job còn chạy (cancel + chờ) trước khi xoá backend root giả.
        runner = datapull.data_runner
        deadline = time.monotonic() + 5
        while runner.busy() and time.monotonic() < deadline:
            active = runner.active_job()
            if active is not None:
                runner.cancel(active["id"])
            time.sleep(0.05)
        self.env_patcher.stop()
        self.venv_patcher.stop()
        self.dir_patcher.stop()
        self.root_patcher.stop()
        self._tmp.cleanup()

    # ------------------------------------------------------------- helpers

    def write_token(self, **over) -> None:
        data = dict(TOKEN_OK, **over)
        (self.pull_dir / "token.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )

    def write_result(self, name: str = "data/channels/youtube_data.json", videos: int = 3) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "generated_at": "2026-08-09T10:00:00+07:00",
                    "channel_id": "UCtest",
                    "analytics_window": {"start": "2026-07-01", "end": "2026-07-31"},
                    "videos": {"v%d" % i: {"videoId": "v%d" % i} for i in range(videos)},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def invocations(self) -> list[dict]:
        f = self.pull_dir / "invocations.jsonl"
        if not f.is_file():
            return []
        return [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line]

    def wait_job(self, job_id: str, timeout: float = 15.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            r = self.client.get("/api/data/jobs/%s" % job_id)
            if r.status_code == 200 and r.json()["status"] != "running":
                return r.json()
            time.sleep(0.05)
        self.fail("job %s không kết thúc trong %ss" % (job_id, timeout))


# ------------------------------------------------------------------- status


class TestStatus(DataApiTestCase):
    def test_status_missing_dir(self) -> None:
        with mock.patch.dict(os.environ, {}):
            os.environ.pop("YT_DATA_PULL_DIR", None)
            os.environ.pop("YT_DATA_PULL_PYTHON", None)
            r = self.client.get("/api/data/status")
        self.assertEqual(r.status_code, 200)
        b = r.json()
        self.assertFalse(b["available"])
        self.assertIsNone(b["pull_dir"])
        self.assertFalse(b["connected"])
        self.assertFalse(b["busy"])

    def test_status_connected_with_token(self) -> None:
        self.write_token()
        r = self.client.get("/api/data/status")
        self.assertEqual(r.status_code, 200)
        b = r.json()
        self.assertTrue(b["available"])
        self.assertEqual(b["pull_dir"], str(self.pull_dir))
        self.assertTrue(b["connected"])
        self.assertTrue(b["scopes_ok"])
        self.assertEqual(b["expires_at"], "2026-12-31T00:00:00Z")
        self.assertEqual(b["python"], sys.executable)

    def test_status_token_scopes_as_string(self) -> None:
        # Flow cũ có thể lưu scopes là chuỗi cách nhau dấu cách.
        self.write_token(scopes="https://www.googleapis.com/auth/youtube.force-ssl https://www.googleapis.com/auth/yt-analytics.readonly")
        b = self.client.get("/api/data/status").json()
        self.assertTrue(b["scopes_ok"])
        self.assertTrue(b["connected"])

    def test_status_not_connected_without_token(self) -> None:
        b = self.client.get("/api/data/status").json()
        self.assertTrue(b["available"])
        self.assertFalse(b["connected"])
        self.assertFalse(b["scopes_ok"])

    def test_status_last_result(self) -> None:
        self.write_token()
        self.write_result()
        b = self.client.get("/api/data/status").json()
        lr = b["last_result"]
        self.assertIsNotNone(lr)
        self.assertEqual(lr["file"], "data/channels/youtube_data.json")
        self.assertEqual(lr["channel_id"], "UCtest")
        self.assertEqual(lr["video_count"], 3)
        self.assertEqual(lr["analytics_window"]["end"], "2026-07-31")

    def test_status_datasets_and_token_are_channel_isolated(self) -> None:
        from youtube_pipeline.platform_db import PlatformDatabase

        db = PlatformDatabase(self.root / "runtime" / "platform.sqlite3")
        for channel_id in ("channel-a", "channel-b"):
            db.register_channel(user_id="dev-user", channel_id=channel_id, youtube_channel_id="UC-" + channel_id)
        for channel_id, marker in (("channel-a", "A"), ("channel-b", "B")):
            data_dir = self.root / "users" / "dev-user" / "channels" / channel_id / "data" / "snapshots"
            data_dir.mkdir(parents=True)
            (data_dir / "youtube_data.json").write_text(json.dumps({
                "schema_version": 2, "channel_id": marker,
                "generated_at": "2026-08-09T10:00:00+07:00",
                "videos": {"v": {"videoId": "v"}},
            }), encoding="utf-8")
            token_dir = self.root / "users" / "dev-user" / "channels" / channel_id / "runtime" / "oauth"
            token_dir.mkdir(parents=True)
            (token_dir / "token.json").write_text(json.dumps(TOKEN_OK), encoding="utf-8")

        a = self.client.get("/api/data/status", params={"user_id": "dev-user", "channel_id": "channel-a"})
        b = self.client.get("/api/data/status", params={"user_id": "dev-user", "channel_id": "channel-b"})
        self.assertEqual(a.status_code, 200)
        self.assertEqual(b.status_code, 200)
        self.assertEqual(a.json()["last_result"]["channel_id"], "A")
        self.assertEqual(b.json()["last_result"]["channel_id"], "B")
        self.assertTrue(a.json()["connected"])
        self.assertTrue(b.json()["connected"])
        self.assertNotEqual(a.json()["datasets"][0]["file"], b.json()["datasets"][0]["file"])

    def test_status_rejects_partial_scope(self) -> None:
        response = self.client.get("/api/data/status", params={"user_id": "dev-user"})
        self.assertEqual(response.status_code, 400)


# ------------------------------------------------------------------ actions


class TestActions(DataApiTestCase):
    def test_connect_spawns_with_cwd(self) -> None:
        self.write_token()
        r = self.client.post("/api/data/connect")
        self.assertEqual(r.status_code, 202)
        body = r.json()
        self.assertEqual(body["kind"], "connect")
        job = self.wait_job(body["job_id"])
        self.assertEqual(job["status"], "complete")
        self.assertEqual(job["exit_code"], 0)
        inv = self.invocations()
        self.assertEqual(len(inv), 1)
        # sys.argv khi chạy `python -c "..."` chỉ là ["-c"] — code string
        # không nằm trong argv; cwd là bằng chứng spawn đúng pull_dir.
        # (Flag `-u` do interpreter tiêu thụ nên không xuất hiện trong sys.argv —
        #  test trực tiếp builders ở TestBuilders dưới.)
        self.assertEqual(inv[0]["argv"], ["-c"])
        # os.getcwd() trong child trả đường dẫn canonical (resolve).
        self.assertEqual(inv[0]["cwd"], str(self.pull_dir.resolve()))

    def test_connect_requires_pull_dir(self) -> None:
        with mock.patch.dict(os.environ, {}):
            os.environ.pop("YT_DATA_PULL_DIR", None)
            r = self.client.post("/api/data/connect")
        self.assertEqual(r.status_code, 400)

    def test_pull_video_ids(self) -> None:
        r = self.client.post(
            "/api/data/pull", json={"mode": "video_ids", "video_ids": ["abc123_XY", "Zz0"]}
        )
        self.assertEqual(r.status_code, 202)
        job = self.wait_job(r.json()["job_id"])
        self.assertEqual(job["status"], "complete")
        argv = self.invocations()[0]["argv"]
        # sys.argv khi chạy `python youtube_pull.py ...`: argv[0] là tên script.
        self.assertEqual(argv[0], "youtube_pull.py")
        # builder đặt --out trước, --videos sau (sys.argv không có python).
        self.assertEqual(argv[1], "--out")
        self.assertEqual(argv[2], str((self.root / "data/channels/youtube_data.json").resolve()))
        self.assertEqual(
            argv[argv.index("--videos") : argv.index("--videos") + 3],
            ["--videos", "abc123_XY", "Zz0"],
        )

    def test_pull_range(self) -> None:
        r = self.client.post(
            "/api/data/pull",
            json={"mode": "range", "start_date": "2026-07-01", "end_date": "2026-07-31"},
        )
        self.assertEqual(r.status_code, 202)
        self.wait_job(r.json()["job_id"])
        argv = self.invocations()[0]["argv"]
        self.assertEqual(argv[argv.index("--start-date") + 1], "2026-07-01")
        self.assertEqual(argv[argv.index("--end-date") + 1], "2026-07-31")

    def test_pull_all(self) -> None:
        r = self.client.post("/api/data/pull", json={"mode": "all"})
        self.assertEqual(r.status_code, 202)
        self.wait_job(r.json()["job_id"])
        argv = self.invocations()[0]["argv"]
        self.assertEqual(argv, ["youtube_pull.py", "--out", str((self.root / "data/channels/youtube_data.json").resolve())])
        self.assertNotIn("--videos", argv)

    def test_pull_advanced_options(self) -> None:
        r = self.client.post(
            "/api/data/pull",
            json={
                "mode": "video_ids",
                "video_ids": ["abc"],
                "max_comments": 50,
                "max_replies": 5,
                "no_replies": True,
            },
        )
        self.assertEqual(r.status_code, 202)
        self.wait_job(r.json()["job_id"])
        argv = self.invocations()[0]["argv"]
        self.assertEqual(argv[argv.index("--max-comments") + 1], "50")
        self.assertEqual(argv[argv.index("--max-replies-per-thread") + 1], "5")
        self.assertIn("--no-replies", argv)

    def test_pull_custom_out_file(self) -> None:
        self.write_result("data/channels/custom.json", videos=2)
        r = self.client.post(
            "/api/data/pull",
            json={"mode": "all", "out_file": "data/channels/custom.json"},
        )
        self.assertEqual(r.status_code, 202)
        self.wait_job(r.json()["job_id"])
        argv = self.invocations()[0]["argv"]
        self.assertEqual(argv[argv.index("--out") + 1], str((self.root / "data/channels/custom.json").resolve()))
        # last_result giờ trỏ vào file mới — và /api/config quét được nó.
        b = self.client.get("/api/data/status").json()
        self.assertEqual(b["last_result"]["file"], "data/channels/custom.json")
        self.assertEqual(b["last_result"]["video_count"], 2)
        config_files = [f["name"] for f in self.client.get("/api/config").json()["input_files"]]
        self.assertIn("data/channels/custom.json", config_files)

    def test_pull_validation_400(self) -> None:
        cases = [
            {"mode": "wat"},
            {"mode": "video_ids"},
            {"mode": "video_ids", "video_ids": ["bad id!"]},
            {"mode": "video_ids", "video_ids": ["toolong_" * 3]},
            {"mode": "range", "start_date": "2026-07-01"},
            {"mode": "range", "start_date": "01-07-2026", "end_date": "2026-07-31"},
            {"mode": "range", "start_date": "2026-08-01", "end_date": "2026-07-01"},
            {"mode": "all", "out_file": "../escape.json"},
            {"mode": "all", "out_file": "notes.txt"},
            {"mode": "all", "out_file": "custom.json"},
            {"mode": "all", "max_comments": -3},
        ]
        for case in cases:
            r = self.client.post("/api/data/pull", json=case)
            self.assertEqual(r.status_code, 400, msg=str(case))
        self.assertEqual(self.invocations(), [])

    def test_reporting_setup(self) -> None:
        r = self.client.post("/api/data/reporting", json={"action": "setup"})
        self.assertEqual(r.status_code, 202)
        self.wait_job(r.json()["job_id"])
        argv = self.invocations()[0]["argv"]
        self.assertIn("--setup-reporting", argv)
        self.assertNotIn("--sync-reporting", argv)

    def test_reporting_sync(self) -> None:
        r = self.client.post(
            "/api/data/reporting", json={"action": "sync", "out_file": "data/channels/youtube_data.json"}
        )
        self.assertEqual(r.status_code, 202)
        self.wait_job(r.json()["job_id"])
        argv = self.invocations()[0]["argv"]
        self.assertIn("--sync-reporting", argv)
        self.assertEqual(argv[argv.index("--out") + 1], str((self.root / "data/channels/youtube_data.json").resolve()))

    def test_reporting_bad_action(self) -> None:
        r = self.client.post("/api/data/reporting", json={"action": "purge"})
        self.assertEqual(r.status_code, 400)


# --------------------------------------------------------------------- jobs


class TestJobs(DataApiTestCase):
    def start_sleeping(self, kind: str = "pull", sleep: float = 30.0) -> str:
        with mock.patch.dict(os.environ, {"YT_STUB_SLEEP": str(sleep)}):
            if kind == "pull":
                r = self.client.post("/api/data/pull", json={"mode": "all"})
            else:
                r = self.client.post("/api/data/connect")
        self.assertEqual(r.status_code, 202)
        return r.json()["job_id"]

    def test_status_busy_with_active_job(self) -> None:
        job_id = self.start_sleeping()
        try:
            b = self.client.get("/api/data/status").json()
            self.assertTrue(b["busy"])
            self.assertEqual(b["active_job"]["id"], job_id)
            self.assertEqual(b["active_job"]["kind"], "pull")
        finally:
            datapull.data_runner.cancel(job_id)

    def test_busy_409(self) -> None:
        job_id = self.start_sleeping()
        try:
            r = self.client.post("/api/data/pull", json={"mode": "all"})
            self.assertEqual(r.status_code, 409)
            r2 = self.client.post("/api/data/connect")
            self.assertEqual(r2.status_code, 409)
        finally:
            datapull.data_runner.cancel(job_id)

    def test_job_running_then_complete(self) -> None:
        job_id = self.start_sleeping(sleep=1.0)
        try:
            r = self.client.get("/api/data/jobs/%s" % job_id)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["status"], "running")
        finally:
            datapull.data_runner.cancel(job_id)
        job = self.wait_job(job_id)
        self.assertEqual(job["status"], "failed")  # bị SIGTERM sau cancel

    def test_job_failed_exit_code(self) -> None:
        with mock.patch.dict(os.environ, {"YT_STUB_EXIT": "3"}):
            r = self.client.post("/api/data/pull", json={"mode": "all"})
        self.assertEqual(r.status_code, 202)
        job = self.wait_job(r.json()["job_id"])
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["exit_code"], 3)

    def test_cancel_then_404(self) -> None:
        job_id = self.start_sleeping()
        r = self.client.post("/api/data/jobs/%s/cancel" % job_id)
        self.assertEqual(r.status_code, 202)
        self.assertTrue(r.json()["cancelled"])
        self.wait_job(job_id)
        r2 = self.client.post("/api/data/jobs/%s/cancel" % job_id)
        self.assertEqual(r2.status_code, 404)

    def test_job_404_unknown(self) -> None:
        r = self.client.get("/api/data/jobs/doesnotexist")
        self.assertEqual(r.status_code, 404)

    def test_log_paging_and_download(self) -> None:
        r = self.client.post("/api/data/pull", json={"mode": "all"})
        job_id = r.json()["job_id"]
        self.wait_job(job_id)
        page = self.client.get("/api/data/jobs/%s/log?offset=0&limit=10" % job_id).json()
        self.assertEqual(page["job_id"], job_id)
        self.assertTrue(page["log_exists"])
        self.assertTrue(page["eof"])
        self.assertGreater(page["total_lines"], 0)
        # marker kết thúc có trong log
        self.assertTrue(any("=== exit code 0 ===" in line for line in page["lines"]))
        dl = self.client.get("/api/data/jobs/%s/log?download=1" % job_id)
        self.assertEqual(dl.status_code, 200)
        self.assertIn("attachment", dl.headers["content-disposition"])
        self.assertIn(b"stub: running", dl.content)

    def test_log_unknown_job(self) -> None:
        page = self.client.get("/api/data/jobs/nope/log").json()
        self.assertFalse(page["log_exists"])
        self.assertEqual(page["lines"], [])
        dl = self.client.get("/api/data/jobs/nope/log?download=1")
        self.assertEqual(dl.status_code, 404)


class TestBuilders(unittest.TestCase):
    """Kiểm tra trực tiếp builders (argv trước lúc spawn).

    Flag `-u` (unbuffered) bị interpreter tiêu thụ nên không xuất hiện trong
    sys.argv của child — phải assert ngay trên kết quả builder.
    """

    PY = "/venv/bin/python"

    def test_connect_has_unbuffered(self) -> None:
        argv = datapull.build_connect_command(self.PY)
        self.assertEqual(argv[0], self.PY)
        self.assertEqual(argv[1], "-u")
        self.assertEqual(argv[2], "-c")
        self.assertIn("get_credentials", argv[3])

    def test_pull_has_unbuffered_before_script(self) -> None:
        out = Path("/tmp/out.json")
        argv = datapull.build_pull_command(self.PY, "all", out)
        self.assertEqual(argv[:3], [self.PY, "-u", "youtube_pull.py"])
        self.assertEqual(argv[3:5], ["--out", str(out)])

    def test_reporting_has_unbuffered(self) -> None:
        out = Path("/tmp/out.json")
        setup = datapull.build_reporting_command(self.PY, "setup", out)
        self.assertEqual(setup[:3], [self.PY, "-u", "youtube_pull.py"])
        sync = datapull.build_reporting_command(self.PY, "sync", out)
        self.assertEqual(sync[:3], [self.PY, "-u", "youtube_pull.py"])
        self.assertEqual(sync[-2:], ["--out", str(out)])

    def test_pull_modes_flags(self) -> None:
        out = Path("/tmp/out.json")
        ids = datapull.build_pull_command(self.PY, "video_ids", out, video_ids=["a1", "b2"])
        self.assertEqual(ids[-3:], ["--videos", "a1", "b2"])
        rng = datapull.build_pull_command(
            self.PY, "range", out, start_date="2026-01-01", end_date="2026-01-31"
        )
        self.assertEqual(rng[-4:], ["--start-date", "2026-01-01", "--end-date", "2026-01-31"])
        adv = datapull.build_pull_command(
            self.PY,
            "all",
            out,
            max_comments=50,
            max_replies=5,
            no_replies=True,
        )
        self.assertEqual(
            adv,
            [
                self.PY,
                "-u",
                "youtube_pull.py",
                "--out",
                str(out),
                "--max-comments",
                "50",
                "--max-replies-per-thread",
                "5",
                "--no-replies",
            ],
        )


if __name__ == "__main__":
    unittest.main()
