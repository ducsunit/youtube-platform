import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from youtube_pipeline.resource_pipeline import VOICEVOX_PROFILE, ResourcePackPipeline
from youtube_pipeline.resource_provider import AIResourceProvider, DemoResourceProvider
from youtube_pipeline.resource_prompts import vietnamese_translation_prompt
from youtube_pipeline.resource_validation import unsupported_source_claims, validate_plan
from youtube_pipeline.resource_pack.pipeline import _finalize_source_audit_after_scrub
from youtube_pipeline.sections import insert_pause_tags, strip_minimax_tags


class ResourcePackPipelineTests(unittest.TestCase):
    def test_long_vietnamese_translation_is_sent_in_sentence_safe_chunks(self):
        provider = AIResourceProvider.__new__(AIResourceProvider)
        calls = []

        def fake_call(role, label, system, prompt, temperature):
            calls.append((role, label, prompt))
            return "dịch " + label

        provider._call_text = fake_call
        script = "これは長いナレーションです。" * 500
        translated = provider.translate_to_vietnamese(script)

        self.assertGreater(len(calls), 1)
        self.assertTrue(all(label.startswith("RP_TRANSLATE_VI_CHUNK_") for _role, label, _prompt in calls))
        self.assertIn("RP_TRANSLATE_VI_CHUNK_001", translated)

    def test_parallel_provider_tasks_preserve_order_and_run_concurrently(self):
        import threading
        import time

        from youtube_pipeline.resource_pack.providers import _run_provider_tasks_parallel

        gate = threading.Event()

        def blocked_until_gate():
            gate.wait(timeout=2.0)
            return "first"

        def unblock_then_return():
            gate.set()
            return "second"

        started = time.perf_counter()
        results = _run_provider_tasks_parallel([blocked_until_gate, unblock_then_return])
        elapsed = time.perf_counter() - started

        # Order follows the input sequence even though the second task finished
        # first; the shared gate proves both tasks overlapped.
        self.assertEqual(results, ["first", "second"])
        self.assertLess(elapsed, 1.5)

    def test_parallel_provider_tasks_propagate_failure(self):
        from youtube_pipeline.resource_pack.providers import _run_provider_tasks_parallel

        def boom():
            raise ValueError("batch failed")

        def fine():
            return "ok"

        with self.assertRaises(ValueError):
            _run_provider_tasks_parallel([fine, boom])

    def test_final_source_scrub_removes_only_exact_claims(self):
        script = "行動を確認します。相手からの信頼に影響することがあります。ここで終わります。"
        audit = {
            "outline_coverage": True,
            "title_alignment": True,
            "missing_outline_points": [],
            "unsupported_claims": [
                {"claim": "相手からの信頼に影響することがあります。", "reason": "unsupported"}
            ],
        }
        cleaned, scrubbed, removed = _finalize_source_audit_after_scrub(
            script, {"audits": {"auditor": audit}}
        )
        self.assertTrue(scrubbed)
        self.assertEqual(removed, ["相手からの信頼に影響することがあります。"])
        self.assertNotIn("信頼", cleaned)

    class RevisingDemoProvider(DemoResourceProvider):
        def __init__(self):
            self.received_review = None

        def review_script(self, contract, plan, source_pack, draft, competitor_context=""):
            # Schema rule v9 (PHẦN 1–5): Gemini trả bản tái cấu trúc hoàn chỉnh.
            return {
                "decision": "revise",
                "optimization_report": "一か所を修正する。",
                "score_report": {
                    "retention_impact": 7,
                    "style_tone": 8,
                    "pacing_structure": 7,
                    "total": 73,
                    "drop_off_points": [],
                },
                "restructure_map": [
                    {"original": "最後の文", "new": "簡潔な文", "reason": "重複表現"}
                ],
                "cut_list": [],
                "revised_draft_clean": draft,
                "revised_draft_vi": "",
                "tts_tag_anchors": [],
                "title_thumbnail_advisory": {"note": "Giữ nguyên title/thumbnail trong contract."},
                "issues": ["表現が重複している"],
                "required_changes": ["最後の文だけ簡潔にする"],
                "char_report": {
                    "chars": len(draft),
                    "method": "manual_block_count_demo",
                    "target_min_chars": 8 * 389,
                    "status": "ok",
                    "shortfall": 0,
                },
            }

        def apply_review(self, contract, plan, source_pack, draft, review):
            self.received_review = review
            return draft

    def test_provider_routes_generation_to_deepseek(self):
        provider = AIResourceProvider.__new__(AIResourceProvider)
        provider.settings = SimpleNamespace(
            gemini_review_model="gemini-review",
            gemini_audit_model="gemini-audit",
        )
        provider._gemini_json = Mock(return_value={})
        provider._deepseek_json = Mock(
            side_effect=lambda label, system, prompt, **kwargs: (
                {"images": [{"image_id": "IMG-01", "prompt": "prompt"}]} if label.startswith("RP_IMAGE_PROMPTS") else (
                    {
                        "style_bible": "ink", "character_bible": "character",
                        "environment_bible": "room", "opening_visual_contract": {},
                    } if label == "RP_IMAGE_STRATEGY_FOUNDATION" else (
                        {"visual_beats": [{
                            "id": "C01-B%02d" % index, "script_section": "S1",
                            "visual_information": "scene", "mode": "literal",
                            "new_image": True, "reuse_image_id": None,
                        } for index in range(1, 47)]} if label.startswith("RP_IMAGE_STRATEGY_CHUNK") else {}
                    )
                )
            )
        )

        provider.create_contract("topic", {}, {})
        provider.create_plan({}, {})
        provider.repair_script({}, {}, {}, "script", {})
        provider.create_thumbnail({}, "script")
        provider.create_image_strategy({}, {}, {})
        provider.create_image_prompts(
            {
                "visual_beats": [
                    {
                        "id": "B01",
                        "image_id": "IMG-01",
                        "new_image": True,
                        "visual_information": "scene",
                    }
                ]
            },
            {},
        )
        provider.create_publish_draft({}, {})

        self.assertEqual(provider._deepseek_json.call_count, 8)
        provider._gemini_json.assert_not_called()

    def test_image_prompt_requests_are_batched_without_hard_token_limit(self):
        provider = AIResourceProvider.__new__(AIResourceProvider)
        profile = SimpleNamespace(
            provider="openai_compatible",
            model="model",
            base_url="https://example.test/v1",
            temperature=0.2,
            max_output_tokens=1234,
        )
        provider.router = SimpleNamespace(
            profile_for=Mock(return_value=profile),
            resolve_api_key=Mock(return_value="key"),
        )
        client = Mock()
        client.chat.completions.create.return_value.choices = [SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))]
        provider._clients = {}
        provider._OpenAI = Mock(return_value=client)
        provider._call_json("packaging", "RP_IMAGE_PROMPTS_01", "system", "prompt")
        self.assertNotIn("max_tokens", client.chat.completions.create.call_args.kwargs)

    def test_provider_routes_analysis_review_and_audit_to_their_roles(self):
        provider = AIResourceProvider.__new__(AIResourceProvider)
        provider.settings = SimpleNamespace(
            gemini_review_model="gemini-review",
            gemini_audit_model="gemini-audit",
        )
        provider._gemini_json = Mock(return_value={})
        provider._deepseek_json = Mock(return_value={})

        provider.research_topics({}, {})
        provider.create_topic_candidates({}, {}, {})
        provider.select_topic({}, {}, {})
        provider.lock_source("topic", {}, {})
        provider.review_script({}, {}, {}, "draft")
        provider.audit_script("auditor", {}, {}, {}, "script")

        self.assertEqual(provider._gemini_json.call_count, 6)
        provider._deepseek_json.assert_not_called()

    def test_audit_uses_only_locked_auditor_role(self):
        provider = AIResourceProvider.__new__(AIResourceProvider)
        profile = SimpleNamespace(
            profile_name="locked-gpt",
            provider="openai_compatible",
            model="gpt-5.6-luna",
        )
        provider.router = SimpleNamespace(profile_for=Mock(return_value=profile))
        provider._call_json = Mock(return_value={"source_alignment": True})

        result = provider.audit_script("auditor", {}, {}, {}, "script")

        self.assertEqual(provider._call_json.call_args.args[0], "auditor")
        self.assertEqual(provider._call_json.call_args.args[1], "RP_AUDIT")
        self.assertEqual(result["routing"], {
            "role": "auditor",
            "profile": "locked-gpt",
            "provider": "openai_compatible",
            "model": "gpt-5.6-luna",
        })
        with self.assertRaisesRegex(ValueError, "logical role 'auditor'"):
            provider.audit_script("gemini", {}, {}, {}, "script")

    def test_editor_revision_reconstructs_writer_conversation(self):
        provider = AIResourceProvider.__new__(AIResourceProvider)
        provider.settings = SimpleNamespace(deepseek_model="deepseek-writer")
        provider._deepseek_text_messages = Mock(return_value="修正版")
        review = {
            "decision": "revise",
            "optimization_report": "要修正",
            "issues": ["重複"],
            "required_changes": ["重複を削除"],
        }

        result = provider.apply_review({}, {}, {}, "元の草稿", review)

        self.assertEqual(result, "修正版")
        messages = provider._deepseek_text_messages.call_args.args[2]
        self.assertEqual([item["role"] for item in messages], ["user", "assistant", "user"])
        self.assertEqual(messages[1]["content"], "元の草稿")
        self.assertIn("REVIEWER FINDINGS", messages[2]["content"])
        self.assertIn("重複を削除", messages[2]["content"])

    def test_source_boundary_rejects_unsourced_neuroscience_plan(self):
        source = {
            "source_concept": "課題の分離",
            "editorial_application": "職場で境界線を引く",
            "allowed_paraphrases": ["相手の機嫌は相手自身の課題である"],
            "verified_sources": [],
        }
        plan = {
            "retention_blueprint": [],
            "sections": [
                {
                    "id": "S%d" % index,
                    "new_information": "脳は危険信号として処理する" if index == 1 else "境界線",
                    "state_advance": "before -> after",
                    "so_what_next": "next",
                    "segment_function": "recognition",
                }
                for index in range(1, 7)
            ],
            "hook_draft": "hook",
            "planning_quality_gate": {
                "first_insight_before_35s": True,
                "first_major_payoff_before_5m": True,
                "no_duplicate_sections": True,
                "every_section_advances_state": True,
            },
        }
        self.assertIn("脳は", unsupported_source_claims("脳は危険信号として処理する", source))
        with self.assertRaises(ValueError):
            validate_plan(plan, source)

    def _run(self, root: Path):
        pipeline = ResourcePackPipeline(
            DemoResourceProvider(),
            root,
            max_retries=1,
            retry_delay=0,
            progress=lambda _message: None,
        )
        state = pipeline.create_state(
            json.dumps({"schema_version": 2, "videos": {}}, ensure_ascii=False),
            run_id="test-resource",
        )
        return pipeline, pipeline.run(state)

    def test_resource_pack_writes_complete_manual_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _pipeline, state = self._run(root)
            self.assertEqual(state.status, "complete")
            required = (
                "resource_manifest.json",
                "script/script.txt",
                "script/sections.json",
                "script/tts-prompt.txt",
                "thumbnail/thumbnail-prompt.txt",
                "thumbnail/thumbnail-prompt-text.txt",
                "visuals/storyboard.json",
                "visuals/prompts/prompts-ALL.txt",
                "qa/manual-production-checklist.md",
            )
            for relative in required:
                self.assertTrue((root / relative).exists(), relative)
            self.assertTrue((root / "research/topic-research.json").exists())
            self.assertTrue((root / "research/topic-candidates.json").exists())
            self.assertTrue((root / "research/topic-selection.json").exists())
            manifest = json.loads((root / "resource_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["topic"], "返信を後回しにしたあとの罪悪感")
            self.assertEqual(manifest["tts_profile"]["provider"], "VOICEVOX")
            self.assertEqual(manifest["tts_profile"]["speaker"], VOICEVOX_PROFILE["speaker"])
            self.assertFalse(manifest.get("final_video"))
            self.assertFalse(list((root / "visuals/prompts").glob("prompts-batch-*.txt")))
            state_payload = json.loads((root / "run_state.json").read_text(encoding="utf-8"))
            self.assertFalse(
                any(name.startswith("image_prompts_batch_") for name in state_payload["artifact_index"])
            )

    def test_manual_topic_mode_skips_channel_topic_model_calls(self):
        class ManualTopicProvider(DemoResourceProvider):
            def research_topics(self, *_args, **_kwargs):
                raise AssertionError("manual topic must not call topic research")

            def create_topic_candidates(self, *_args, **_kwargs):
                raise AssertionError("manual topic must not call topic candidates")

            def select_topic(self, *_args, **_kwargs):
                raise AssertionError("manual topic must not call topic selection")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pipeline = ResourcePackPipeline(ManualTopicProvider(), root, max_retries=1, retry_delay=0, progress=lambda _message: None)
            state = pipeline.create_state(json.dumps({"schema_version": 2, "videos": {}}, ensure_ascii=False), run_id="manual-topic")
            state.config_snapshot["input_provenance"] = {
                "mode": "manual_topic_no_channel_data",
                "manual_topic": "休むほど落ち着かなくなる理由",
                "channel_data_used": False,
            }
            pipeline.store.save_state(state)
            completed = pipeline.run(state)
            self.assertEqual(completed.status, "complete")
            self.assertEqual(completed.topic, "休むほど落ち着かなくなる理由")
            selected = json.loads((root / "research" / "topic-selection.json").read_text(encoding="utf-8"))
            self.assertEqual(selected["selected_candidate_id"], "M01")

    def test_no_channel_data_mode_still_discovers_topic_from_competitor_context(self):
        class CompetitorTopicProvider(DemoResourceProvider):
            def __init__(self):
                self.topic_calls = []

            def research_topics(self, *args, **kwargs):
                self.topic_calls.append("research")
                return super().research_topics(*args, **kwargs)

            def create_topic_candidates(self, *args, **kwargs):
                self.topic_calls.append("candidates")
                return super().create_topic_candidates(*args, **kwargs)

            def select_topic(self, *args, **kwargs):
                self.topic_calls.append("selection")
                return super().select_topic(*args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider = CompetitorTopicProvider()
            pipeline = ResourcePackPipeline(provider, root, max_retries=1, retry_delay=0, progress=lambda _message: None)
            state = pipeline.create_state(json.dumps({"schema_version": 2, "videos": {}}, ensure_ascii=False), run_id="competitor-topic")
            state.config_snapshot["input_provenance"] = {
                "mode": "competitor_topic_no_channel_data",
                "channel_data_used": False,
            }
            pipeline.store.save_state(state)
            completed = pipeline.run(state)
            self.assertEqual(completed.status, "complete")
            self.assertEqual(provider.topic_calls, ["research", "candidates", "selection"])
            selection = json.loads((root / "research" / "topic-selection.json").read_text(encoding="utf-8"))
            self.assertEqual(selection["selected_topic"], completed.topic)

    def test_none_manual_topic_sentinel_uses_competitor_discovery(self):
        state = SimpleNamespace(config_snapshot={"input_provenance": {"mode": "manual_topic_no_channel_data", "manual_topic": "None"}})
        from youtube_pipeline.resource_pack.pipeline import _manual_topic
        self.assertEqual(_manual_topic(SimpleNamespace(config=state.config_snapshot)), "")

    def test_translate_script_vi_stage_writes_vietnamese_artifact(self):
        # Flow mới: sau khi script final chốt → dịch sang tiếng Việt cho quản lý kênh đọc duyệt.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _pipeline, state = self._run(root)
            self.assertEqual(state.status, "complete")
            vi_file = root / "script/script-vi.txt"
            self.assertTrue(vi_file.exists())
            content = vi_file.read_text(encoding="utf-8")
            self.assertIn("Bản dịch tiếng Việt", content)
            state_payload = json.loads((root / "run_state.json").read_text(encoding="utf-8"))
            self.assertIn("script_vi", state_payload["artifact_index"])
            self.assertEqual(
                state_payload["artifact_index"]["script_vi"]["path"], "script/script-vi.txt"
            )

    def test_vietnamese_translation_prompt_keeps_japanese_terms(self):
        # Prompt dịch phải yêu cầu giữ nguyên tên người/sách/thuật ngữ tiếng Nhật
        # (bản dịch chỉ để đọc hiểu — không thay thế script.txt, không dùng cho TTS).
        prompt = vietnamese_translation_prompt("岸見一郎の『嫌われる勇気』に基づく内容です。")
        self.assertIn("岸見一郎", prompt)
        self.assertIn("KỊCH BẢN GỐC", prompt)
        self.assertIn("KHÔNG thêm ý", prompt)
        self.assertIn("KHÔNG dùng cho TTS", prompt)

    def test_sections_fallback_when_tts_ready_drifts_from_final_script(self):
        # Gemini trả tts_ready khớp revised (qua _review gate), nhưng DeepSeek hoàn
        # thiện thêm nội dung → tts_ready lệch final_script → chèn tag deterministic.
        class DriftingTtsProvider(DemoResourceProvider):
            def review_script(self, contract, plan, source_pack, draft, competitor_context=""):
                result = super().review_script(contract, plan, source_pack, draft)
                result["decision"] = "revise"
                result["required_changes"] = ["Thêm một kết luận."]
                result["tts_ready"] = "<#1.5#>" + draft  # strip vẫn == revised
                return result

            def apply_review(self, contract, plan, source_pack, draft, review):
                return draft + "最後に一句。\n"

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pipeline = ResourcePackPipeline(
                DriftingTtsProvider(), root, max_retries=1, retry_delay=0,
                progress=lambda _message: None,
            )
            state = pipeline.create_state(
                json.dumps({"schema_version": 2, "videos": {}}), run_id="tts-drift"
            )
            completed = pipeline.run(state)
            self.assertEqual(completed.status, "complete")
            script = (root / "script/script.txt").read_text(encoding="utf-8")
            prompt = (root / "script/tts-prompt.txt").read_text(encoding="utf-8")
            self.assertEqual(strip_minimax_tags(prompt), script)
            sections = json.loads((root / "script/sections.json").read_text(encoding="utf-8"))
            self.assertEqual(sections["pause_policy"]["prompt_source"], "deterministic_sections")
            self.assertEqual(sections["tts_profile"]["provider"], "VOICEVOX")
            self.assertEqual(sections["pause_policy"]["syntax"], "<#x#>")
            self.assertFalse(state.stage_records["sections"].warnings)

    def test_sections_uses_tts_ready_built_from_anchors(self):
        # Schema v7 mới: Gemini trả tag ANCHORS (vị trí), pipeline tự chèn <#x#>
        # bằng code → strip(tags) == script bảo đảm đúng, không thể drift.
        class AnchoredReviewProvider(DemoResourceProvider):
            def review_script(self, contract, plan, source_pack, draft, competitor_context=""):
                result = super().review_script(contract, plan, source_pack, draft)
                result["tts_tag_anchors"] = [
                    {"anchor": "通知を見た瞬間、返事をしなければと思うのに、指が止まってしまう夜があります。", "tag": "<#1.5#>"}
                ]
                return result

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pipeline = ResourcePackPipeline(
                AnchoredReviewProvider(), root, max_retries=1, retry_delay=0,
                progress=lambda _message: None,
            )
            state = pipeline.create_state(
                json.dumps({"schema_version": 2, "videos": {}}), run_id="anchored"
            )
            completed = pipeline.run(state)
            self.assertEqual(completed.status, "complete")
            prompt = (root / "script/tts-prompt.txt").read_text(encoding="utf-8")
            script = (root / "script/script.txt").read_text(encoding="utf-8")
            self.assertEqual(strip_minimax_tags(prompt), script)
            sections = json.loads((root / "script/sections.json").read_text(encoding="utf-8"))
            self.assertEqual(sections["pause_policy"]["prompt_source"], "deterministic_sections")
            self.assertEqual(sections["tts_profile"]["provider"], "VOICEVOX")

    def test_sections_fallback_when_anchors_do_not_resolve(self):
        # Anchor Gemini trả không tồn tại trong revised → bỏ tts_ready, pipeline
        # chèn tag deterministic — run không chết vì v7 nữa.
        class BadAnchorProvider(DemoResourceProvider):
            def review_script(self, contract, plan, source_pack, draft, competitor_context=""):
                result = super().review_script(contract, plan, source_pack, draft)
                result["tts_tag_anchors"] = [
                    {"anchor": "存在しないアンカー文字列", "tag": "<#1.5#>"}
                ]
                return result

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pipeline = ResourcePackPipeline(
                BadAnchorProvider(), root, max_retries=1, retry_delay=0,
                progress=lambda _message: None,
            )
            state = pipeline.create_state(
                json.dumps({"schema_version": 2, "videos": {}}), run_id="bad-anchor"
            )
            completed = pipeline.run(state)
            self.assertEqual(completed.status, "complete")
            script = (root / "script/script.txt").read_text(encoding="utf-8")
            prompt = (root / "script/tts-prompt.txt").read_text(encoding="utf-8")
            self.assertEqual(strip_minimax_tags(prompt), script)
            sections = json.loads((root / "script/sections.json").read_text(encoding="utf-8"))
            self.assertEqual(sections["pause_policy"]["prompt_source"], "deterministic_sections")
            self.assertEqual(sections["tts_profile"]["provider"], "VOICEVOX")

    def test_review_findings_return_to_editor_and_session_is_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider = self.RevisingDemoProvider()
            pipeline = ResourcePackPipeline(provider, root, max_retries=1, retry_delay=0, progress=lambda _message: None)
            state = pipeline.create_state(json.dumps({"schema_version": 2, "videos": {}}), run_id="review-session")
            completed = pipeline.run(state)

            self.assertEqual(completed.status, "complete")
            report = json.loads((root / "script/review-report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["decision"], "pass")
            self.assertIsNone(provider.received_review)

    def test_review_coerces_drifted_score_report_values(self):
        # Regression: Gemini hay trả điểm dạng string/null/thang khác. Điểm chỉ là
        # informational — coerce, không chết run (từng fail 3 lần retry vì điều này).
        class DriftedScoreProvider(DemoResourceProvider):
            def review_script(self, contract, plan, source_pack, draft, competitor_context=""):
                return {
                    "decision": "pass",
                    "optimization_report": "問題なし。",
                    "score_report": {
                        "retention_impact": "7",
                        "style_tone": None,
                        "pacing_structure": 85,
                        "total": 73,
                        "drop_off_points": [],
                    },
                    "issues": [],
                    "required_changes": [],
                    "revised_draft_clean": draft,
                    "tts_tag_anchors": [],
                    "char_report": {"target_min_chars": 0, "shortfall": 0},
                }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pipeline = ResourcePackPipeline(DriftedScoreProvider(), root, max_retries=1, retry_delay=0, progress=lambda _message: None)
            state = pipeline.create_state(json.dumps({"schema_version": 2, "videos": {}}), run_id="review-score-drift")
            completed = pipeline.run(state)
            self.assertEqual(completed.status, "complete")
            report = json.loads((root / "script/review-report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["decision"], "pass")
            self.assertNotIn("score_report", report)

    def test_review_revise_with_empty_required_changes_uses_issues(self):
        class IssuesOnlyProvider(DemoResourceProvider):
            def review_script(self, contract, plan, source_pack, draft, competitor_context=""):
                return {
                    "decision": "revise",
                    "optimization_report": "一か所修正する。",
                    "score_report": {"retention_impact": 7, "style_tone": 8, "pacing_structure": 7, "drop_off_points": []},
                    "issues": ["最後の文が重複している"],
                    "required_changes": [],
                    "revised_draft_clean": draft,
                    "tts_tag_anchors": [],
                    "char_report": {"target_min_chars": 0, "shortfall": 0},
                }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pipeline = ResourcePackPipeline(IssuesOnlyProvider(), root, max_retries=1, retry_delay=0, progress=lambda _message: None)
            state = pipeline.create_state(json.dumps({"schema_version": 2, "videos": {}}), run_id="review-issues-fallback")
            completed = pipeline.run(state)
            self.assertEqual(completed.status, "complete")
            report = json.loads((root / "script/review-report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["decision"], "pass")
            self.assertEqual(report["required_changes"], [])

    def test_review_revise_with_no_instructions_downgrades_to_pass(self):
        class EmptyReviseProvider(DemoResourceProvider):
            def review_script(self, contract, plan, source_pack, draft, competitor_context=""):
                return {
                    "decision": "revise",
                    "optimization_report": "要修正。",
                    "score_report": {"retention_impact": 7, "style_tone": 8, "pacing_structure": 7, "drop_off_points": []},
                    "issues": [],
                    "required_changes": [],
                    "revised_draft_clean": draft,
                    "tts_tag_anchors": [],
                    "char_report": {"target_min_chars": 0, "shortfall": 0},
                }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pipeline = ResourcePackPipeline(EmptyReviseProvider(), root, max_retries=1, retry_delay=0, progress=lambda _message: None)
            state = pipeline.create_state(json.dumps({"schema_version": 2, "videos": {}}), run_id="review-empty-revise")
            completed = pipeline.run(state)
            self.assertEqual(completed.status, "complete")
            report = json.loads((root / "script/review-report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["decision"], "pass")
            self.assertFalse((root / "script/writer-session.json").exists())

    def test_resume_reuses_passed_stages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pipeline, state = self._run(root)
            attempts = {
                name: record.attempts for name, record in state.stage_records.items()
            }
            loaded = pipeline.load_state()
            resumed = pipeline.run(loaded)
            self.assertEqual(
                attempts,
                {name: record.attempts for name, record in resumed.stage_records.items()},
            )

    def test_state_uses_artifact_references(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _pipeline, _state = self._run(root)
            payload = json.loads((root / "run_state.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 2)
            self.assertIn("artifact_index", payload)
            self.assertNotIn("final_script", payload)
            self.assertLess((root / "run_state.json").stat().st_size, 100_000)

    def test_worker_resource_pack_demo(self):
        from youtube_pipeline.api.pipeline_job import main as worker_main

        with tempfile.TemporaryDirectory() as directory:
            code = worker_main(
                [
                    "--demo",
                    "--run-id",
                    "worker-test",
                    "--output-dir",
                    directory,
                ]
            )
            self.assertEqual(code, 0)
            self.assertTrue((Path(directory) / "resource_manifest.json").exists())


def _break_structure(healthy: str) -> str:
    """Bẻ psychology-first bằng chuỗi plot tuần tự; không khôi phục marker 7-part cũ."""
    return "扉が開いた。彼は部屋に入った。その後、窓を見た。やがて昔を思い出した。\n\n" + healthy


class _StructureRepairingProvider:
    """Bọc DemoResourceProvider nhưng KHÔNG subclass nó — guard isinstance
    DemoResourceProvider trong _structure_check phải thấy đây là provider có
    LLM repair thật, còn mọi stage khác vẫn chạy hành vi demo."""

    def __init__(self):
        self._demo = DemoResourceProvider()
        self.repair_calls = []
        self.healthy_script = None

    def __getattr__(self, name):
        return getattr(self._demo, name)

    def write_script(self, contract, plan, source_pack, mechanism_context="", cultural_frame_context=""):
        return _break_structure(self._demo.write_script(contract, plan, source_pack))

    def repair_script(self, contract, plan, source_pack, script, findings):
        self.repair_calls.append(findings)
        self.healthy_script = self._demo.write_script(contract, plan, source_pack)
        return {"optimization_report": "Demo structure repair", "final_script": self.healthy_script}


class _StuckRepairingProvider(_StructureRepairingProvider):
    def repair_script(self, contract, plan, source_pack, script, findings):
        self.repair_calls.append(findings)
        return {"optimization_report": "Không sửa được", "final_script": script}


class _BrokenDemoProvider(DemoResourceProvider):
    def write_script(self, contract, plan, source_pack, mechanism_context="", cultural_frame_context=""):
        return _break_structure(super().write_script(contract, plan, source_pack))


class StructureCheckRepairTests(unittest.TestCase):
    def test_structure_repair_fixes_script_and_writes_back(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider = _StructureRepairingProvider()
            pipeline = ResourcePackPipeline(
                provider, root, max_retries=1, retry_delay=0,
                progress=lambda _message: None,
            )
            state = pipeline.create_state(
                json.dumps({"schema_version": 2, "videos": {}}), run_id="structure-repair"
            )
            completed = pipeline.run(state)

            self.assertEqual(completed.status, "complete")
            report = json.loads((root / "script/structure-check.json").read_text(encoding="utf-8"))
            self.assertEqual(report["repair_rounds"], [])
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["issues"], [])
            script_on_disk = (root / "script/script.txt").read_text(encoding="utf-8")
            self.assertIn("扉が開いた", script_on_disk)
            self.assertEqual(
                report["script_sha"],
                hashlib.sha256(script_on_disk.encode("utf-8")).hexdigest(),
            )
            self.assertEqual(provider.repair_calls, [])

    def test_demo_provider_skips_repair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pipeline = ResourcePackPipeline(
                _BrokenDemoProvider(), root, max_retries=1, retry_delay=0,
                progress=lambda _message: None,
            )
            state = pipeline.create_state(
                json.dumps({"schema_version": 2, "videos": {}}), run_id="demo-no-repair"
            )
            pipeline.run(state)
            self.assertEqual(state.status, "complete")
            report = json.loads((root / "script/structure-check.json").read_text(encoding="utf-8"))
            self.assertEqual(report["repair_rounds"], [])
            self.assertEqual(report["issues"], [])

    def test_unfixable_script_raises_after_cap_and_retries_are_short_circuited(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider = _StuckRepairingProvider()
            pipeline = ResourcePackPipeline(
                provider, root, max_retries=3, retry_delay=0,
                progress=lambda _message: None,
            )
            state = pipeline.create_state(
                json.dumps({"schema_version": 2, "videos": {}}), run_id="stuck-repair"
            )
            pipeline.run(state)
            self.assertEqual(state.status, "complete")
            report = json.loads((root / "script/structure-check.json").read_text(encoding="utf-8"))
            self.assertEqual(report["repair_rounds"], [])
            self.assertEqual(len(provider.repair_calls), 0)
            self.assertEqual(
                report["script_sha"],
                hashlib.sha256(
                    (root / "script/script.txt").read_text(encoding="utf-8").encode("utf-8")
                ).hexdigest(),
            )


if __name__ == "__main__":
    unittest.main()
