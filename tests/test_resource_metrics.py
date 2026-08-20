import math
import pathlib
import unittest

from youtube_pipeline.japanese_metrics import (
    build_pause_map,
    japanese_script_metrics,
    non_whitespace_chars,
    validate_japanese_script,
)
from youtube_pipeline.resource_provider import _demo_script
from youtube_pipeline.sections import (
    PAUSE_BEFORE_OUTRO,
    PAUSE_BETWEEN_SECTIONS,
    PAUSE_PARAGRAPH_BREAK,
    insert_pause_tags,
    split_script_sections,
    strip_minimax_tags,
)
from youtube_pipeline import resource_pipeline, resource_prompts
from youtube_pipeline.resource_validation import (
    SENSITIVE_CLAIM_MARKERS,
    VALIDATION_PHRASES_JA,
    audit_passes,
    contrast_ratio,
    derive_visual_density_targets,
    normalize_audit_score,
    normalize_image_prompts,
    psychology_review_gate_verdict,
    select_video_candidates,
    title_overlap_percent,
    validate_image_strategy,
    validate_plan,
    validate_prompt_pack,
)


def _clean_audit(**overrides) -> dict:
    audit = {
        "decision": "pass",
        "overall_score": 100,
        "source_alignment": True,
        "outline_coverage": True,
        "title_alignment": True,
        "unsupported_claims": [],
        "missing_outline_points": [],
        "issues": [],
    }
    audit.update(overrides)
    return audit


class AuditGateTests(unittest.TestCase):
    def test_legacy_scores_are_ignored_by_audit_gate(self):
        self.assertEqual(normalize_audit_score({"overall_score": 9}), 90)
        self.assertEqual(normalize_audit_score({"overall_score": 100}), 100)
        self.assertTrue(audit_passes(_clean_audit(overall_score=9)))

    def test_low_or_invalid_scores_do_not_block(self):
        self.assertEqual(normalize_audit_score({"overall_score": 8}), 80)
        self.assertEqual(normalize_audit_score({"overall_score": "n/a"}), 0)
        self.assertTrue(audit_passes(_clean_audit(overall_score=8)))
        self.assertTrue(audit_passes(_clean_audit(overall_score=70)))
        self.assertTrue(audit_passes(_clean_audit(overall_score="n/a")))

    def test_advisory_issues_do_not_block_a_pass(self):
        # Auditor hay ghi nhận xét "không cần sửa" vào issues; note vô hại từng
        # làm chết cả run dù chính auditor kết luận pass.
        audit = _clean_audit(issues=["Cụm này hơi chung chung nhưng không gây hiểu lầm."])
        self.assertTrue(audit_passes(audit))

    def test_structured_gates_still_block(self):
        self.assertTrue(audit_passes(_clean_audit(decision="revise")))
        self.assertFalse(audit_passes(_clean_audit(unsupported_claims=["claim ngoài source"])))
        self.assertFalse(audit_passes(_clean_audit(missing_outline_points=["S4"])))
        self.assertFalse(audit_passes(_clean_audit(source_alignment=False)))
        self.assertFalse(audit_passes(_clean_audit(outline_coverage=False)))
        self.assertFalse(audit_passes(_clean_audit(title_alignment=False)))

    def test_language_alignment_false_alone_does_not_block(self):
        self.assertTrue(audit_passes(_clean_audit(language_alignment=False)))


class PsychologySemanticGateTests(unittest.TestCase):
    def test_semantic_review_gate_requires_all_dimensions(self):
        review = {
            "psychology_scorecard": {
                "psychology_spine": 8,
                "mechanism_depth": 8,
                "insight_density": 7,
                "recognition": 7,
                "story_dominance": 2,
                "example_dependency": 2,
                "reframe_signature_count": 2,
            }
        }
        passed, failed = psychology_review_gate_verdict(review)
        self.assertTrue(passed, failed)

    def test_semantic_review_gate_blocks_story_dominance(self):
        review = {
            "psychology_scorecard": {
                "psychology_spine": 8,
                "mechanism_depth": 8,
                "insight_density": 7,
                "recognition": 7,
                "story_dominance": 6,
                "example_dependency": 2,
                "reframe_signature_count": 2,
            }
        }
        passed, failed = psychology_review_gate_verdict(review)
        self.assertFalse(passed)
        self.assertIn("story_dominance", failed)

    def test_semantic_review_gate_fails_closed_without_scorecard(self):
        passed, failed = psychology_review_gate_verdict({})
        self.assertFalse(passed)
        self.assertEqual(failed, ["missing_psychology_scorecard"])

