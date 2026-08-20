from __future__ import annotations

import json
import unittest

from youtube_pipeline.resource_pack.analysis import build_channel_snapshot, build_performance_review
from youtube_pipeline.resource_pack.prompts import thumbnail_prompt


class PerformancePackagingDiagnosticsTests(unittest.TestCase):
    def test_reach_ctr_and_intro_retention_drive_packaging_hook_diagnosis(self):
        raw = json.dumps({
            "schema_version": 2,
            "videos": {
                "video-a": {
                    "videoId": "video-a",
                    "title": "心理テストのような長いタイトル",
                    "publishedAt": "2026-08-01T00:00:00Z",
                    "analytics": {
                        "summary": [{"views": 80, "averageViewPercentage": 8}],
                        "reach": {"impressions": 2500, "impressions_ctr": 0.02},
                        "retention": [
                            {"elapsedVideoTimeRatio": 0.01, "audienceWatchRatio": 0.95},
                            {"elapsedVideoTimeRatio": 0.10, "audienceWatchRatio": 0.22},
                        ],
                        "traffic_source": [{"insightTrafficSourceType": "RELATED_VIDEO", "views": 55}],
                    },
                }
            },
        })

        snapshot = build_channel_snapshot(raw)
        video = snapshot["recent_videos"][0]
        self.assertEqual(video["impressions"], 2500.0)
        self.assertEqual(video["ctr"], 0.02)
        self.assertEqual(video["intro_retention_10pct"], 0.22)
        self.assertEqual(video["traffic_sources"], {"RELATED_VIDEO": 55})

        review = build_performance_review(snapshot)
        self.assertEqual(review["primary_bottleneck"], "PACKAGING_AND_HOOK_MISMATCH")
        self.assertEqual(review["packaging_diagnostics"][0]["diagnosis"], "PACKAGING_AND_HOOK")

    def test_thumbnail_prompt_requires_click_and_hook_alignment(self):
        prompt = thumbnail_prompt({"chosen_title": "人と会うと疲れる心理"}, "人と会うと、帰宅後に動けなくなる。")
        self.assertIn('"click_hypothesis"', prompt)
        self.assertIn('"hook_alignment"', prompt)
        self.assertIn("CLICK/HOLD ALIGNMENT", prompt)

    def test_stale_export_is_visible_but_does_not_block_performance_review(self):
        raw = json.dumps({
            "generated_at": "2026-08-18T00:00:00+00:00",
            "videos": {},
        })

        snapshot = build_channel_snapshot(raw)
        self.assertEqual(snapshot["input_freshness"]["status"], "stale")
        review = build_performance_review(snapshot)
        self.assertTrue(any(warning.startswith("STALE_PERFORMANCE_INPUT") for warning in review["warnings"]))
