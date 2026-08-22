import unittest

from youtube_pipeline.resource_pack.metrics import japanese_spoken_cadence, scrub_source_citation_tokens, validate_japanese_script
from youtube_pipeline.resource_pack.prompts import (
    PLANNING_SYSTEM,
    REVIEW_SYSTEM,
    WRITING_SYSTEM,
    audit_prompt,
    repair_prompt,
    target_duration_min_from_contract,
)
from youtube_pipeline.resource_pack.pipeline import _mechanism_is_covered, _psychology_structure_issues, _script_repetition_findings
from youtube_pipeline.resource_pack.validation import (
    mechanism_is_covered,
    normalize_plan_editorial_metadata,
    normalize_plan_quality_metadata,
    normalize_review_list,
    psychology_hook_findings,
    validate_plan,
)
from youtube_pipeline.resource_pack.validation import normalize_image_prompts, normalize_thumbnail_prompt, validate_prompt_pack, validate_thumbnail


class PsychologyEditorialFlowTests(unittest.TestCase):
    def test_prompts_lock_the_editorial_spine_without_metric_quotas(self):
        combined = "\n".join((PLANNING_SYSTEM, WRITING_SYSTEM, REVIEW_SYSTEM))
        self.assertIn("sensory recognition", combined)
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

    def test_structure_accepts_localized_metadata_and_combined_quiet_landing(self):
        script = "帰宅後、外で使った努力の負担と次の行動の開始条件を別々に見てみる。"
        brief = {
            "selected_mechanisms": [{
                "name": "Nỗ lực điều chỉnh tích lũy được nhận biết muộn",
                "behavior_explained": "Khó bắt đầu sau khi về nhà",
                "why": "Nỗ lực được nhận biết muộn",
                "inner_process": "Chú ý chuyển sang hành động đơn giản",
            }],
            "origin_status": "skip",
        }
        plan = {
            "planning_quality_gate": {"ending_creates_self_understanding": True},
            "sections": [{
                "segment_function": "practical_shift",
                "psychological_job": "自分を責めず条件を観察する",
                "new_information": "開始条件を見直す",
                "state_advance": "自己非難 -> 自分の条件を理解する",
                "so_what_next": "静かに見る",
            }],
        }
        contract = {"core_psychological_question": "なぜ止まるのか", "main_tension": "対応できても止まる"}
        issues, _mechanisms, covered = _psychology_structure_issues(script, contract, plan, brief)
        self.assertEqual(issues, [])
        self.assertEqual(covered, ["Nỗ lực điều chỉnh tích lũy được nhận biết muộn"])

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
                "retention_turns": [{"after_section": "S3", "new_information": "注意が対応対象へ移る。", "why_continue": "休息へのcostが見える。", "payoff_kind": "consequence"}],
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

    def test_missing_planning_metadata_is_completed_without_a_model_retry(self):
        plan = {
            "sections": [{"id": "S1", "segment_function": "mechanism"}],
            "continuity_map": {"retention_turns": [{"after_section": "S1"}]},
        }
        self.assertTrue(normalize_plan_quality_metadata(plan))
        self.assertTrue(plan["planning_quality_gate"]["psychology_is_spine"])
        self.assertEqual("mechanism_reveal", plan["continuity_map"]["retention_turns"][0]["payoff_kind"])

    def test_continuity_turn_rejects_empty_teaser(self):
        functions = ["recognition", "mechanism", "insight_landing"]
        plan = {
            "retention_blueprint": [{"movement": "cold_open"}], "hook_draft": "返信の前で止まる。なぜでしょうか。",
            "continuity_map": {
                "big_open_loop": "なぜ止まるのか。", "payoff_path": ["反応の条件を見る。"],
                "retention_turns": [{"after_section": "S1", "new_information": "反応の条件が見える。", "why_continue": "次で明かします。", "payoff_kind": "mechanism_reveal"}],
            },
            "planning_quality_gate": {"no_duplicate_sections": True, "every_section_advances_state": True, "psychology_is_spine": True, "no_plot_or_character_arc": True, "ending_creates_self_understanding": True},
            "sections": [{"id": f"S{i}", "psychological_job": name, "behavior_link": "返信", "why_answered": "なぜ止まるか", "mechanisms_used": [], "example_budget": 0, "new_information": f"情報{i}", "state_advance": "before -> after", "so_what_next": "next", "segment_function": name} for i, name in enumerate(functions, 1)],
        }
        with self.assertRaisesRegex(ValueError, "teaser/FOMO"):
            validate_plan(plan)

    def test_spoken_cadence_is_advisory_except_unpunctuated_wall(self):
        normal = japanese_spoken_cadence("返事の前で止まる。理由を一つずつ見ます。\n\nこれは意志だけの問題ではありません。")
        self.assertTrue(normal["passed"], normal)
        analytical = japanese_spoken_cadence("これは" + "反応の条件を観察することが大切です。" * 8)
        self.assertTrue(analytical["passed"], analytical)
        malformed = japanese_spoken_cadence("あ" * 181)
        self.assertFalse(malformed["passed"])

    def test_duration_guideline_accepts_half_minute_notation(self):
        self.assertAlmostEqual(target_duration_min_from_contract({"target_duration_minutes": "8:30-10"}), 8.5)

    def test_hook_allows_sensory_opening_but_flags_plot_without_pivot(self):
        strong = (
            "休みの日なのに、座った瞬間から落ち着かない。"
            "本当は疲れているのに、通知も来ていない画面を開いてしまう。"
            "なぜ、何も起きていない時間ほど、自分で用事を探し始めるのでしょうか。"
        )
        weak = "夜、部屋に入った。その後、窓の外を見て、翌日を思い出した。ドアが開き、彼は歩いていった。"
        self.assertEqual([], psychology_hook_findings(strong))
        self.assertIn("opening_scene_became_plot_without_symbolic_psychological_pivot", psychology_hook_findings(weak))

    def test_direct_address_findings_flag_scene_only_cold_open(self):
        from youtube_pipeline.resource_pack.validation import direct_address_findings

        addressed = (
            "もし、心から祝いたいはずの友人の成功に触れた瞬間、胸の奥が重くなる自分に気づいたとしたら"
            "——あなたはその反応を、どう受け止めますか。画面に浮かんだ「おめでとう」の文字。その下で、指だけが止まる。"
        )
        scene_only = "夜、部屋に入ると、すぐスマホを開いてしまう。実は、いつもの反応が先に始まっています。"
        self.assertEqual([], direct_address_findings(addressed))
        self.assertEqual(
            ["opening_missing_direct_address_question"], direct_address_findings(scene_only)
        )

    def test_narrative_plan_prepends_direct_address_to_scene_first_hook(self):
        from youtube_pipeline.resource_pack.pipeline import _narrative_plan

        brief = {
            "core_psychological_question": "なぜ、いつもの反応が先に始まるのでしょうか",
            "common_misconception": "意志が弱い",
            "early_reframe": "",
            "psychological_identity": "習慣反応",
            "recognizable_behavior_signals": ["スマホを開く"],
            "selected_mechanisms": [{"name": "状況手がかりによる習慣反応"}],
            "origin_status": "skip",
            "strength_status": "skip",
            "cost_status": "required",
            "practical_shift_status": "useful",
            "editorial_dna": {"behavioral_entry": "スマホを開いてしまう", "memory_line": "条件を見る"},
            "narrative_pack": {
                "opening_image": "夜、部屋に入ると、すぐスマホを開いてしまう。",
                "movements": [
                    {"phase": "RECOGNITION", "new_information": "行動"},
                    {"phase": "MECHANISM", "new_information": "仕組み", "mechanisms_used": ["状況手がかりによる習慣反応"]},
                    {"phase": "INSIGHT_LANDING", "new_information": "理解"},
                ],
            },
        }
        plan = _narrative_plan(brief)
        self.assertTrue(plan["hook_draft"].startswith("あなたにも、心当たりはないでしょうか。"))
        validate_plan(plan, psychology_brief=brief)

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

    def test_narrative_plan_adds_reframe_after_a_scene_first_opening(self):
        from youtube_pipeline.resource_pack.pipeline import _narrative_plan

        brief = {
            "core_psychological_question": "なぜ、いつもの反応が先に始まるのでしょうか",
            "common_misconception": "意志が弱い",
            "early_reframe": "意志が消えたのではなく、状況の手がかりが反応を先に起動している",
            "psychological_identity": "習慣反応",
            "recognizable_behavior_signals": ["スマホを開く"],
            "selected_mechanisms": [{"name": "状況手がかりによる習慣反応"}],
            "origin_status": "skip",
            "strength_status": "skip",
            "cost_status": "required",
            "practical_shift_status": "useful",
            "editorial_dna": {"behavioral_entry": "スマホを開いてしまう", "memory_line": "条件を見る"},
            "narrative_pack": {
                "opening_image": "夜、部屋に入ると、すぐスマホを開いてしまう。",
                "movements": [
                    {"phase": "RECOGNITION", "new_information": "行動"},
                    {"phase": "MECHANISM", "new_information": "仕組み", "mechanisms_used": ["状況手がかりによる習慣反応"]},
                    {"phase": "INSIGHT_LANDING", "new_information": "理解"},
                ],
            },
        }
        plan = _narrative_plan(brief)
        self.assertIn("実は、意志が消えたのではなく", plan["hook_draft"])
        validate_plan(plan, psychology_brief=brief)

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
            "text_color": "#777777",
            "background_color": "#666666",
            "image_prompt": "An anonymous character hesitating before starting a task.",
            "negative_prompt": "watermark",
            "overlay_spec": {"lines": 1},
        }
        normalize_thumbnail_prompt(value)
        qa = validate_thumbnail(value, "なぜ最初の一歩だけが選べないのか")
        self.assertTrue(qa["passed"], qa["issues"])
        self.assertIn("16:9", value["image_prompt"])
        self.assertIn("no text", value["image_prompt"].lower())
        self.assertEqual(value["text_color"], "#FFE500")
        self.assertEqual(value["background_color"], "#111111")
        self.assertIn("text_zone", value["overlay_spec"])

    def test_short_thumbnail_headline_is_preserved_without_auto_suffix(self):
        value = {
            "concepts": [{"mode": "SELF_RECOGNITION", "text": "祝えない私"}],
            "chosen_mode": "SELF_RECOGNITION",
            "thumbnail_text": "祝えない私",
            "text_color": "#FFE500",
            "background_color": "#111111",
            "image_prompt": "16:9 ink illustration with thick black outline and gold accent, fictional character, no text",
            "negative_prompt": "watermark",
            "overlay_spec": {"lines": 1},
        }
        normalize_thumbnail_prompt(value)
        self.assertEqual(value["thumbnail_text"], "祝えない私")

    def test_repetition_gate_detects_duplicate_long_propositions(self):
        script = (
            "相手の成功を見て苦しくなるとき、それは自分の認めにくい願望に触れた反応かもしれません。"
            "相手の成功を見て胸が苦しくなるとき、それは自分の認めにくい願望に触れた反応かもしれません。"
        )
        findings = _script_repetition_findings(script)
        self.assertEqual(len(findings), 1)
        self.assertGreaterEqual(findings[0]["similarity"], 0.62)


if __name__ == "__main__":
    unittest.main()
