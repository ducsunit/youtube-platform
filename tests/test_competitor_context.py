"""tests/test_competitor_context.py — Checklist D: competitor context injection.

Covers:
- competitor_context.py itself (patterns constant, inject text)
- pure prompt builders: topic_candidates / review / thumbnail append the block
- pipeline integration: all three stages pass the block to the provider
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from youtube_pipeline import competitor_context
from youtube_pipeline.resource_pipeline import ResourcePackPipeline
from youtube_pipeline.resource_provider import DemoResourceProvider
from youtube_pipeline.resource_prompts import (
    baked_text_thumbnail_prompt,
    image_prompts_prompt,
    review_prompt,
    thumbnail_prompt,
    topic_candidates_prompt,
)
import youtube_pipeline.resource_prompts as resource_prompts


class CompetitorContextUnitTests(unittest.TestCase):
    def test_inject_text_contains_psychtoons_patterns(self):
        text = competitor_context.competitor_inject_text()
        self.assertIn("PsychToons", text)
        self.assertIn("2–4 giây", text)
        self.assertIn("9–11 phút", text)

    def test_inject_text_equals_baked_constant(self):
        self.assertEqual(
            competitor_context.competitor_inject_text(),
            competitor_context.PSYCHTOONS_PATTERNS
            + "\n"
            + competitor_context.PSYCHTOONS_WRITING_DNA,
        )

    def test_topic_candidates_prompt_includes_competitor_context(self):
        prompt = topic_candidates_prompt({}, {}, {}, competitor_context.competitor_inject_text())
        self.assertIn("PsychToons", prompt)

    def test_topic_candidates_prompt_omits_context_when_empty(self):
        prompt = topic_candidates_prompt({}, {}, {})
        self.assertNotIn("PsychToons", prompt)

    def test_review_prompt_includes_hook_check_when_context_given(self):
        contract = {"target_duration_minutes": "9-11"}
        prompt = review_prompt(
            contract, {}, {}, "draft", competitor_context.competitor_inject_text()
        )
        self.assertIn("PsychToons", prompt)
        self.assertIn("COMPETITOR HOOK CHECK", prompt)

    def test_review_prompt_omits_context_when_empty(self):
        contract = {"target_duration_minutes": "9-11"}
        prompt = review_prompt(contract, {}, {}, "draft")
        self.assertNotIn("PsychToons", prompt)
        self.assertNotIn("COMPETITOR HOOK CHECK", prompt)

    def test_thumbnail_prompt_includes_alignment_when_context_given(self):
        prompt = thumbnail_prompt(
            {}, "script", competitor_context.competitor_inject_text()
        )
        self.assertIn("PsychToons", prompt)
        self.assertIn("COMPETITOR ALIGNMENT", prompt)

    def test_thumbnail_prompt_omits_context_when_empty(self):
        prompt = thumbnail_prompt({}, "script")
        # PsychToons-style character là STYLE LOCK cố định của kênh — luôn xuất hiện.
        self.assertIn("PsychToons", prompt)
        self.assertNotIn("COMPETITOR ALIGNMENT", prompt)

    def test_style_lock_contains_qa_required_tokens(self):
        # Regression guard (production lỗi 2026-08-17): prompt gửi LLM phải chứa đủ
        # literal token mà validate_thumbnail bắt buộc — nếu không LLM trung thành
        # với prompt sẽ bị QA reject 3 lần liên tiếp.
        lock = resource_prompts.CHARACTER_STYLE_LOCK.lower()
        for token in ("flat illustrated", "thick black outline", "navy"):
            self.assertIn(token, lock)
        prompt = thumbnail_prompt({}, "script").lower()
        self.assertIn("flat illustrated", prompt)
        self.assertIn("navy", prompt)

    def test_thumbnail_prompt_requires_soft_gradient_composition(self):
        prompt = thumbnail_prompt({}, "script").lower()
        self.assertIn("soft", prompt)
        self.assertIn("gradient", prompt)
        self.assertIn("hard split", prompt)

    def test_baked_text_thumbnail_prompt_carries_baked_kanji(self):
        contract = {
            "thumbnail_text": "誰のせい？",
            "concepts": [{"scene": "The bald cartoon character sits alone at a wooden conference table."}],
        }
        prompt = baked_text_thumbnail_prompt(contract)
        self.assertIn("誰のせい？", prompt)
        self.assertIn("16:9", prompt)
        self.assertIn("cartoon", prompt)
        self.assertIn("PsychToons-style", prompt)
        self.assertNotIn("no text", prompt)
        # Spec chữ (2026-08-15): to, dễ đọc mobile, VÀNG + VIỀN ĐEN — regression guard.
        self.assertIn("EXTRA LARGE", prompt)
        self.assertIn("GOLD/yellow", prompt)
        self.assertIn("BLACK outline", prompt)
        self.assertIn("small mobile thumbnail", prompt)

    def test_baked_text_thumbnail_prompt_falls_back_without_text(self):
        prompt = baked_text_thumbnail_prompt({})
        self.assertIn("Japanese headline", prompt)
        self.assertIn("Negative:", prompt)

    # ── CHARACTER BIBLE đồng bộ (2026-08-16) ────────────────────────────────
    # Nhân vật chính phải NGUYÊN VĂN giống nhau ở mọi prompt — nghiên cứu vidIQ
    # (@PsychToonsHQ, video 2.35M views) đã chốt đặc điểm; mô tả chỉ tồn tại ở
    # CHARACTER_BIBLE và được nội suy, không nhân bản.

    def test_character_bible_single_source_in_code(self):
        """Mỗi cụm mô tả nhân vật chỉ xuất hiện ĐÚNG 1 lần trong source code
        (định nghĩa CHARACTER_BIBLE) — mọi prompt khác phải nội suy qua biến."""
        source = Path(resource_prompts.__file__).read_text(encoding="utf-8")
        for phrase in (
            "pale cream skin",
            "round black eyes",
            "slate-blue crewneck",
            "khaki straight-leg trousers",
            "fictional cartoon figure",
        ):
            self.assertEqual(
                source.count(phrase), 1,
                f"'{phrase}' phải xuất hiện đúng 1 lần (định nghĩa CHARACTER_BIBLE)",
            )

    def test_character_bible_present_in_all_prompts(self):
        """Mọi prompt (system, thumbnail, baked, image) nhúng CHARACTER_BIBLE —
        chặn regression 'prompt gen nhân vật không đồng bộ'."""
        contract = {
            "thumbnail_text": "誰のせい？",
            "concepts": [{"scene": "The character sits at a wooden conference table."}],
        }
        strategy = {
            "visual_beats": [
                {"id": "B01", "image_id": "IMG-01", "new_image": True, "visual_information": "x"}
            ]
        }
        prompts = [
            resource_prompts.THUMBNAIL_SYSTEM,
            thumbnail_prompt(contract, "script"),
            baked_text_thumbnail_prompt(contract),
            image_prompts_prompt(strategy, contract),
        ]
        for prompt in prompts:
            self.assertIn("pale cream skin", prompt)
            self.assertIn("PsychToons-style", prompt)
            self.assertIn("fictional cartoon figure", prompt)


class CompetitorContextPipelineTests(unittest.TestCase):
    class CapturingDemoProvider(DemoResourceProvider):
        def __init__(self):
            self.topic_candidates_context = None
            self.review_context = None
            self.thumbnail_context = None

        def create_topic_candidates(self, research, snapshot, performance, competitor_context=""):
            self.topic_candidates_context = competitor_context
            return super().create_topic_candidates(research, snapshot, performance, competitor_context)

        def review_script(self, contract, plan, source_pack, draft, competitor_context=""):
            self.review_context = competitor_context
            return super().review_script(contract, plan, source_pack, draft, competitor_context)

        def create_thumbnail(self, contract, script, competitor_context=""):
            self.thumbnail_context = competitor_context
            return super().create_thumbnail(contract, script, competitor_context)

    def _run(self, provider, root):
        pipeline = ResourcePackPipeline(
            provider, root, max_retries=1, retry_delay=0, progress=lambda _message: None
        )
        state = pipeline.create_state(
            json.dumps({"schema_version": 2, "videos": {}}), run_id="competitor-context"
        )
        return pipeline.run(state)

    def test_competitor_context_injected_in_topic_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = self.CapturingDemoProvider()
            completed = self._run(provider, Path(directory))
            self.assertEqual(completed.status, "complete")
            self.assertTrue(provider.topic_candidates_context)
            self.assertIn("PsychToons", provider.topic_candidates_context)

    def test_competitor_context_injected_in_review(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = self.CapturingDemoProvider()
            completed = self._run(provider, Path(directory))
            self.assertEqual(completed.status, "complete")
            self.assertTrue(provider.review_context)
            self.assertIn("PsychToons", provider.review_context)

    def test_competitor_context_injected_in_thumbnail(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = self.CapturingDemoProvider()
            completed = self._run(provider, Path(directory))
            self.assertEqual(completed.status, "complete")
            self.assertTrue(provider.thumbnail_context)
            self.assertIn("PsychToons", provider.thumbnail_context)


if __name__ == "__main__":
    unittest.main()
