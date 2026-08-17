import json
import tempfile
import unittest
from pathlib import Path

from youtube_pipeline.models import AuditReport, FlowState, Proposal, ReviewResult
from youtube_pipeline.pipeline import (
    PipelineError,
    YouTubePipeline,
    script_metrics,
    write_outputs,
)


class FakeProvider:
    def __init__(self):
        self.calls = []

    def analyze(self, raw_data):
        self.calls.append("analysis")
        return Proposal("A title", "2 seconds", "0-1s hook; 1-2s body")

    def write(self, proposal):
        self.calls.append("writing")
        return "One two three four five"

    def review(self, proposal, draft):
        self.calls.append("review")
        return ReviewResult("Tightened hook", draft + " final")

    @staticmethod
    def passing_audit(auditor):
        return AuditReport(
            auditor=auditor,
            overall_score=100,
            decision="pass",
            outline_coverage=True,
            title_alignment=True,
            duration_alignment=True,
            contradictions=[],
            unsupported_claims=[],
            missing_outline_points=[],
            claim_checks=[
                {
                    "claim_id": "C001",
                    "final_claim": "A claim",
                    "source_evidence": "channel facts",
                    "status": "supported",
                    "explanation": "Matched",
                }
            ],
            summary="Consistent",
        )

    def audit_deepseek(self, raw_data, proposal, draft, final_script):
        self.calls.append("audit_deepseek")
        return self.passing_audit("deepseek")

    def audit_gemini(self, raw_data, proposal, draft, final_script):
        self.calls.append("audit_gemini")
        return self.passing_audit("gemini")

    def repair(self, raw_data, proposal, draft, final_script, findings):
        self.calls.append("repair")
        return ReviewResult("Repaired consistency", final_script)


class FlakyProvider(FakeProvider):
    def __init__(self):
        super().__init__()
        self.failures = 0

    def analyze(self, raw_data):
        self.failures += 1
        if self.failures == 1:
            raise TimeoutError("temporary")
        return super().analyze(raw_data)


class RevisingProvider(FakeProvider):
    def __init__(self):
        super().__init__()
        self.audit_round = 0

    def audit_deepseek(self, raw_data, proposal, draft, final_script):
        self.calls.append("audit_deepseek")
        self.audit_round += 1
        if self.audit_round == 1:
            return AuditReport(
                auditor="deepseek",
                overall_score=70,
                decision="revise",
                outline_coverage=True,
                title_alignment=True,
                duration_alignment=True,
                contradictions=["Conflicting year"],
                unsupported_claims=[],
                missing_outline_points=[],
                claim_checks=[
                    {
                        "claim_id": "C001",
                        "final_claim": "Wrong year",
                        "source_evidence": "Different year",
                        "status": "contradiction",
                        "explanation": "Year changed",
                    }
                ],
                summary="Needs repair",
            )
        return self.passing_audit("deepseek")

    def audit_gemini(self, raw_data, proposal, draft, final_script):
        self.calls.append("audit_gemini")
        if self.audit_round == 1:
            return AuditReport(
                auditor="gemini",
                overall_score=75,
                decision="revise",
                outline_coverage=True,
                title_alignment=True,
                duration_alignment=True,
                contradictions=["Conflicting year"],
                unsupported_claims=[],
                missing_outline_points=[],
                claim_checks=[
                    {
                        "claim_id": "C001",
                        "final_claim": "Wrong year",
                        "source_evidence": "Different year",
                        "status": "contradiction",
                        "explanation": "Year changed",
                    }
                ],
                summary="Needs repair",
            )
        return self.passing_audit("gemini")


class RejectingProvider(FakeProvider):
    @staticmethod
    def failed_audit(auditor):
        return AuditReport(
            auditor=auditor,
            overall_score=50,
            decision="revise",
            outline_coverage=False,
            title_alignment=True,
            duration_alignment=True,
            contradictions=["Unresolved conflict"],
            unsupported_claims=[],
            missing_outline_points=["Missing ending"],
            claim_checks=[
                {
                    "claim_id": "C001",
                    "final_claim": "Unresolved claim",
                    "source_evidence": "Conflicting source",
                    "status": "contradiction",
                    "explanation": "Still conflicts",
                }
            ],
            summary="Rejected",
        )

    def audit_deepseek(self, raw_data, proposal, draft, final_script):
        self.calls.append("audit_deepseek")
        return self.failed_audit("deepseek")

    def audit_gemini(self, raw_data, proposal, draft, final_script):
        self.calls.append("audit_gemini")
        return self.failed_audit("gemini")


class PipelineTests(unittest.TestCase):
    def test_full_pipeline_checkpoints_and_writes_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider = FakeProvider()
            pipeline = YouTubePipeline(
                provider, root / "state.json", retry_delay=0
            )
            state = pipeline.run(FlowState("channel facts"))

            self.assertEqual(
                provider.calls,
                ["analysis", "writing", "review", "audit_deepseek", "audit_gemini"],
            )
            self.assertEqual(
                state.completed_steps,
                ["analysis", "writing", "review", "consistency"],
            )
            self.assertTrue(state.consistency_passed)
            saved = json.loads((root / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["final_script"], "One two three four five final")

            script_path, result_path = write_outputs(state, root / "output")
            self.assertTrue(script_path.exists())
            result = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(result["metrics"]["word_count"], 6)

    def test_resume_skips_completed_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = FlowState(
                "channel facts",
                gemini_proposal=Proposal("Saved", "8m", "outline"),
                completed_steps=["analysis"],
            )
            checkpoint = root / "state.json"
            checkpoint.write_text(json.dumps(state.to_dict()), encoding="utf-8")
            loaded = YouTubePipeline.load_checkpoint(checkpoint)
            provider = FakeProvider()
            YouTubePipeline(provider, checkpoint, retry_delay=0).run(loaded)
            self.assertEqual(
                provider.calls,
                ["writing", "review", "audit_deepseek", "audit_gemini"],
            )

    def test_transient_failure_is_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = FlakyProvider()
            YouTubePipeline(
                provider,
                Path(directory) / "state.json",
                max_retries=2,
                retry_delay=0,
            ).run(FlowState("channel facts"))
            self.assertEqual(provider.failures, 2)

    def test_failed_audit_is_repaired_then_audited_again(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = RevisingProvider()
            state = YouTubePipeline(
                provider,
                Path(directory) / "state.json",
                retry_delay=0,
                consistency_max_rounds=2,
            ).run(FlowState("channel facts"))
            self.assertTrue(state.consistency_passed)
            self.assertEqual(state.revision_count, 1)
            self.assertEqual(len(state.consistency_audits), 2)
            self.assertEqual(provider.calls.count("repair"), 1)

    def test_pipeline_fails_closed_when_audits_never_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = FlowState("channel facts")
            with self.assertRaises(PipelineError):
                YouTubePipeline(
                    RejectingProvider(),
                    root / "state.json",
                    retry_delay=0,
                    consistency_max_rounds=2,
                ).run(state)
            self.assertFalse(state.consistency_passed)
            with self.assertRaises(PipelineError):
                write_outputs(state, root / "output")
            self.assertFalse((root / "output" / "final_script.txt").exists())

    def test_script_metrics(self):
        self.assertEqual(script_metrics("one two three", 60)["estimated_speaking_seconds"], 3)


if __name__ == "__main__":
    unittest.main()
