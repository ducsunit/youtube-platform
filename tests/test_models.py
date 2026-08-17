import unittest

from youtube_pipeline.models import (
    AuditReport,
    FlowState,
    Proposal,
    ReviewResult,
    ValidationError,
)
from youtube_pipeline.prompts import (
    ANALYSIS_SYSTEM,
    REVIEW_SYSTEM,
    WRITER_SYSTEM,
    analysis_prompt,
    review_prompt,
    writer_prompt,
)
from youtube_pipeline.providers import parse_json_object


class ModelTests(unittest.TestCase):
    def test_proposal_validates_required_fields(self):
        with self.assertRaises(ValidationError):
            Proposal.from_dict(
                {"suggested_title": "Title", "target_duration": "8 minutes"}
            )

    def test_review_rejects_blank_script(self):
        with self.assertRaises(ValidationError):
            ReviewResult.from_dict(
                {"optimization_report": "Shorter hook", "final_script": "  "}
            )

    def test_json_parser_accepts_code_fence(self):
        value = parse_json_object('```json\n{"answer": "ok"}\n```')
        self.assertEqual(value, {"answer": "ok"})

    def test_json_parser_rejects_array(self):
        with self.assertRaises(ValidationError):
            parse_json_object("[]")

    def test_json_parser_trims_trailing_text_after_object(self):
        # Model hay kèm chú thích/JSON thứ hai sau object chính (lỗi "Extra data").
        value = parse_json_object('{"answer": "ok"}\nNgoài ra: đây là giải thích thêm.')
        self.assertEqual(value, {"answer": "ok"})

    def test_json_parser_escapes_raw_control_chars_in_string(self):
        # Model trả newline/tab thật bên trong string (lỗi "Invalid control character").
        raw = '{"script": "第一段落。\n第二段落。\t続き"}'
        value = parse_json_object(raw)
        self.assertEqual(value, {"script": "第一段落。\n第二段落。\t続き"})

    def test_checkpoint_rejects_completed_step_without_artifact(self):
        with self.assertRaises(ValidationError):
            FlowState("channel facts", completed_steps=["analysis"])

    def test_all_model_prompts_use_accented_vietnamese(self):
        prompts = (
            ANALYSIS_SYSTEM,
            WRITER_SYSTEM,
            REVIEW_SYSTEM,
            analysis_prompt("Dữ liệu mẫu"),
            writer_prompt("Tiêu đề", "8 phút", "Dàn ý"),
            review_prompt("Tiêu đề", "8 phút", "Dàn ý", "Bản nháp"),
        )
        accented_terms = ("Bạn", "kịch bản", "Tiêu đề", "Dàn ý")
        combined = "\n".join(prompts)
        for term in accented_terms:
            self.assertIn(term, combined)

    def test_audit_requires_clean_report_to_pass(self):
        report = AuditReport.from_dict(
            "gemini",
            {
                "overall_score": 95,
                "decision": "pass",
                "outline_coverage": True,
                "title_alignment": True,
                "duration_alignment": True,
                "contradictions": ["Mốc năm bị đổi"],
                "unsupported_claims": [],
                "missing_outline_points": [],
                "claim_checks": [
                    {
                        "claim_id": "C001",
                        "final_claim": "Sai mốc năm",
                        "source_evidence": "Mốc năm gốc",
                        "status": "contradiction",
                        "explanation": "Hai mốc năm khác nhau",
                    }
                ],
                "summary": "Có một mâu thuẫn",
            },
        )
        self.assertFalse(report.passes(90))


if __name__ == "__main__":
    unittest.main()