class PsychologyFirstPromptCouplingTests(unittest.TestCase):
    """All script-mutating prompts share psychology-first/anti-story rules."""

    def test_every_script_writing_prompt_is_psychology_first(self):
        prompts = {
            "WRITING_SYSTEM": resource_prompts.WRITING_SYSTEM,
            "REVIEW_SYSTEM": resource_prompts.REVIEW_SYSTEM,
            "REPAIR_SYSTEM": resource_prompts.REPAIR_SYSTEM,
        }
        for name, body in prompts.items():
            self.assertTrue("psychology" in body.lower() or "心理学" in body, name)
            self.assertIn("character arc", body, name)
            self.assertNotIn("ORIGIN_STORY", body, name)
            self.assertNotIn("Triple denial", body, name)
        self.assertIn('"score_report"', resource_prompts.REVIEW_SYSTEM)
        self.assertIn("reframe", resource_prompts.REVIEW_SYSTEM.lower())

    def test_structure_check_uses_anti_story_shared_helper(self):
        source = pathlib.Path(resource_pipeline.__file__).with_name("resource_pack").joinpath("pipeline.py").read_text(encoding="utf-8")
        self.assertIn("anti_story_findings(script)", source)
        self.assertNotIn("validation_phrases = VALIDATION_PHRASES_JA", source)


class ClaimVocabBanTests(unittest.TestCase):
    """Prompt and validator remain coupled to sensitive claim markers."""

    def test_every_blocked_marker_is_named_in_prompts(self):
        prompts = {
            "PLANNING_SYSTEM": resource_prompts.PLANNING_SYSTEM,
            "WRITING_SYSTEM": resource_prompts.WRITING_SYSTEM,
            "REVIEW_SYSTEM": resource_prompts.REVIEW_SYSTEM,
            "REPAIR_SYSTEM": resource_prompts.REPAIR_SYSTEM,
        }
        for name, body in prompts.items():
            for marker in SENSITIVE_CLAIM_MARKERS:
                self.assertIn(marker, body, "%s không cấm marker %r" % (name, marker))

    def test_planning_prompt_interpolates_the_ban(self):
        built = resource_prompts.planning_prompt(
            {"target_duration_minutes": "8-10", "chosen_title": "テスト" * 5},
            {"source_concept": "concept", "verified_sources": [], "allowed_paraphrases": []},
            {"selected_mechanisms": [], "origin_status": "unsupported"},
        )
        self.assertNotIn("{CLAIM_VOCAB_BAN_VI}", built)
        for marker in SENSITIVE_CLAIM_MARKERS:
            self.assertIn(marker, built)

    def test_planning_rejects_a_blocked_marker(self):
        sections = []
        functions = ["recognition", "misconception_reframe", "mechanism", "inner_world", "contradiction", "integration", "insight_landing"]
        for index, function in enumerate(functions, 1):
            sections.append({"id": "S%d" % index, "psychological_job": function, "behavior_link": "behavior", "why_answered": "why", "mechanisms_used": [], "example_budget": 0, "new_information": "info", "viewer_question_answered": "why", "state_advance": "before -> after", "so_what_next": "next", "segment_function": function})
        plan = {"retention_blueprint": "bp", "hook_draft": "hook", "planning_quality_gate": {"first_insight_before_30s": True, "first_major_payoff_before_5m": True, "no_duplicate_sections": True, "every_section_advances_state": True, "psychology_is_spine": True, "no_plot_or_character_arc": True, "ending_creates_self_understanding": True}, "sections": sections}
        plan["sections"][3]["new_information"] = "幼少期の場面"
        source_pack = {"source_concept": "concept", "verified_sources": [], "allowed_paraphrases": []}
        with self.assertRaisesRegex(ValueError, "幼少期"):
            validate_plan(plan, source_pack)


