from __future__ import annotations

import unittest
from pathlib import Path

from youtube_pipeline.resource_pipeline import RESOURCE_PACK_REQUIRED, resource_pack_stages
from youtube_pipeline.resource_prompts import (
    ANTI_STORY_RULES,
    PLANNING_SYSTEM,
    REPAIR_SYSTEM,
    REVIEW_SYSTEM,
    WRITING_SYSTEM,
    psychology_brief_prompt,
)
from youtube_pipeline.resource_validation import (
    anti_story_findings,
    format_gate_verdict,
    generic_selfhelp_findings,
    psychology_format_metrics,
    validate_contract,
    validate_plan,
    validate_psychology_brief,
)


class PsychologyFirstFlowTests(unittest.TestCase):
    def _brief(self, route="PROCESS", origin="unsupported"):
        return {
            "phenomenon_or_type": "考えすぎる人",
            "psychological_identity": "不確実性を先回りして処理する傾向",
            "core_psychological_question": "なぜ考えが止まらないのか",
            "main_tension": "安心を得ようとする思考が不安を長引かせる",
            "recognizable_behavior_signals": ["反芻", "確認", "先読み"],
            "common_misconception": "意志が弱い",
            "early_reframe": "思考で不確実性を制御しようとしている",
            "mechanism_candidates": [{"name": "反芻"}],
            "selected_mechanisms": [{"name": "反芻", "role": "loop", "behavior_explained": "繰り返し考える", "why": "確実な答えを探す", "inner_process": "注意が同じ疑問へ戻る", "evidence_status": "editorial"}],
            "causal_chain": ["不確実性 -> 反芻 -> 一時的制御感 -> 疲労"],
            "inner_process_map": [{"trigger": "曖昧さ", "thought_attention_body": "注意固定", "response": "確認"}],
            "origin_status": origin, "strength_status": "useful", "cost_status": "required",
            "practical_shift_status": "useful", "route": route, "exclusions": ["diagnosis"],
        }

    def test_brief_schema_and_adaptive_routes(self):
        for route in ("PROCESS", "EXPLANATION", "PROFILE_SIGNS", "PARADOX", "RELATIONAL"):
            validate_psychology_brief(self._brief(route=route))

    def test_prompt_is_psychology_first_not_fixed_seven_part(self):
        combined = "\n".join((PLANNING_SYSTEM, WRITING_SYSTEM, REPAIR_SYSTEM))
        self.assertIn("Psychology", combined)
        self.assertIn("character arc", combined)
        self.assertNotIn("7-PART STRUCTURE", combined)
        self.assertNotIn("ORIGIN_STORY", combined)
        self.assertNotIn("Triple denial", combined)
        self.assertIn("direct-to-viewer", ANTI_STORY_RULES)

    def test_psychology_brief_prompt_requires_core_and_tension(self):
        prompt = psychology_brief_prompt("topic", {}, {})
        self.assertIn("core_psychological_question", prompt)
        self.assertIn("main_tension", prompt)
        self.assertIn("selected_mechanisms", prompt)
        self.assertIn("route", prompt)

    def test_anti_story_flags_sequential_plot_but_not_micro_example(self):
        bad = "ドアが開き、彼は部屋に入った。その後、窓の外を見て、翌日を思い出した。"
        self.assertTrue(anti_story_findings(bad))
        good = "会話の後に言葉を反芻することがあります。これは不確実性を減らそうとする注意の働きです。"
        self.assertEqual(anti_story_findings(good), [])

    def test_review_requires_reframe_signature_and_writing_cites_sparingly(self):
        # Gap 1: REVIEW_SYSTEM bắt >= 2 landing "XではなくY" (1 sớm + 1 ending).
        self.assertIn("REFRAME SIGNATURE", REVIEW_SYSTEM)
        self.assertIn("ではなく", REVIEW_SYSTEM)
        # Gap 2: WRITING_SYSTEM chốt chính sách citation — 1–2 study phản trực giác
        # đọc tên + năm trong narration, còn lại để citation block.
        self.assertIn("reframe", WRITING_SYSTEM.lower())
        self.assertIn("引用", WRITING_SYSTEM)

    def test_review_rule_md_documents_reframe_signature(self):
        rule_path = (
            Path(__file__).resolve().parent.parent
            / "skills" / "skill_tam_ly_hoc_script_production_JP" / "review-rule-v9.md"
        )
        content = rule_path.read_text(encoding="utf-8")
        self.assertIn("REFRAME SIGNATURE", content)
        self.assertIn("reframe_signature_findings", content)
        self.assertIn("reframe_signature_present", content)

    def _source_pack(self):
        return {
            "source_concept": "課題の分離",
            "editorial_application": "対人関係の悩みを分離の考え方で整理する",
            "verified_sources": [{"title": "嫌われる勇気", "supports": "承認欲求を手放す"}],
        }

    def test_brief_allows_sensitive_terms_in_candidates_exclusions_misconception(self):
        # Regression: AI phải được phép cân nhắc rồi LOẠI các cơ chế ngoài source.
        # Quét toàn bộ JSON từng làm brief hợp lệ fail 3 lần retry rồi chết run.
        brief = self._brief()
        brief["mechanism_candidates"] = [
            {"name": "扁桃体の過敏性", "role": "candidate", "source_support": "source pack に無し", "confidence": "low"},
            {"name": "生存本能の誤作動", "role": "candidate", "source_support": "source pack に無し", "confidence": "low"},
        ]
        brief["exclusions"] = ["扁桃体", "脳科学", "生存本能", "進化的", "幼少期", "親の顔色", "診断"]
        brief["common_misconception"] = "幼少期や生存本能だけで説明できるという思い込み"
        validate_psychology_brief(brief, self._source_pack())

    def test_brief_rejects_sensitive_terms_in_selected_mechanisms(self):
        brief = self._brief()
        brief["selected_mechanisms"][0]["why"] = "扁桃体が危険信号として処理するから"
        with self.assertRaisesRegex(ValueError, "claim ngoài source pack"):
            validate_psychology_brief(brief, self._source_pack())

    def test_brief_rejects_sensitive_terms_in_causal_chain(self):
        brief = self._brief()
        brief["causal_chain"] = ["幼少期 -> 親の顔色 -> 承認欲求 -> 反芻"]
        with self.assertRaisesRegex(ValueError, "claim ngoài source pack"):
            validate_psychology_brief(brief, self._source_pack())

    def test_plan_optional_reason_may_mention_excluded_concepts(self):
        # Meta-commentary không phải claim: giải thích "origin bỏ vì 幼少期 không
        # có source" không được làm plan fail — cùng bug class với brief.
        brief = self._brief()
        sections = []
        functions = ["recognition", "misconception_reframe", "mechanism", "inner_world", "integration", "insight_landing"]
        for i, function in enumerate(functions, 1):
            sections.append({
                "id": f"S{i}", "psychological_job": function, "behavior_link": "行動",
                "why_answered": "why", "mechanisms_used": ["反芻"] if function == "mechanism" else [],
                "example_budget": 0, "optional_reason": "origin bỏ: 幼少期 không có source",
                "new_information": str(i), "state_advance": "a -> b", "so_what_next": "next",
                "segment_function": function,
            })
        plan = {
            "retention_blueprint": [{}], "sections": sections, "hook_draft": "x",
            "redundancy_risks": ["nhắc lại 生存本能 gây trùng ý"],
            "planning_quality_gate": {
                "first_insight_before_35s": True, "first_major_payoff_before_5m": True,
                "no_duplicate_sections": True, "every_section_advances_state": True,
                "psychology_is_spine": True, "no_plot_or_character_arc": True,
                "ending_creates_self_understanding": True,
            },
        }
        validate_plan(plan, self._source_pack(), brief)

    def test_plan_rejects_origin_when_brief_says_unsupported(self):
        brief = self._brief(origin="unsupported")
        sections = []
        functions = ["recognition", "misconception_reframe", "mechanism", "inner_world", "origin_development", "integration", "insight_landing"]
        for i, function in enumerate(functions, 1):
            sections.append({"id": f"S{i}", "psychological_job": function, "behavior_link": "行動", "why_answered": "why", "mechanisms_used": ["反芻"] if function == "mechanism" else [], "example_budget": 0, "new_information": str(i), "state_advance": "a -> b", "so_what_next": "next", "segment_function": function})
        plan = {"retention_blueprint": [{}], "sections": sections, "hook_draft": "x", "planning_quality_gate": {"first_insight_before_35s": True, "first_major_payoff_before_5m": True, "no_duplicate_sections": True, "every_section_advances_state": True, "psychology_is_spine": True, "no_plot_or_character_arc": True, "ending_creates_self_understanding": True}}
        with self.assertRaisesRegex(ValueError, "origin"):
            validate_plan(plan, psychology_brief=brief)


