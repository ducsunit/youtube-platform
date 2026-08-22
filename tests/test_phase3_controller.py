from youtube_pipeline.core.engine import _classify_retry, run_with_retry
from youtube_pipeline.resource_pack.validation import audit_passes, normalize_audit_report


class ApiError(Exception):
    def __init__(self, code):
        super().__init__("provider error")
        self.code = code


def test_retry_controller_does_not_retry_configuration_errors():
    calls = []

    def operation():
        calls.append(1)
        raise ApiError(404)

    assert _classify_retry(ApiError(404)) == "provider_configuration"
    try:
        run_with_retry("image_strategy", operation, 3, 0)
    except RuntimeError as exc:
        assert "provider configuration failure" in str(exc)
    else:
        raise AssertionError("expected provider configuration failure")
    assert len(calls) == 1


def test_retry_controller_does_not_retry_wrapped_deterministic_failure():
    assert _classify_retry(RuntimeError("planning deterministic failure (no blind retry): bad hook")) == "deterministic"


def test_retry_controller_classifies_gateway_worded_timeout():
    assert _classify_retry(RuntimeError("Request timed out")) == "timeout"


def test_retry_controller_stops_on_tls_certificate_mismatch_wrapped_by_sdk():
    cause = RuntimeError("api.example.test certificate name does not match input")
    wrapper = RuntimeError("Connection error")
    wrapper.__cause__ = cause
    assert _classify_retry(wrapper) == "provider_configuration"


def test_retry_controller_marks_generic_sdk_connection_as_provider_connection():
    class APIConnectionError(Exception):
        pass

    assert _classify_retry(APIConnectionError("Connection error")) == "provider_connection"


def test_audit_contract_is_normalized_before_gate_decision():
    report = normalize_audit_report({"decision": "pass"}, "gemini")
    assert report["decision"] == "revise"
    assert report["auditor"] == "gemini"
    assert not audit_passes(report)


def test_audit_score_is_removed_and_cannot_block_a_rule_compliant_report():
    report = normalize_audit_report(
        {
            "decision": "revise",
            "overall_score": 1,
            "source_alignment": True,
            "outline_coverage": True,
            "title_alignment": True,
            "unsupported_claims": [],
            "missing_outline_points": [],
        },
        "auditor",
    )
    assert "overall_score" not in report
    assert audit_passes(report)
