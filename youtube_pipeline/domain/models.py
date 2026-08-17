from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Mapping, Optional


class ValidationError(ValueError):
    """Raised when a model response does not follow the required schema."""


def _required_text(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("Truong '%s' phai la chuoi khong rong." % key)
    return value.strip()


def _string_list(data: Mapping[str, Any], key: str) -> list:
    value = data.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValidationError("Trường '%s' phải là danh sách chuỗi." % key)
    return [item.strip() for item in value if item.strip()]


def _required_bool(data: Mapping[str, Any], key: str) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise ValidationError("Trường '%s' phải là boolean." % key)
    return value


def _claim_checks(data: Mapping[str, Any]) -> list:
    value = data.get("claim_checks")
    if not isinstance(value, list) or not value:
        raise ValidationError("claim_checks phải là danh sách không rỗng.")
    checked = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, Mapping):
            raise ValidationError("claim_checks[%d] phải là JSON object." % index)
        status = _required_text(item, "status").lower()
        if status not in ("supported", "contradiction", "unsupported"):
            raise ValidationError("Trạng thái claim_checks[%d] không hợp lệ." % index)
        source_evidence = item.get("source_evidence", "")
        if not isinstance(source_evidence, str):
            raise ValidationError("source_evidence của claim %d phải là chuỗi." % index)
        checked.append(
            {
                "claim_id": _required_text(item, "claim_id"),
                "final_claim": _required_text(item, "final_claim"),
                "source_evidence": source_evidence.strip(),
                "status": status,
                "explanation": _required_text(item, "explanation"),
            }
        )
    return checked


@dataclass(frozen=True)
class Proposal:
    suggested_title: str
    target_duration: str
    script_outline: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Proposal":
        if not isinstance(data, Mapping):
            raise ValidationError("De xuat cua Gemini phai la mot JSON object.")
        return cls(
            suggested_title=_required_text(data, "suggested_title"),
            target_duration=_required_text(data, "target_duration"),
            script_outline=_required_text(data, "script_outline"),
        )

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class ReviewResult:
    optimization_report: str
    final_script: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReviewResult":
        if not isinstance(data, Mapping):
            raise ValidationError("Ket qua review cua Gemini phai la mot JSON object.")
        return cls(
            optimization_report=_required_text(data, "optimization_report"),
            final_script=_required_text(data, "final_script"),
        )


@dataclass(frozen=True)
class AuditReport:
    auditor: str
    overall_score: int
    decision: str
    outline_coverage: bool
    title_alignment: bool
    duration_alignment: bool
    contradictions: list
    unsupported_claims: list
    missing_outline_points: list
    claim_checks: list
    summary: str

    @classmethod
    def from_dict(cls, auditor: str, data: Mapping[str, Any]) -> "AuditReport":
        if not isinstance(data, Mapping):
            raise ValidationError("Báo cáo audit phải là một JSON object.")
        score = data.get("overall_score")
        if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
            raise ValidationError("overall_score phải là số nguyên từ 0 đến 100.")
        decision = _required_text(data, "decision").lower()
        if decision not in ("pass", "revise"):
            raise ValidationError("decision chỉ được là 'pass' hoặc 'revise'.")
        return cls(
            auditor=auditor,
            overall_score=score,
            decision=decision,
            outline_coverage=_required_bool(data, "outline_coverage"),
            title_alignment=_required_bool(data, "title_alignment"),
            duration_alignment=_required_bool(data, "duration_alignment"),
            contradictions=_string_list(data, "contradictions"),
            unsupported_claims=_string_list(data, "unsupported_claims"),
            missing_outline_points=_string_list(data, "missing_outline_points"),
            claim_checks=_claim_checks(data),
            summary=_required_text(data, "summary"),
        )

    def passes(self, minimum_score: int) -> bool:
        return (
            self.decision == "pass"
            and self.overall_score >= minimum_score
            and self.outline_coverage
            and self.title_alignment
            and self.duration_alignment
            and not self.contradictions
            and not self.unsupported_claims
            and not self.missing_outline_points
            and all(item["status"] == "supported" for item in self.claim_checks)
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FlowState:
    raw_youtube_data: str
    gemini_proposal: Optional[Proposal] = None
    deepseek_draft: str = ""
    optimization_report: str = ""
    final_script: str = ""
    consistency_passed: bool = False
    consistency_audits: list = field(default_factory=list)
    revision_count: int = 0
    completed_steps: list = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.raw_youtube_data, str) or not self.raw_youtube_data.strip():
            raise ValidationError("Du lieu YouTube dau vao khong duoc de trong.")
        self.raw_youtube_data = self.raw_youtube_data.strip()
        valid_progress = (
            [],
            ["analysis"],
            ["analysis", "writing"],
            ["analysis", "writing", "review"],
            ["analysis", "writing", "review", "consistency"],
        )
        if self.completed_steps not in valid_progress:
            raise ValidationError("Thu tu completed_steps trong checkpoint khong hop le.")
        if "analysis" in self.completed_steps and self.gemini_proposal is None:
            raise ValidationError("Checkpoint da xong analysis nhung thieu proposal.")
        if "writing" in self.completed_steps and not self.deepseek_draft.strip():
            raise ValidationError("Checkpoint da xong writing nhung thieu draft.")
        if "review" in self.completed_steps and (
            not self.optimization_report.strip() or not self.final_script.strip()
        ):
            raise ValidationError("Checkpoint da xong review nhung thieu ket qua.")
        if not isinstance(self.consistency_audits, list) or not all(
            isinstance(item, dict) for item in self.consistency_audits
        ):
            raise ValidationError("consistency_audits phải là danh sách JSON object.")
        if not isinstance(self.consistency_passed, bool):
            raise ValidationError("consistency_passed phải là boolean.")
        if isinstance(self.revision_count, bool) or not isinstance(self.revision_count, int):
            raise ValidationError("revision_count phải là số nguyên.")
        if self.revision_count < 0:
            raise ValidationError("revision_count không được âm.")
        if "consistency" in self.completed_steps and not self.consistency_passed:
            raise ValidationError("Checkpoint đã xong consistency nhưng quality gate chưa pass.")
        if self.consistency_passed and not self.consistency_audits:
            raise ValidationError("Quality gate pass nhưng checkpoint thiếu báo cáo audit.")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw_youtube_data": self.raw_youtube_data,
            "gemini_proposal": (
                self.gemini_proposal.to_dict() if self.gemini_proposal else None
            ),
            "deepseek_draft": self.deepseek_draft,
            "optimization_report": self.optimization_report,
            "final_script": self.final_script,
            "consistency_passed": self.consistency_passed,
            "consistency_audits": list(self.consistency_audits),
            "revision_count": self.revision_count,
            "completed_steps": list(self.completed_steps),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FlowState":
        proposal_data = data.get("gemini_proposal")
        steps = data.get("completed_steps", [])
        if not isinstance(steps, list) or not all(isinstance(item, str) for item in steps):
            raise ValidationError("completed_steps phai la danh sach chuoi.")
        return cls(
            raw_youtube_data=_required_text(data, "raw_youtube_data"),
            gemini_proposal=(Proposal.from_dict(proposal_data) if proposal_data else None),
            deepseek_draft=str(data.get("deepseek_draft", "")),
            optimization_report=str(data.get("optimization_report", "")),
            final_script=str(data.get("final_script", "")),
            consistency_passed=data.get("consistency_passed", False),
            consistency_audits=data.get("consistency_audits", []),
            revision_count=data.get("revision_count", 0),
            completed_steps=steps,
        )
