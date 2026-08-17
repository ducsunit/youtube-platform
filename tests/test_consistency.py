import unittest

from youtube_pipeline.consistency import (
    deterministic_duration_check,
    evaluate_quality_gate,
    target_duration_seconds,
)
from youtube_pipeline.models import AuditReport


def audit(auditor, decision="pass", contradictions=None):
    return AuditReport(
        auditor=auditor,
        overall_score=95,
        decision=decision,
        outline_coverage=True,
        title_alignment=True,
        duration_alignment=True,
        contradictions=contradictions or [],
        unsupported_claims=[],
        missing_outline_points=[],
        claim_checks=[
            {
                "claim_id": "C001",
                "final_claim": "Claim",
                "source_evidence": "Evidence",
                "status": "supported",
                "explanation": "Matched",
            }
        ],
        summary="Checked",
    )


class ConsistencyTests(unittest.TestCase):
    def test_parses_vietnamese_and_english_duration(self):
        self.assertEqual(target_duration_seconds("Video dài 8 phút"), 480)
        self.assertEqual(target_duration_seconds("Shorts 60 seconds"), 60)

    def test_duration_check_fails_outside_tolerance(self):
        result = deterministic_duration_check("60 giây", "một hai ba", 0.25, 60)
        self.assertFalse(result["passed"])

    def test_gate_requires_both_auditors_and_duration(self):
        result = evaluate_quality_gate(
            audit("deepseek"),
            audit("gemini", contradictions=["Conflict"]),
            {"passed": True},
            90,
        )
        self.assertFalse(result["passed"])


if __name__ == "__main__":
    unittest.main()