class PsychologyFormatCheckTests(unittest.TestCase):
    """Phase 4 (format_lock) + Phase 8–10 (psychology_format_check metrics/gate)."""

    def _contract(self):
        return {
            "single_core_promise": "考えすぎの正体を理解し、課題の分離で思考の重さを軽くする",
            "psychological_identity": "不確実性を先回りして処理する傾向",
            "core_psychological_question": "なぜ考えが止まらないのか",
            "main_tension": "安心を得ようとする思考が不安を長引かせる",
            "route": "PROCESS",
            "selected_mechanisms": ["反芻"],
            "title_candidates": [
                {"title": "考えすぎる人に知ってほしい心の仕組みです"},
                {"title": "考えが止まらないのは意志のせいではない"},
                {"title": "不安を大きくしているのは思考の錯覚です"},
            ],
            "chosen_title": "考えが止まらないのは意志のせいではない",
            "target_char_min": 2400,
            "target_char_max": 4700,
            "hook_contract": {"recognition_by_seconds": 8},
            "thumbnail_brief": {"click_question": "なぜ考えが止まらないのか"},
            "format_lock": {
                "primary_format": "psychological profile / psychological deep-dive",
                "content_center": "một kiểu người — người suy nghĩ quá nhiều",
                "primary_narration": "direct psychological explanation",
                "secondary_device": "short behavioral examples",
                "forbidden_spine": [
                    "narrative story",
                    "personal anecdote",
                    "fictional character journey",
                    "chronological life story",
                ],
            },
        }

    def test_format_lock_is_required_and_psychological(self):
        validate_contract(self._contract())  # hợp lệ — không raise

        missing = self._contract()
        del missing["format_lock"]
        with self.assertRaisesRegex(ValueError, "format_lock"):
            validate_contract(missing)

        essay = self._contract()
        essay["format_lock"]["primary_format"] = "self-help essay"
        with self.assertRaisesRegex(ValueError, "psychological"):
            validate_contract(essay)

        short_spine = self._contract()
        short_spine["format_lock"]["forbidden_spine"] = ["narrative story"]
        with self.assertRaisesRegex(ValueError, "forbidden_spine"):
            validate_contract(short_spine)

    def test_psychology_format_metrics_scores_japanese_brief(self):
        brief = {
            "psychological_identity": "不確実性を先回りして処理し、他者の反応を自分の価値の証明と受け取る",
            "recognizable_behavior_signals": [
                "返信速度や絵文字の有無から相手の気持ちを推測する",
                "夜でもスマホで職場の通知を確認する",
            ],
            "selected_mechanisms": [{"name": "課題の分離"}],
        }
        script = (
            "あなたは返信速度や絵文字の有無を見て、相手の気持ちを推測してしまいます。"
            "夜でもスマホで職場の通知を確認して、不確実性を先回りして処理しようとします。"
            "他者の反応を自分の価値の証明と受け取っているのです。"
            "これは課題の分離で整理できます。"
        )
        metrics = psychology_format_metrics(script, brief)
        self.assertEqual(metrics["psychological_identity"], 10.0)
        self.assertEqual(metrics["behavioral_density"], 10.0)
        self.assertEqual(metrics["mechanism_depth"], 10.0)
        self.assertEqual(metrics["narrative_contamination"], 0.0)
        self.assertGreater(metrics["self_recognition"], 0.0)

    def test_psychology_format_metrics_detects_story_contamination(self):
        brief = {"psychological_identity": "不確実性を先回りして処理する傾向"}
        story = "ドアが開き、彼は部屋に入った。その後、窓の外を見て、翌日を思い出した。"
        self.assertGreater(
            psychology_format_metrics(story, brief)["narrative_contamination"], 0.0
        )

    def test_generic_selfhelp_detector(self):
        flattery = "あなたは繊細で、誰にも理解されない特別な存在です。そのままでいいのです。"
        findings = generic_selfhelp_findings(flattery)
        self.assertIn("あなたは繊細", findings)
        self.assertIn("誰にも理解されない", findings)
        self.assertEqual(generic_selfhelp_findings("これは課題の分離で整理できます。"), [])

    def test_reframe_signature_metric_counts_distinction_landings(self):
        # Reframe signature (đối thủ PsychToons "Not X. It's Y."): 3 landing
        # "XではなくY" + marker "その違い" => count 3, score trần 10.0.
        # Regex alternation xếp longest-first để "のではなく" không đếm 2 lần.
        script = (
            "問題は意志の弱さではなく、予測の仕組みです。"
            "努力が足りないのではなく、結びつけ方が逆なのです。"
            "これは欠点じゃなくて、生き延びるための工夫でした。"
            "その違いを知ることが最初の一歩です。"
        )
        metrics = psychology_format_metrics(script, {"psychological_identity": "反芻"})
        self.assertEqual(metrics["raw"]["reframe_signature_count"], 3)
        self.assertEqual(metrics["reframe_signature"], 10.0)
        self.assertIn("その違い", metrics["raw"]["difference_marker_hits"])

    def test_reframe_signature_ignores_rhetorical_negation(self):
        # "ではないでしょうか" là câu hỏi tu từ, không phải landing — 0 điểm.
        script = "答えは一つではないでしょうか。そう考えても良いのです。"
        metrics = psychology_format_metrics(script, {"psychological_identity": "反芻"})
        self.assertEqual(metrics["raw"]["reframe_signature_count"], 0)
        self.assertEqual(metrics["reframe_signature"], 0.0)

    def test_reframe_signature_zero_without_landings(self):
        script = "これは課題の分離で整理できます。不確実性を先回りして処理します。"
        metrics = psychology_format_metrics(script, {"psychological_identity": "反芻"})
        self.assertEqual(metrics["reframe_signature"], 0.0)

    def test_format_gate_verdict_is_suggested_not_blocking(self):
        passing = {
            "psychological_identity": 8.0,
            "behavioral_density": 8.0,
            "mechanism_depth": 8.0,
            "insight_density": 8.0,
            "reframe_signature": 7.0,
            "narrative_contamination": 1.0,
        }
        self.assertEqual(format_gate_verdict(passing), (True, []))

        failing = dict(passing)
        failing["insight_density"] = 2.0
        failing["narrative_contamination"] = 6.0
        ok, failed = format_gate_verdict(failing)
        self.assertFalse(ok)
        self.assertIn("insight_density", failed)
        self.assertIn("narrative_contamination", failed)

    def test_format_check_stage_runs_after_structure_check_and_feeds_pack(self):
        names = [stage.name for stage in resource_pack_stages()]
        # Sau structure_check để metric đo script CUỐI CÙNG (structure_check
        # được phép rewrite final_script khi repair) — lệch sơ đồ plan §17 có chủ đích.
        self.assertGreater(names.index("psychology_format_check"), names.index("structure_check"))
        self.assertLess(names.index("psychology_format_check"), names.index("post_script_assets"))
        stage = next(s for s in resource_pack_stages() if s.name == "psychology_format_check")
        self.assertIn("structure_check", stage.requires)
        self.assertIn("final_script", stage.requires)
        self.assertIn("psychology_format_check", RESOURCE_PACK_REQUIRED)
        self.assertIn("script_vi", RESOURCE_PACK_REQUIRED)


if __name__ == "__main__":
    unittest.main()
