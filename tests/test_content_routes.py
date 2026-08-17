"""tests/test_content_routes.py — Test API /api/content/* endpoints.

Mọi test patch youtube_pipeline.content_manager._CONTENT_DIR vào
TemporaryDirectory — không bao giờ đụng content/ thật của repo.
"""
from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from youtube_pipeline import content_manager
from youtube_pipeline.api import app

QUEUE_MD = textwrap.dedent("""\
    # Video Queue

    | # | Hiện tượng | primary_core | Cơ chế chính | Cơ chế dự phòng | Frame văn hóa | Status |
    |---|---|---|---|---|---|---|
    | 1 | Im lặng khi bị tổn thương | ne_tranh | 愛着スタイル | 学習性無力感 | 本音 | queued |
    | 2 | Không thể từ chối | kiet_suc | 認知的不協和 | — | 空気を読む | queued |

    ## Chi tiết từng video

    ### 1. Người im lặng khi bị tổn thương
    - **working_title_jp:** 傷ついた時、黙ってしまう人の心理
    - **mechanism:** 愛着スタイル
    - **cultural_frame:** 本音

    ### 2. Người không thể từ chối
    - **working_title_jp:** 断れない人の心理
    - **mechanism:** 認知的不協和
    - **cultural_frame:** 空気を読む

    ## Nhật ký dùng (cập nhật sau mỗi lần đăng)

    | Ngày đăng | Video (queue #) | Cơ chế đã dùng | Frame đã dùng | Video ID |
    |---|---|---|---|---|
    | — | (chưa có video queue nào đăng) | — | — | — |
""")

MECHANISMS_MD = textwrap.dedent("""\
    # Mechanisms

    ## 1. 課題の分離 — ⛔ (tạm ngừng)
    - **Tác giả + năm:** 岸見一郎 (1999)
    - **Nguồn:** 嫌われる勇気

    ## 2. 感情労働
    - **Tác giả + năm:** Arlie Hochschild (1983)
    - **Nguồn:** The Managed Heart
""")

FRAMES_MD = textwrap.dedent("""\
    # Cultural Frames JP

    ## 1. 侘寂
    - **Khái niệm:** Vẻ đẹp trong sự không hoàn hảo
    - **Dùng ở bước nào:** Writing — closing validation
""")


class ContentRoutesTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.content_dir = Path(self._tmp.name) / "content"
        self.content_dir.mkdir(parents=True, exist_ok=True)
        self.patcher = mock.patch.object(content_manager, "_CONTENT_DIR", self.content_dir)
        self.patcher.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.patcher.stop()
        self._tmp.cleanup()

    def _queue_text(self) -> str:
        return (self.content_dir / "video-queue.md").read_text(encoding="utf-8")


class TestQueueRead(ContentRoutesTestCase):
    def test_queue_lists_topics_with_real_status(self) -> None:
        (self.content_dir / "video-queue.md").write_text(QUEUE_MD, encoding="utf-8")
        r = self.client.get("/api/content/queue")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(len(body["topics"]), 2)
        self.assertEqual(body["topics"][0]["queue_no"], 1)
        self.assertEqual(body["topics"][0]["hien_tuong"], "Im lặng khi bị tổn thương")
        self.assertEqual(body["topics"][0]["status"], "queued")
        # detail block merged in
        self.assertEqual(body["topics"][0]["title_vn"], "Người im lặng khi bị tổn thương")
        # placeholder diary → empty
        self.assertEqual(body["diary"], [])
        self.assertEqual(body["recent_mechanisms"], [])

    def test_queue_empty_when_no_file(self) -> None:
        r = self.client.get("/api/content/queue")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"topics": [], "diary": [], "recent_mechanisms": []})


