import unittest

from youtube_pipeline.resource_pack.validation import (
    normalize_image_prompts,
    derive_visual_density_targets,
    validate_image_strategy,
    validate_prompt_pack,
)


class ResourcePackImageFlowTests(unittest.TestCase):
    def test_visual_density_prefers_finished_script_duration(self):
        targets = derive_visual_density_targets(
            {
                "target_duration_minutes": "6-12",
                "visual_duration_seconds": 328,
                "visual_duration_source": "script_qa_estimate",
            },
            {"sections": [{} for _ in range(6)]},
        )

        self.assertEqual(328, targets["duration_seconds_reference"])
        self.assertEqual("script_qa_estimate", targets["duration_source"])
        self.assertEqual(33, targets["minimum_visual_events"])

    def test_strategy_rejects_baked_text_request(self):
        strategy = {
            "estimated_unique_images": 1,
            "estimated_total_visual_events": 1,
            "density_check": True,
            "no_filler_check": True,
            "opening_visual_contract": {},
            "visual_beats": [
                {
                    "id": "B01",
                    "script_section": "S1",
                    "visual_information": "A scale with a stone labeled exactly Japanese text.",
                    "mode": "metaphor",
                    "new_image": True,
                    "reuse_image_id": None,
                }
            ],
        }

        with self.assertRaisesRegex(ValueError, "chữ/label"):
            validate_image_strategy(strategy)

    def test_storyboard_timing_is_built_without_model_timestamps(self):
        strategy = {
            "estimated_unique_images": 3,
            "estimated_total_visual_events": 3,
            "density_check": True,
            "no_filler_check": True,
            "opening_visual_contract": {},
            "visual_beats": [
                {"id": "B01", "script_section": "S1", "visual_information": "opening", "mode": "literal", "new_image": True, "reuse_image_id": None},
                {"id": "B02", "script_section": "S2", "visual_information": "mechanism", "mode": "literal", "new_image": True, "reuse_image_id": None},
                {"id": "B03", "script_section": "S2", "visual_information": "landing", "mode": "literal", "new_image": True, "reuse_image_id": None},
            ],
        }
        validate_image_strategy(strategy)
        value = {"images": [], "storyboard": []}

        normalize_image_prompts(
            value,
            strategy,
            duration_seconds=12,
            sections={"sections": [{"id": "S1", "chars": 100}, {"id": "S2", "chars": 200}]},
        )

        self.assertEqual(["0-4s", "4-8s", "8-12s"], [row["time"] for row in value["storyboard"]])
        self.assertEqual(12, value["timeline"]["duration_seconds"])
        self.assertTrue(validate_prompt_pack(value, strategy, require_timing=True)["passed"])

        value["storyboard"][-1]["time"] = "12-12s"
        self.assertFalse(validate_prompt_pack(value, strategy, require_timing=True)["passed"])


if __name__ == "__main__":
    unittest.main()
