import unittest
from unittest.mock import Mock
import re

from youtube_pipeline.resource_pack.providers import (
    AIResourceProvider,
    _allocate_visual_events,
    _renumber_visual_chunk,
)
from youtube_pipeline.resource_pack.validation import validate_image_strategy


class ImageStrategyChunkTests(unittest.TestCase):
    def test_event_allocation_is_exact_and_every_section_has_coverage(self):
        allocation = _allocate_visual_events(47, [1.0, 1.2, 0.8])

        self.assertEqual(47, sum(allocation))
        self.assertTrue(all(count > 0 for count in allocation))
        self.assertGreater(allocation[1], allocation[2])

    def test_local_reuse_is_renumbered_to_global_beat(self):
        result = _renumber_visual_chunk([
            {
                "id": "C01-B01", "script_section": "S1", "visual_information": "opening",
                "mode": "literal", "new_image": True, "reuse_image_id": None,
            },
            {
                "id": "C01-B02", "script_section": "S1", "visual_information": "continuation",
                "mode": "literal", "new_image": False, "reuse_image_id": "C01-B01",
            },
        ], 9, "S3")

        self.assertEqual(["B009", "B010"], [beat["id"] for beat in result])
        self.assertEqual("B009", result[1]["reuse_image_id"])
        self.assertEqual(["S3", "S3"], [beat["script_section"] for beat in result])

    def test_future_or_external_reuse_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "reuse"):
            _renumber_visual_chunk([
                {
                    "id": "C01-B01", "script_section": "S1", "visual_information": "bad",
                    "mode": "literal", "new_image": False, "reuse_image_id": "C01-B02",
                },
            ], 1, "S1")

    def test_provider_builds_strategy_from_bounded_section_calls(self):
        provider = AIResourceProvider.__new__(AIResourceProvider)
        calls = []

        def call_json(_role, label, _system, prompt):
            calls.append(label)
            if label == "RP_IMAGE_STRATEGY_FOUNDATION":
                return {
                    "style_bible": "ink", "character_bible": "character",
                    "environment_bible": "room", "opening_visual_contract": {},
                }
            number = int(label.rsplit("_", 1)[1])
            target = int(re.search(r"Return EXACTLY\s+(\d+)", prompt).group(1))
            return {
                "visual_beats": [
                    {
                        "id": "C%02d-B%02d" % (number, index),
                        "script_section": "ignored", "visual_information": "visual %d" % index,
                        "mode": "literal", "new_image": True, "reuse_image_id": None,
                    }
                    for index in range(1, target + 1)
                ]
            }

        provider._call_json = Mock(side_effect=call_json)
        strategy = provider.create_image_strategy(
            {"visual_duration_seconds": 300, "chosen_title": "topic"},
            {"sections": [{"id": "S1", "relative_weight": 1}, {"id": "S2", "relative_weight": 1}]},
            {},
        )

        # Five minutes has 31 minimum events, split between two bounded calls.
        self.assertEqual("RP_IMAGE_STRATEGY_FOUNDATION", calls[0])
        self.assertEqual(3, len(calls))
        self.assertEqual(31, strategy["estimated_total_visual_events"])
        self.assertEqual(["B001", "B031"], [strategy["visual_beats"][0]["id"], strategy["visual_beats"][-1]["id"]])
        validate_image_strategy(strategy, {"visual_duration_seconds": 300}, {"sections": [{}, {}]})


if __name__ == "__main__":
    unittest.main()