class TestQueueInProgress(ContentRoutesTestCase):
    def test_marks_in_progress_and_updates_file(self) -> None:
        (self.content_dir / "video-queue.md").write_text(QUEUE_MD, encoding="utf-8")
        r = self.client.post("/api/content/queue/in-progress", json={"topic": "Im lặng khi bị tổn thương"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"queue_no": 1, "status": "in_progress", "changed": True})
        self.assertIn("| in_progress |", self._queue_text())

    def test_idempotent_second_call(self) -> None:
        (self.content_dir / "video-queue.md").write_text(QUEUE_MD, encoding="utf-8")
        self.client.post("/api/content/queue/in-progress", json={"topic": "Im lặng khi bị tổn thương"})
        r = self.client.post("/api/content/queue/in-progress", json={"topic": "Im lặng khi bị tổn thương"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["changed"], False)

    def test_unknown_topic_404(self) -> None:
        (self.content_dir / "video-queue.md").write_text(QUEUE_MD, encoding="utf-8")
        r = self.client.post("/api/content/queue/in-progress", json={"topic": "Ngoài queue"})
        self.assertEqual(r.status_code, 404)

    def test_empty_topic_400(self) -> None:
        r = self.client.post("/api/content/queue/in-progress", json={"topic": "  "})
        self.assertEqual(r.status_code, 400)


class TestQueuePublish(ContentRoutesTestCase):
    def test_publish_writes_diary_and_status(self) -> None:
        (self.content_dir / "video-queue.md").write_text(QUEUE_MD, encoding="utf-8")
        r = self.client.post(
            "/api/content/queue/publish",
            json={"topic": "Im lặng khi bị tổn thương", "mechanism": "愛着スタイル", "frame": "本音"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "published")
        text = self._queue_text()
        self.assertIn("| 1 | Im lặng khi bị tổn thương | ne_tranh | 愛着スタイル | 学習性無力感 | 本音 | published |", text)
        self.assertIn("#1 — ", text)  # diary row added
        self.assertIn("愛着スタイル", text)
        self.assertNotIn("(chưa có", text)  # placeholder dropped

    def test_already_published_409(self) -> None:
        (self.content_dir / "video-queue.md").write_text(QUEUE_MD, encoding="utf-8")
        self.client.post("/api/content/queue/publish", json={"topic": "Im lặng khi bị tổn thương"})
        r = self.client.post("/api/content/queue/publish", json={"topic": "Im lặng khi bị tổn thương"})
        self.assertEqual(r.status_code, 409)

    def test_unknown_topic_404(self) -> None:
        (self.content_dir / "video-queue.md").write_text(QUEUE_MD, encoding="utf-8")
        r = self.client.post("/api/content/queue/publish", json={"topic": "Ngoài queue"})
        self.assertEqual(r.status_code, 404)


class TestQueueVideoId(ContentRoutesTestCase):
    def test_fills_video_id_into_latest_diary_row(self) -> None:
        (self.content_dir / "video-queue.md").write_text(QUEUE_MD, encoding="utf-8")
        self.client.post(
            "/api/content/queue/publish",
            json={"topic": "Im lặng khi bị tổn thương", "mechanism": "愛着スタイル", "frame": "本音"},
        )
        r = self.client.post(
            "/api/content/queue/video-id",
            json={"topic": "Im lặng khi bị tổn thương", "video_id": "AbCdEf12345"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["video_id"], "AbCdEf12345")
        self.assertIn("| AbCdEf12345 |", self._queue_text())

    def test_no_diary_row_yet_409(self) -> None:
        (self.content_dir / "video-queue.md").write_text(QUEUE_MD, encoding="utf-8")
        r = self.client.post(
            "/api/content/queue/video-id",
            json={"topic": "Im lặng khi bị tổn thương", "video_id": "abc"},
        )
        self.assertEqual(r.status_code, 409)

    def test_empty_video_id_400(self) -> None:
        (self.content_dir / "video-queue.md").write_text(QUEUE_MD, encoding="utf-8")
        r = self.client.post(
            "/api/content/queue/video-id",
            json={"topic": "Im lặng khi bị tổn thương", "video_id": " "},
        )
        self.assertEqual(r.status_code, 400)


class TestLibraryRead(ContentRoutesTestCase):
    def test_mechanisms(self) -> None:
        (self.content_dir / "mechanisms.md").write_text(MECHANISMS_MD, encoding="utf-8")
        r = self.client.get("/api/content/mechanisms")
        self.assertEqual(r.status_code, 200)
        mechs = r.json()["mechanisms"]
        self.assertIn("感情労働", mechs)
        self.assertTrue(mechs["課題の分離"]["paused"])
        self.assertFalse(mechs["感情労働"]["paused"])

    def test_cultural_frames(self) -> None:
        (self.content_dir / "cultural-frames-jp.md").write_text(FRAMES_MD, encoding="utf-8")
        r = self.client.get("/api/content/cultural-frames")
        self.assertEqual(r.status_code, 200)
        frames = r.json()["frames"]
        self.assertIn("侘寂", frames)
        self.assertIn("concept", frames["侘寂"])

    def test_empty_when_missing(self) -> None:
        self.assertEqual(self.client.get("/api/content/mechanisms").json(), {"mechanisms": {}})
        self.assertEqual(self.client.get("/api/content/cultural-frames").json(), {"frames": {}})
