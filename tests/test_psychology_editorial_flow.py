import unittest

from youtube_pipeline.resource_pack.metrics import scrub_source_citation_tokens, validate_japanese_script
from youtube_pipeline.resource_pack.prompts import (
    PLANNING_SYSTEM,
    REVIEW_SYSTEM,
    WRITING_SYSTEM,
    audit_prompt,
    repair_prompt,
    target_duration_min_from_contract,
)
from youtube_pipeline.resource_pack.pipeline import _mechanism_is_covered
from youtube_pipeline.resource_pack.validation import (
    mechanism_is_covered,
    normalize_plan_editorial_metadata,
    normalize_review_list,
    psychology_hook_findings,
    validate_plan,
)
from youtube_pipeline.resource_pack.validation import normalize_image_prompts, normalize_thumbnail_prompt, validate_prompt_pack, validate_thumbnail


class PsychologyEditorialFlowTests(unittest.TestCase):
    def test_prompts_lock_the_editorial_spine_without_metric_quotas(self):
        combined = "\n".join((PLANNING_SYSTEM, WRITING_SYSTEM, REVIEW_SYSTEM))
        self.assertIn("cold-open", combined)
        self.assertIn("1-2 mechanisms", combined)
        self.assertIn("một core question", combined)
        self.assertIn("không có số lần bắt buộc", combined)
        self.assertIn("Không rewrite toàn bộ chỉ để tối ưu metric", combined)

    def test_short_but_complete_japanese_script_is_not_rejected_for_length(self):
        script = (
            "帰宅すると、やることは分かっているのに、座ってスマホを開いてしまう。"
            "これは意志が消えたのではなく、休息へ向かう手がかりが先に選ばれている状態です。"
            "さらに何を準備し、どこから始めるかを一度に決めようとすると、最初の一歩の負担が重くなります。"
            "休むことでその場の負担は下がりますが、未完了は残り、次に始める時の重さになります。"
            "意志を強くするより、最初の行動を一つだけ固定し、必要なものを先に置く。"
            "自分が止まるのは、どの手がかりの後で、どの準備が重い瞬間なのかを見てみる。"
        )
        result = validate_japanese_script(script)
        self.assertTrue(result["passed"], result["issues"])
        self.assertEqual(result["length_status"], "short_but_allowed")
        self.assertTrue(result["length_is_advisory"])

    def test_structure_accepts_natural_mechanism_explanation_without_label(self):
        mechanism = {"name": "状況手がかりによる習慣反応"}
        script = "帰宅という状況と、何度も繰り返した行動が結びつき、意図より先にいつもの反応が始まります。"
        self.assertTrue(_mechanism_is_covered(script, mechanism))

    def test_structure_accepts_localized_mechanism_label(self):
        script = "ここでは課題の分離として、相手の課題と自分の課題を分けて考えます。"
        self.assertTrue(mechanism_is_covered(script, {"name": "Phân tách nhiệm vụ"}))

    def test_planning_uses_relative_weight_and_drops_clock_guesses(self):
        plan = {
            "sections": [{"id": "S1", "estimated_seconds": 65}],
            "retention_blueprint": [{"time": "0:00-0:20", "new_information": "hook"}],
            "continuity_map": {
                "time": "0:00-9:00",
                "retention_turns": [{"timestamp": "3:30", "new_information": "mechanism payoff"}],
            },
        }
        self.assertTrue(normalize_plan_editorial_metadata(plan))
        self.assertEqual(plan["sections"][0]["relative_weight"], 1.0)
        self.assertNotIn("estimated_seconds", plan["sections"][0])
        self.assertNotIn("time", plan["retention_blueprint"][0])
        self.assertNotIn("time", plan["continuity_map"])
        self.assertNotIn("timestamp", plan["continuity_map"]["retention_turns"][0])

    def test_continuity_map_accepts_information_turns_but_not_clock_template(self):
        functions = ["recognition", "misconception_reframe", "mechanism", "strength_cost", "insight_landing"]
        plan = {
            "retention_blueprint": [{"movement": "cold_open"}],
            "hook_draft": "休みの日なのに、疲れているのに通知を確認する。なぜ休めないのでしょうか。",
            "continuity_map": {
                "big_open_loop": "なぜ意図より先に反応が始まるのか。",
                "payoff_path": ["手がかりと反復が反応を説明する。"],
                "retention_turns": [{"after_section": "S3", "new_information": "注意が対応対象へ移る。", "why_continue": "休息へのcostを見る。"}],
            },
            "planning_quality_gate": {
                "no_duplicate_sections": True, "every_section_advances_state": True,
                "psychology_is_spine": True, "no_plot_or_character_arc": True,
                "ending_creates_self_understanding": True,
            },
            "sections": [
                {
                    "id": f"S{index}", "psychological_job": function, "behavior_link": "休息",
                    "why_answered": "なぜ起きるか", "mechanisms_used": [], "example_budget": 0,
                    "new_information": f"情報{index}", "state_advance": "before -> after",
                    "so_what_next": "next", "segment_function": function,
                }
                for index, function in enumerate(functions, start=1)
            ],
        }
        validate_plan(plan)

    def test_duration_guideline_accepts_half_minute_notation(self):
        self.assertAlmostEqual(target_duration_min_from_contract({"target_duration_minutes": "8:30-10"}), 8.5)

    def test_hook_requires_pain_contradiction_and_one_open_loop_as_review_diagnostic(self):
        strong = (
            "休みの日なのに、座った瞬間から落ち着かない。"
            "本当は疲れているのに、通知も来ていない画面を開いてしまう。"
            "なぜ、何も起きていない時間ほど、自分で用事を探し始めるのでしょうか。"
        )
        weak = "休みの日に通知を確認する人がいます。習慣について説明します。"
        self.assertEqual([], psychology_hook_findings(strong))
        self.assertIn("opening_lacks_pain_contradiction_or_open_loop", psychology_hook_findings(weak))

    def test_review_issue_objects_are_normalized_to_strings(self):
        result = normalize_review_list([
            {"issue": "hook chậm", "reason": "thiếu tension"},
            "mechanism chưa rõ",
            {"claim": "x", "reason": "ngoài source"},
        ])
        self.assertEqual(result, ["hook chậm — thiếu tension", "mechanism chưa rõ", "x — ngoài source"])

    def test_plan_allows_a_micro_scene_when_it_pivots_to_psychology(self):
        functions = ["recognition", "misconception_reframe", "mechanism", "contradiction", "insight_landing"]
        plan = {
            "retention_blueprint": [{"movement": "cold_open"}],
            "hook_draft": "帰宅すると、やることは分かっているのにスマホを開いてしまう。実は、意志が消えたのではなく、いつもの反応が先に始まっています。",
            "planning_quality_gate": {
                "no_duplicate_sections": True,
                "every_section_advances_state": True,
                "psychology_is_spine": True,
                "no_plot_or_character_arc": True,
                "ending_creates_self_understanding": True,
            },
            "sections": [
                {
                    "id": f"S{index}", "psychological_job": function, "behavior_link": "行動",
                    "why_answered": "なぜ起きるか", "mechanisms_used": [], "example_budget": 0,
                    "new_information": f"情報{index}", "state_advance": "before -> after",
                    "so_what_next": "next", "segment_function": function,
                }
                for index, function in enumerate(functions, start=1)
            ],
        }
        validate_plan(plan)

    def test_plan_allows_concise_three_movement_argument(self):
        functions = ["recognition", "mechanism", "insight_landing"]
        plan = {
            "retention_blueprint": [{"movement": "cold_open"}],
            "hook_draft": "通知を見ると、すぐに返せない。意志の問題ではなく、反応の条件が重くなっているのかもしれません。",
            "planning_quality_gate": {
                "no_duplicate_sections": True, "every_section_advances_state": True,
                "psychology_is_spine": True, "no_plot_or_character_arc": True,
                "ending_creates_self_understanding": True,
            },
            "sections": [
                {
                    "id": f"S{index}", "psychological_job": function, "behavior_link": "返信",
                    "why_answered": "なぜ止まるか", "mechanisms_used": [], "example_budget": 0,
                    "new_information": f"情報{index}", "state_advance": "before -> after",
                    "so_what_next": "next", "segment_function": function,
                }
                for index, function in enumerate(functions, start=1)
            ],
        }
        validate_plan(plan)

    def test_source_citation_leak_is_transliterated_or_removed(self):
        script = "Dennis Runger と Wendy Wood の Psychology of Habit を参照します。"
        cleaned, removed = scrub_source_citation_tokens(script)
        self.assertNotIn("Dennis", cleaned)
        self.assertNotIn("Psychology", cleaned)
        self.assertIn("デニス・ランガー", cleaned)
        self.assertIsInstance(removed, list)

    def test_audit_and_repair_prompts_do_not_leak_another_topics_framework(self):
        source_pack = {
            "source_concept": "反復と状況の手がかりによって形成される習慣",
            "allowed_paraphrases": ["習慣は反復と状況の手がかりによって形成されます"],
            "editorial_application": "会話の要求を手がかりに謝罪が先に出る反応として扱う",
            "verified_sources": [],
        }
        prompts = audit_prompt("auditor", {}, {}, source_pack, "") + repair_prompt({}, {}, source_pack, "", {})
        self.assertNotIn("課題の分離", prompts)
        self.assertNotIn("相手の評価まで決められない", prompts)

    def test_truncated_image_response_is_completed_from_strategy(self):
        strategy = {
            "estimated_unique_images": 2,
            "estimated_total_visual_events": 3,
            "density_check": True,
            "no_filler_check": True,
            "opening_visual_contract": {},
            "visual_beats": [
                {"id": "B01", "time": "DRAFT_TIMING", "image_id": "IMG-01", "new_image": True, "script_section": "S1", "mode": "literal", "visual_information": "opening"},
                {"id": "B02", "time": "DRAFT_TIMING", "image_id": "IMG-02", "new_image": True, "script_section": "S2", "mode": "literal", "visual_information": "mechanism"},
                {"id": "B03", "time": "DRAFT_TIMING", "image_id": "IMG-01", "reuse_image_id": "IMG-01", "new_image": False, "script_section": "S1", "mode": "callback", "visual_information": "callback"},
            ],
        }
        value = {"images": [{"image_id": "IMG-01", "prompt": "opening"}], "storyboard": []}
        normalize_image_prompts(value, strategy)
        qa = validate_prompt_pack(value, strategy)
        self.assertTrue(qa["passed"], qa["issues"])
        self.assertEqual(len(value["images"]), 2)
        self.assertEqual(len(value["storyboard"]), 3)

    def test_thumbnail_prompt_contract_is_completed_without_retry(self):
        value = {
            "concepts": [{"mode": "SELF_RECOGNITION", "text": "止まる理由"}],
            "chosen_mode": "SELF_RECOGNITION",
            "thumbnail_text": "止まる理由",
            "text_color": "#FFD700",
            "background_color": "#1A2332",
            "image_prompt": "An anonymous character hesitating before starting a task.",
            "negative_prompt": "watermark",
            "overlay_spec": {"lines": 1},
        }
        normalize_thumbnail_prompt(value)
        qa = validate_thumbnail(value, "なぜ最初の一歩だけが選べないのか")
        self.assertTrue(qa["passed"], qa["issues"])
        self.assertIn("16:9", value["image_prompt"])
        self.assertIn("no text", value["image_prompt"].lower())


if __name__ == "__main__":
    unittest.main()
