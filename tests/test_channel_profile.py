"""tests/test_channel_profile.py — Multi-channel profile pack behavior."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from youtube_pipeline import channel_profile
from youtube_pipeline.channel_profile import (
    ChannelProfileError,
    build_config_block,
    detect_channel_id,
    load_channel_profile,
    resolve_channel_id,
)
from youtube_pipeline.competitor_context import competitor_inject_text
from youtube_pipeline.resource_pack import prompts as pack_prompts
from youtube_pipeline.resource_pack import source_catalog
from youtube_pipeline.resource_pack.providers import DemoResourceProvider
from youtube_pipeline.resource_pack.pipeline import ResourcePackPipeline
from youtube_pipeline.topic_history import history_path


PROFILE_JSON = {
    "schema_version": 1,
    "channel_id": "testchan",
    "display_name": "Test Channel",
    "youtube_channel_ids": ["UCTEST123"],
    "competitor": {
        "patterns": "## Competitor: TESTCOMP\n\n- Observed format: 10-minute essays.",
        "writing_dna": "- Open with the artifact.",
        "last_updated": "2026-08-22",
    },
    "sources": {
        "approved_catalog": [
            {"title": "Example Archive", "url": "https://example.test/archive", "supports": "demo"}
        ]
    },
    "claims": {
        "known_named_frameworks": ["テスト理論"],
        "framework_source_aliases": {"テスト理論": ("test",)},
    },
    "style_locks": {
        "CHARACTER_STYLE_LOCK": "sepia ink on parchment, deep-red accent",
        "text_color": "#F5EFE0",
        "accent_color": "#B22222",
        "background_color": "#2B2118",
    },
}


class ChannelProfileIsolation(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="chan-profile-"))
        self.runs = self.tmp / "runs"
        self.runs.mkdir()
        channel_profile.reset()

    def tearDown(self) -> None:
        channel_profile.reset()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_profile(self, channel_id: str = "testchan", payload: dict | None = None) -> Path:
        folder = self.tmp / "config" / "channels" / channel_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "profile.json"
        path.write_text(json.dumps(payload or PROFILE_JSON, ensure_ascii=False), encoding="utf-8")
        return path

    def test_load_missing_profile_returns_error(self):
        with self.assertRaises(ChannelProfileError):
            load_channel_profile(self.tmp, "ghost")

    def test_load_rejects_unknown_fields_and_bad_catalog(self):
        self._write_profile("bad", {"hacker_field": True})
        with self.assertRaises(ChannelProfileError):
            load_channel_profile(self.tmp, "bad")
        broken = dict(PROFILE_JSON)
        broken["sources"] = {"approved_catalog": [{"title": "no url"}]}
        self._write_profile("bad2", broken)
        with self.assertRaises(ChannelProfileError):
            load_channel_profile(self.tmp, "bad2")

    def test_detect_maps_youtube_channel_ids(self):
        self._write_profile()
        raw = json.dumps({"schema_version": 2, "videos": {}, "channel_id": "UCTEST123"})
        self.assertEqual(detect_channel_id(self.tmp, raw), "testchan")
        self.assertIsNone(detect_channel_id(self.tmp, json.dumps({"videos": {}})))

    def test_resolve_explicit_wins_without_file_but_warns_defaults(self):
        channel_id, profile = resolve_channel_id(self.tmp, "unknown-chan", None)
        self.assertEqual(channel_id, "unknown-chan")
        self.assertIsNone(profile)

    def test_default_block_matches_builtin_competitor_text(self):
        block = build_config_block(None, None)
        self.assertEqual(block["competitor_block"], competitor_inject_text())
        self.assertNotIn("known_named_frameworks", block)

    def test_block_carries_overrides(self):
        block = build_config_block("testchan", PROFILE_JSON)
        self.assertIn("TESTCOMP", block["competitor_block"])
        self.assertEqual(block["known_named_frameworks"], ["テスト理論"])
        self.assertEqual(block["_approved_catalog"][0]["url"], "https://example.test/archive")
        self.assertEqual(block["_style_locks"]["text_color"], "#F5EFE0")

    def test_activate_swaps_catalog_style_and_restores_on_reset(self):
        original_url_count = len(source_catalog.KNOWN_SOURCE_URLS)
        original_lock = pack_prompts.CHARACTER_STYLE_LOCK
        block = build_config_block("testchan", PROFILE_JSON)
        try:
            channel_profile.activate(block)
            self.assertIn("https://example.test/archive", source_catalog.KNOWN_SOURCE_URLS)
            self.assertNotEqual(len(source_catalog.KNOWN_SOURCE_URLS), original_url_count)
            self.assertEqual(pack_prompts.CHARACTER_STYLE_LOCK, "sepia ink on parchment, deep-red accent")
            self.assertEqual(
                channel_profile.active_claim_policy()[0],
                ["テスト理論"],
            )
            self.assertEqual(channel_profile.active_style_colors()["accent_color"], "#B22222")
        finally:
            channel_profile.reset()
        self.assertEqual(len(source_catalog.KNOWN_SOURCE_URLS), original_url_count)
        self.assertEqual(pack_prompts.CHARACTER_STYLE_LOCK, original_lock)

    def test_history_path_scopes_by_channel(self):
        legacy = history_path(self.tmp)
        scoped = history_path(self.tmp, "testchan")
        self.assertEqual(legacy, self.tmp / "data" / "topic-history.json")
        self.assertEqual(scoped, self.tmp / "data" / "channels" / "testchan" / "topic-history.json")


class PipelineChannelWiring(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="chan-pipeline-"))
        (self.tmp / "runs").mkdir()
        channel_profile.reset()

    def tearDown(self) -> None:
        channel_profile.reset()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_create_state_autodetects_channel_and_stores_block(self):
        self._write_profile()
        raw = json.dumps({"schema_version": 2, "videos": {}, "channel_id": "UCTEST123"})
        pipeline = ResourcePackPipeline(DemoResourceProvider(), self.tmp / "runs" / "v-auto")
        state = pipeline.create_state(raw, run_id="v-auto")
        block = state.config_snapshot["channel_profile"]
        self.assertEqual(block["channel_id"], "testchan")
        self.assertIn("TESTCOMP", block["competitor_block"])
        # Activation side effects applied process-wide for prompt building.
        self.assertIn("TESTCOMP", channel_profile.active_competitor_block())

    def _write_profile(self):
        folder = self.tmp / "config" / "channels" / "testchan"
        folder.mkdir(parents=True)
        (folder / "profile.json").write_text(
            json.dumps(PROFILE_JSON, ensure_ascii=False), encoding="utf-8"
        )


if __name__ == "__main__":
    unittest.main()