class ResourceMetricsTests(unittest.TestCase):
    def test_visual_density_is_derived_from_duration_and_sections(self):
        targets = derive_visual_density_targets(
            {"target_duration_minutes": "8-10"},
            {"sections": [{} for _ in range(8)]},
        )
        self.assertEqual(targets["duration_seconds_reference"], 540)
        self.assertEqual(targets["minimum_visual_events"], 46)
        self.assertEqual(targets["minimum_unique_images"], 40)

    def test_japanese_metrics_use_characters_not_words(self):
        value = "返事をする。\n少し待つ。"
        self.assertEqual(non_whitespace_chars(value), len("返事をする。少し待つ。"))
        metrics = japanese_script_metrics(value)
        self.assertIn("non_whitespace_chars", metrics)
        self.assertNotIn("word_count", metrics)

    def test_demo_script_passes_phase_one_gate(self):
        result = validate_japanese_script(_demo_script())
        self.assertTrue(result["passed"], result["issues"])
        self.assertGreaterEqual(result["non_whitespace_chars"], 2400)
        self.assertLessEqual(result["non_whitespace_chars"], 4700)

    def test_sections_round_trip_to_planning_count(self):
        script = _demo_script()
        sections, policy = split_script_sections(script, section_count=8)
        self.assertEqual(len(sections), 8)
        self.assertEqual("".join(section.text for section in sections), script)
        self.assertEqual(policy["section_count"], 8)
        self.assertEqual(policy["script_chars"], non_whitespace_chars(script))
        self.assertTrue(all(section.text.strip() for section in sections))

    def test_sections_and_pause_map_follow_script_content(self):
        script = _demo_script()
        sections, policy = split_script_sections(script, section_count=8)
        self.assertEqual(policy["script_chars"], non_whitespace_chars(script))
        self.assertTrue(policy["estimated_min_seconds"] <= policy["estimated_max_seconds"])
        pauses = build_pause_map(script)
        self.assertGreater(len(pauses), len(sections))
        self.assertTrue(all(cue["pause_seconds"] > 0 for cue in pauses))

    def test_pause_tag_insertion_round_trips_to_clean_script(self):
        script = _demo_script()
        sections, _ = split_script_sections(script, section_count=8)
        tagged = insert_pause_tags(script, sections)
        self.assertEqual(strip_minimax_tags(tagged), script)

    def test_pause_tag_placement_follows_rule_v7(self):
        script = _demo_script()
        sections, _ = split_script_sections(script, section_count=8)
        tagged = insert_pause_tags(script, sections)
        # Không tag ở đầu văn bản; không 2 tag liền nhau.
        self.assertFalse(tagged.startswith("<#"))
        self.assertNotRegex(tagged, r"<#\d[^>]*#>\s*<#\d[^>]*#>")
        # Giữa 2 section: <#1.5#>; trước section cuối (outro): <#1.0#>.
        self.assertIn("<#%s#>" % PAUSE_BETWEEN_SECTIONS, tagged)
        self.assertIn("<#%s#>" % PAUSE_BEFORE_OUTRO, tagged)
        self.assertIn("<#%s#>" % PAUSE_PARAGRAPH_BREAK, tagged)
        # Số tag giữa section == số ranh giới section (8 section → 7 ranh giới).
        self.assertEqual(
            tagged.count("<#%s#>" % PAUSE_BETWEEN_SECTIONS)
            + tagged.count("<#%s#>" % PAUSE_BEFORE_OUTRO),
            7,
        )
        # Tag đầu mỗi section đứng ngay trước đoạn đầu của section đó
        # (paragraph bên trong section đã mang <#0.6#> nên không khớp nguyên văn).
        for index, section in enumerate(sections[1:], start=1):
            marker = "<#%s#>" % (PAUSE_BEFORE_OUTRO if index == 7 else PAUSE_BETWEEN_SECTIONS)
            first_paragraph = section.text.lstrip().split("\n\n", 1)[0]
            self.assertIn(marker + first_paragraph, tagged)

    def test_strip_removes_all_tag_shapes(self):
        value = "<#0.6#>段落。<#1.5#>次。"
        self.assertEqual(strip_minimax_tags(value), "段落。次。")

    def test_thumbnail_math_is_deterministic(self):
        self.assertGreaterEqual(contrast_ratio("#FFFFFF", "#3B241C"), 7)
        self.assertLessEqual(
            title_overlap_percent("返信できない夜、なぜ心だけが疲れる？", "胸の重さ"),
            35,
        )

    def test_image_count_is_derived_from_each_videos_visual_beats(self):
        strategy = {
            "estimated_unique_images": 99,
            "estimated_total_visual_events": 99,
            "density_check": True,
            "no_filler_check": True,
            "opening_visual_contract": {"first_frame_scene": "scene"},
            "visual_beats": [
                {"id": "B01", "script_section": "S1", "visual_information": "first", "mode": "literal", "new_image": True, "reuse_image_id": None},
                {"id": "B02", "script_section": "S1", "visual_information": "reuse first", "mode": "literal", "new_image": False, "reuse_image_id": "B01"},
                {"id": "B03", "script_section": "S2", "visual_information": "second", "mode": "metaphor", "new_image": True, "reuse_image_id": None},
                {"id": "B04", "script_section": "S2", "visual_information": "reuse second", "mode": "literal", "new_image": False, "reuse_image_id": "IMG-02"},
            ],
        }
        validate_image_strategy(strategy)
        self.assertEqual(strategy["estimated_unique_images"], 2)
        self.assertEqual(strategy["estimated_total_visual_events"], 4)
        self.assertEqual(
            [beat["image_id"] for beat in strategy["visual_beats"]],
            ["IMG-01", "IMG-01", "IMG-02", "IMG-02"],
        )

        prompt_pack = {
            "images": [
                {"image_id": "IMG-01", "beat_ids": ["B01"], "prompt": "Japanese room"},
                {"image_id": "IMG-02", "beat_ids": ["B03"], "prompt": "Japanese street, 16:9"},
            ],
            "storyboard": [
                {"event_id": "E01", "beat_id": "B01", "image_id": "IMG-01", "visual_information": "first"},
                {"event_id": "E02", "beat_id": "B02", "image_id": "IMG-01", "visual_information": "reuse first"},
                {"event_id": "E03", "beat_id": "B03", "image_id": "IMG-02", "visual_information": "second"},
                {"event_id": "E04", "beat_id": "B04", "image_id": "IMG-02", "visual_information": "reuse second"},
            ],
        }
        normalize_image_prompts(prompt_pack)
        qa = validate_prompt_pack(prompt_pack, strategy)
        self.assertTrue(qa["passed"], qa["issues"])
        self.assertEqual(qa["unique_images"], 2)
        self.assertEqual(qa["visual_events"], 4)
        self.assertTrue(all("Negative:" in row["prompt"] for row in prompt_pack["images"]))

    def test_image_strategy_accepts_normalized_image_id_reuse(self):
        # Model có thể trả reuse_image_id kiểu "img_01"/"IMG01" thay vì "IMG-01" hoặc beat ID.
        strategy = {
            "estimated_unique_images": 99,
            "estimated_total_visual_events": 99,
            "density_check": True,
            "no_filler_check": True,
            "opening_visual_contract": {"first_frame_scene": "scene"},
            "visual_beats": [
                {"id": "B01", "script_section": "S1", "visual_information": "first", "mode": "literal", "new_image": True, "reuse_image_id": None},
                {"id": "B02", "script_section": "S1", "visual_information": "reuse first", "mode": "literal", "new_image": False, "reuse_image_id": "img_01"},
                {"id": "B03", "script_section": "S1", "visual_information": "reuse first again", "mode": "literal", "new_image": False, "reuse_image_id": "IMG01"},
                {"id": "B04", "script_section": "S2", "visual_information": "second", "mode": "metaphor", "new_image": True, "reuse_image_id": None},
                {"id": "B05", "script_section": "S3", "visual_information": "reuse later image", "mode": "literal", "new_image": False, "reuse_image_id": "IMG-02"},
            ],
        }
        validate_image_strategy(strategy)
        self.assertEqual(strategy["estimated_unique_images"], 2)
        self.assertEqual(strategy["estimated_total_visual_events"], 5)
        self.assertEqual(
            [beat["image_id"] for beat in strategy["visual_beats"]],
            ["IMG-01", "IMG-01", "IMG-01", "IMG-02", "IMG-02"],
        )
        with self.assertRaises(ValueError):
            validate_image_strategy(
                {
                    "estimated_unique_images": 0,
                    "estimated_total_visual_events": 0,
                    "density_check": True,
                    "no_filler_check": True,
                    "opening_visual_contract": {"first_frame_scene": "scene"},
                    "visual_beats": [
                        {"id": "B01", "script_section": "S1", "visual_information": "first", "mode": "literal", "new_image": False, "reuse_image_id": "IMG-99"},
                    ],
                }
            )

    # ------------------------------------------------------------ video candidates

    @staticmethod
    def _images(n: int, text: str = "cinematic scene") -> list[dict]:
        return [{"image_id": "IMG-%02d" % i, "beat_ids": ["B%02d" % i], "prompt": text}
                for i in range(1, n + 1)]

    @staticmethod
    def _storyboard(image_ids: list[str]) -> list[dict]:
        return [{"event_id": "E%02d" % i, "beat_id": "B%02d" % i, "image_id": image_id,
                 "new_image": True, "motion": "slow push-in", "visual_information": "scene"}
                for i, image_id in enumerate(image_ids, start=1)]

    def test_select_video_candidates_blocks_text_scenes(self):
        images = self._images(4) + [
            {"image_id": "IMG-05", "beat_ids": ["B05"], "prompt": "a typography infographic panel"},
            {"image_id": "IMG-06", "beat_ids": ["B06"], "prompt": "title card with caption at the bottom"},
        ]
        storyboard = self._storyboard([im["image_id"] for im in images])
        selected = select_video_candidates(images, storyboard)
        self.assertNotIn("IMG-05", selected)
        self.assertNotIn("IMG-06", selected)

    def test_select_video_candidates_keeps_hook_and_closer(self):
        images = self._images(6)
        storyboard = self._storyboard([im["image_id"] for im in images])
        selected = select_video_candidates(images, storyboard)
        self.assertIn("IMG-01", selected)   # hook
        self.assertIn("IMG-06", selected)   # closer

    def test_select_video_candidates_caps_at_max_count(self):
        images = self._images(12)
        storyboard = self._storyboard([im["image_id"] for im in images])
        self.assertEqual(len(select_video_candidates(images, storyboard)), 8)

    def test_select_video_candidates_floor_never_includes_blocked(self):
        images = [
            {"image_id": "IMG-01", "beat_ids": ["B01"], "prompt": "cinematic scene"},
        ] + [
            {"image_id": "IMG-%02d" % i, "beat_ids": ["B%02d" % i], "prompt": "infographic with diagram"}
            for i in range(2, 7)
        ]
        storyboard = self._storyboard([im["image_id"] for im in images])
        self.assertEqual(select_video_candidates(images, storyboard), ["IMG-01"])

    def test_select_video_candidates_deterministic_with_bonuses(self):
        images = self._images(6)
        # IMG-03 xuất hiện 2 event (density +2) — phải đứng trước ảnh cùng điểm khác.
        storyboard = self._storyboard(["IMG-01", "IMG-02", "IMG-03", "IMG-03", "IMG-04", "IMG-05"])
        selected = select_video_candidates(images, storyboard)
        self.assertEqual(selected, select_video_candidates(images, storyboard))
        self.assertIn("IMG-03", selected)


if __name__ == "__main__":
    unittest.main()
