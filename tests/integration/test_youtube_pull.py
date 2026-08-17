import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from youtube_pipeline.analysis import youtube_pull


class Request:
    def __init__(self, payload):
        self.payload = payload

    def execute(self, **_kwargs):
        return self.payload


class CommentThreads:
    def __init__(self):
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(kwargs)
        return Request(
            {
                "items": [
                    {
                        "id": "thread-1",
                        "snippet": {
                            "totalReplyCount": 1,
                            "topLevelComment": {
                                "id": "comment-1",
                                "snippet": {
                                    "textDisplay": "Hay",
                                    "likeCount": 3,
                                    "publishedAt": "2026-07-01T00:00:00Z",
                                    "updatedAt": "2026-07-01T00:00:00Z",
                                    "authorDisplayName": "Viewer",
                                    "authorChannelId": {"value": "channel-viewer"},
                                },
                            },
                        },
                    }
                ]
            }
        )


class Comments:
    def __init__(self):
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(kwargs)
        return Request(
            {
                "items": [
                    {
                        "id": "reply-1",
                        "snippet": {
                            "textDisplay": "Cảm ơn",
                            "likeCount": 1,
                            "publishedAt": "2026-07-01T01:00:00Z",
                            "updatedAt": "2026-07-01T01:00:00Z",
                            "authorDisplayName": "Owner",
                            "authorChannelId": {"value": "channel-owner"},
                        },
                    }
                ]
            }
        )


class CommentApi:
    def __init__(self):
        self.thread_resource = CommentThreads()
        self.comment_resource = Comments()

    def commentThreads(self):
        return self.thread_resource

    def comments(self):
        return self.comment_resource


class ReportTypes:
    def list(self, **_kwargs):
        return Request(
            {
                "reportTypes": [
                    {"id": "channel_reach_basic_a1"},
                    {"id": "channel_cards_a1"},
                ]
            }
        )


class Jobs:
    def __init__(self):
        self.created = []

    def list(self, **_kwargs):
        return Request(
            {
                "jobs": [
                    {
                        "id": "job-reach",
                        "reportTypeId": "channel_reach_basic_a1",
                        "name": "Reach",
                    }
                ]
            }
        )

    def create(self, body):
        self.created.append(body)
        return Request(
            {
                "id": "job-cards",
                "reportTypeId": body["reportTypeId"],
                "name": body["name"],
            }
        )


class ReportingApi:
    def __init__(self):
        self.jobs_resource = Jobs()

    def reportTypes(self):
        return ReportTypes()

    def jobs(self):
        return self.jobs_resource


class YoutubePullTests(unittest.TestCase):
    def menu_args(self):
        return SimpleNamespace(
            videos=["configured-video"],
            start_date=None,
            end_date=None,
            out="/path/that/does/not/exist.json",
            setup_reporting=False,
            sync_reporting=False,
        )

    def test_comments_include_replies_and_request_only_remaining(self):
        api = CommentApi()
        comments, status = youtube_pull.fetch_comments(
            api,
            "video-1",
            max_comments=1,
            include_replies=True,
            max_replies_per_thread=1,
        )

        self.assertEqual(status, "ok")
        self.assertEqual(len(comments), 1)
        self.assertEqual(comments[0]["replies"][0]["commentId"], "reply-1")
        self.assertEqual(api.thread_resource.calls[0]["maxResults"], 1)
        self.assertEqual(api.comment_resource.calls[0]["maxResults"], 1)

    def test_attach_reach_summary_uses_impression_weighted_ctr(self):
        output = {"videos": {"v1": {"analytics": {}}}}
        rows = [
            {
                "date": "2026-07-01",
                "video_id": "v1",
                "video_thumbnail_impressions": 100,
                "video_thumbnail_impressions_ctr": 10.0,
            },
            {
                "date": "2026-07-02",
                "video_id": "v1",
                "video_thumbnail_impressions": 300,
                "video_thumbnail_impressions_ctr": 2.0,
            },
        ]

        youtube_pull._attach_reach_summary(output, rows)

        reach = output["videos"]["v1"]["analytics"]["reach"]
        self.assertEqual(reach["impressions"], 400)
        self.assertEqual(reach["impressions_ctr"], 4.0)
        self.assertEqual(len(reach["by_day"]), 2)

    def test_convert_csv_values(self):
        self.assertEqual(youtube_pull._convert_csv_value("42"), 42)
        self.assertEqual(youtube_pull._convert_csv_value("-2"), -2)
        self.assertEqual(youtube_pull._convert_csv_value("3.5"), 3.5)
        self.assertEqual(youtube_pull._convert_csv_value("video-id"), "video-id")
        self.assertIsNone(youtube_pull._convert_csv_value(""))

    def test_atomic_json_write(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "nested" / "data.json"
            youtube_pull._write_json_atomic(target, {"ok": True})
            self.assertEqual(json.loads(target.read_text()), {"ok": True})

    def test_setup_reporting_jobs_is_idempotent(self):
        api = ReportingApi()
        result = youtube_pull.setup_reporting_jobs(api)

        self.assertEqual(result["existing"][0]["jobId"], "job-reach")
        self.assertEqual(result["created"][0]["reportTypeId"], "channel_cards_a1")
        self.assertIn("channel_reach_combined_a1", result["unavailable"])
        self.assertEqual(len(api.jobs_resource.created), 1)

    @patch("builtins.input", side_effect=["2", "video-a, video-b"])
    def test_menu_can_accept_video_ids(self, _mock_input):
        args = self.menu_args()
        self.assertTrue(youtube_pull.interactive_menu(args))
        self.assertEqual(args.videos, ["video-a", "video-b"])
        self.assertFalse(args.setup_reporting)
        self.assertFalse(args.sync_reporting)

    @patch("builtins.input", side_effect=["5"])
    def test_menu_can_select_reporting_sync(self, _mock_input):
        args = self.menu_args()
        self.assertTrue(youtube_pull.interactive_menu(args))
        self.assertTrue(args.sync_reporting)
        self.assertFalse(args.setup_reporting)

    @patch("builtins.input", side_effect=["0"])
    def test_menu_can_exit(self, _mock_input):
        self.assertFalse(youtube_pull.interactive_menu(self.menu_args()))


if __name__ == "__main__":
    unittest.main()
