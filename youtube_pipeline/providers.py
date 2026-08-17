from __future__ import annotations

import json
import logging
import random
import re
from typing import Any, Dict, Mapping, Protocol

from .config import Settings
from .domain.models import AuditReport, Proposal, ReviewResult, ValidationError
from .infrastructure.model_trace import (
    trace_parsed_response,
    trace_raw_response,
    trace_request,
)
from .prompts import (
    ANALYSIS_SYSTEM,
    AUDIT_SYSTEM,
    REPAIR_SYSTEM,
    REVIEW_SYSTEM,
    WRITER_SYSTEM,
    analysis_prompt,
    audit_prompt,
    repair_prompt,
    review_prompt,
    writer_prompt,
)

logger = logging.getLogger(__name__)


class ContentProvider(Protocol):
    def analyze(self, raw_data: str) -> Proposal:
        ...

    def write(self, proposal: Proposal) -> str:
        ...

    def review(self, proposal: Proposal, draft: str) -> ReviewResult:
        ...

    def audit_deepseek(
        self, raw_data: str, proposal: Proposal, draft: str, final_script: str
    ) -> AuditReport:
        ...

    def audit_gemini(
        self, raw_data: str, proposal: Proposal, draft: str, final_script: str
    ) -> AuditReport:
        ...

    def repair(
        self,
        raw_data: str,
        proposal: Proposal,
        draft: str,
        final_script: str,
        findings: Mapping[str, Any],
    ) -> ReviewResult:
        ...


def _sanitize_control_chars(candidate: str) -> str:
    """Escape control character raw nằm TRONG JSON string (model hay trả newline/tab thật).

    Control char ngoài JSON (whitespace giữa các token) giữ nguyên — đó là
    whitespace hợp lệ; chỉ ký tự điều khiển bên trong dấu ngoặc kép mới khiến
    json.loads ném "Invalid control character".
    """
    out: list[str] = []
    in_string = False
    escaped = False
    for ch in candidate:
        if escaped:
            out.append(ch)
            escaped = False
            continue
        if in_string and ch == "\\":
            out.append(ch)
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            out.append(ch)
            continue
        if in_string and ord(ch) < 0x20:
            out.append("\\u%04x" % ord(ch))
            continue
        out.append(ch)
    return "".join(out)


def parse_json_object(text: str) -> Dict[str, Any]:
    if not isinstance(text, str) or not text.strip():
        raise ValidationError("Model tra ve noi dung rong.")
    candidate = text.strip()
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, flags=re.DOTALL)
    if fence:
        candidate = fence.group(1).strip()
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        # Lần 2: JSON hợp lệ nhưng model kèm text thừa phía sau (chú thích, JSON
        # thứ hai, markdown dở) — raw_decode lấy object đầu tiên, bỏ phần dư.
        try:
            value, _ = json.JSONDecoder().raw_decode(candidate)
        except json.JSONDecodeError:
            # Lần 3: control character thật bên trong string — escape rồi thử lại.
            fixed = _sanitize_control_chars(candidate)
            try:
                value, _ = json.JSONDecoder().raw_decode(fixed)
            except json.JSONDecodeError as exc:
                raise ValidationError(
                    "Model khong tra ve JSON hop le: %s" % exc.msg
                ) from exc
    if not isinstance(value, dict):
        raise ValidationError("Model phai tra ve mot JSON object.")
    return value


class AIContentProvider:
    """Production adapter for Gemini and DeepSeek's OpenAI-compatible API."""

    def __init__(self, settings: Settings) -> None:
        try:
            from google import genai
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "Thieu SDK. Hay chay: python3 -m pip install -e ."
            ) from exc

        self._settings = settings
        self._gemini = genai.Client(api_key=settings.gemini_api_key)
        self._deepseek = OpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
        )
        logger.info(
            "Đã khởi tạo AI provider | analysis_model=%s | writer_model=%s | "
            "review_model=%s | deepseek_audit_model=%s | gemini_audit_model=%s | "
            "deepseek_base_url=%s",
            settings.gemini_analysis_model,
            settings.deepseek_model,
            settings.gemini_review_model,
            settings.deepseek_audit_model,
            settings.gemini_audit_model,
            settings.deepseek_base_url,
        )

    def _gemini_generate(self, model: str, contents: str, config: Any, label: str) -> Any:
        """Gọi Gemini với retry khi API quá tải (503 / UNAVAILABLE / high demand).

        Lỗi quá tải là tạm thời — ngủ 15–30s rồi thử lại, tối đa 3 lần. Mọi lỗi
        khác (4xx, xác thực, mạng thật) raise ngay để không che giấu lỗi.
        """
        import time

        from google.genai import errors as genai_errors

        max_attempts = 3
        base_delay = 15.0
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                return self._gemini.models.generate_content(
                    model=model, contents=contents, config=config
                )
            except genai_errors.APIError as exc:
                last_error = exc
                message = str(exc).lower()
                overloaded = (
                    getattr(exc, "code", None) == 503
                    or "unavailable" in message
                    or "high demand" in message
                )
                if not overloaded or attempt == max_attempts:
                    raise
                delay = base_delay * attempt + random.uniform(0, 5)
                logger.warning(
                    "Gemini quá tải (503) — thử lại lần %d/%d sau %.0fs | stage=%s",
                    attempt + 1,
                    max_attempts,
                    delay,
                    label,
                )
                time.sleep(delay)
        assert last_error is not None
        raise last_error

    @property
    def max_retries(self) -> int:
        return self._settings.max_retries

    @property
    def consistency_min_score(self) -> int:
        return self._settings.consistency_min_score

    @property
    def consistency_max_rounds(self) -> int:
        return self._settings.consistency_max_rounds

    @property
    def duration_tolerance(self) -> float:
        return self._settings.duration_tolerance

    def analyze(self, raw_data: str) -> Proposal:
        from google.genai import types

        user_prompt = analysis_prompt(raw_data)
        logger.info("Bắt đầu gọi Gemini phân tích | model=%s", self._settings.gemini_analysis_model)
        logger.debug("Gemini analysis system instruction:\n%s", ANALYSIS_SYSTEM)
        logger.debug("Gemini analysis user prompt:\n%s", user_prompt)
        trace_request(
            1,
            "Gemini Analysis",
            "Gemini",
            self._settings.gemini_analysis_model,
            ANALYSIS_SYSTEM,
            user_prompt,
            0.4,
        )
        response = self._gemini_generate(
            model=self._settings.gemini_analysis_model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=ANALYSIS_SYSTEM,
                response_mime_type="application/json",
                temperature=0.4,
                thinking_config=types.ThinkingConfig(thinking_level="high"),
            ),
            label="Gemini Analysis",
        )
        logger.debug("Gemini analysis raw response:\n%s", response.text)
        trace_raw_response(1, "Gemini Analysis", response.text)
        proposal = Proposal.from_dict(parse_json_object(response.text))
        logger.info("Gemini phân tích hoàn tất | title=%s", proposal.suggested_title)
        logger.debug("Gemini proposal parsed:\n%s", json.dumps(proposal.to_dict(), ensure_ascii=False, indent=2))
        trace_parsed_response(1, "Gemini Analysis", proposal.to_dict())
        return proposal

    def write(self, proposal: Proposal) -> str:
        user_prompt = writer_prompt(
            proposal.suggested_title,
            proposal.target_duration,
            proposal.script_outline,
        )
        logger.info("Bắt đầu gọi DeepSeek viết | model=%s", self._settings.deepseek_model)
        logger.debug("DeepSeek writer system prompt:\n%s", WRITER_SYSTEM)
        logger.debug("DeepSeek writer user prompt:\n%s", user_prompt)
        trace_request(
            2,
            "DeepSeek Writer",
            "DeepSeek",
            self._settings.deepseek_model,
            WRITER_SYSTEM,
            user_prompt,
            0.7,
        )
        response = self._deepseek.chat.completions.create(
            model=self._settings.deepseek_model,
            messages=[
                {"role": "system", "content": WRITER_SYSTEM},
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
            temperature=0.7,
        )
        content = response.choices[0].message.content
        logger.debug("DeepSeek writer raw response:\n%s", content)
        trace_raw_response(2, "DeepSeek Writer", content)
        if not isinstance(content, str) or not content.strip():
            raise ValidationError("DeepSeek tra ve ban nhap rong.")
        logger.info("DeepSeek viết hoàn tất | characters=%d", len(content.strip()))
        trace_parsed_response(2, "DeepSeek Writer", content.strip())
        return content.strip()

    def review(self, proposal: Proposal, draft: str) -> ReviewResult:
        from google.genai import types

        user_prompt = review_prompt(
            proposal.suggested_title,
            proposal.target_duration,
            proposal.script_outline,
            draft,
        )
        logger.info("Bắt đầu gọi Gemini review | model=%s", self._settings.gemini_review_model)
        logger.debug("Gemini review system instruction:\n%s", REVIEW_SYSTEM)
        logger.debug("Gemini review user prompt:\n%s", user_prompt)
        trace_request(
            3,
            "Gemini Reviewer",
            "Gemini",
            self._settings.gemini_review_model,
            REVIEW_SYSTEM,
            user_prompt,
            0.2,
        )
        response = self._gemini_generate(
            model=self._settings.gemini_review_model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=REVIEW_SYSTEM,
                response_mime_type="application/json",
                temperature=0.2,
                thinking_config=types.ThinkingConfig(thinking_level="high"),
            ),
            label="Gemini Review",
        )
        logger.debug("Gemini review raw response:\n%s", response.text)
        trace_raw_response(3, "Gemini Reviewer", response.text)
        result = ReviewResult.from_dict(parse_json_object(response.text))
        logger.info("Gemini review hoàn tất | final_characters=%d", len(result.final_script))
        logger.debug("Optimization report:\n%s", result.optimization_report)
        logger.debug("Final script:\n%s", result.final_script)
        trace_parsed_response(
            3,
            "Gemini Reviewer",
            {
                "optimization_report": result.optimization_report,
                "final_script": result.final_script,
            },
        )
        return result

    def audit_deepseek(
        self, raw_data: str, proposal: Proposal, draft: str, final_script: str
    ) -> AuditReport:
        user_prompt = audit_prompt(
            "DeepSeek Auditor",
            raw_data,
            proposal.suggested_title,
            proposal.target_duration,
            proposal.script_outline,
            draft,
            final_script,
        )
        trace_request(
            "4A",
            "DeepSeek Consistency Auditor",
            "DeepSeek",
            self._settings.deepseek_audit_model,
            AUDIT_SYSTEM,
            user_prompt,
            0.0,
        )
        logger.info(
            "Bắt đầu DeepSeek consistency audit | model=%s",
            self._settings.deepseek_audit_model,
        )
        response = self._deepseek.chat.completions.create(
            model=self._settings.deepseek_audit_model,
            messages=[
                {"role": "system", "content": AUDIT_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
        )
        content = response.choices[0].message.content
        trace_raw_response("4A", "DeepSeek Consistency Auditor", content)
        report = AuditReport.from_dict(
            "deepseek", parse_json_object(content if content else "")
        )
        trace_parsed_response("4A", "DeepSeek Consistency Auditor", report.to_dict())
        logger.info(
            "DeepSeek audit hoàn tất | decision=%s | score=%d",
            report.decision,
            report.overall_score,
        )
        return report

    def audit_gemini(
        self, raw_data: str, proposal: Proposal, draft: str, final_script: str
    ) -> AuditReport:
        from google.genai import types

        user_prompt = audit_prompt(
            "Gemini Auditor",
            raw_data,
            proposal.suggested_title,
            proposal.target_duration,
            proposal.script_outline,
            draft,
            final_script,
        )
        trace_request(
            "4B",
            "Gemini Consistency Auditor",
            "Gemini",
            self._settings.gemini_audit_model,
            AUDIT_SYSTEM,
            user_prompt,
            0.0,
        )
        logger.info(
            "Bắt đầu Gemini consistency audit | model=%s",
            self._settings.gemini_audit_model,
        )
        response = self._gemini_generate(
            model=self._settings.gemini_audit_model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=AUDIT_SYSTEM,
                response_mime_type="application/json",
                temperature=0.0,
                thinking_config=types.ThinkingConfig(thinking_level="high"),
            ),
            label="Gemini Consistency Audit",
        )
        trace_raw_response("4B", "Gemini Consistency Auditor", response.text)
        report = AuditReport.from_dict(
            "gemini", parse_json_object(response.text)
        )
        trace_parsed_response("4B", "Gemini Consistency Auditor", report.to_dict())
        logger.info(
            "Gemini audit hoàn tất | decision=%s | score=%d",
            report.decision,
            report.overall_score,
        )
        return report

    def repair(
        self,
        raw_data: str,
        proposal: Proposal,
        draft: str,
        final_script: str,
        findings: Mapping[str, Any],
    ) -> ReviewResult:
        from google.genai import types

        findings_json = json.dumps(findings, ensure_ascii=False, indent=2)
        user_prompt = repair_prompt(
            raw_data,
            proposal.suggested_title,
            proposal.target_duration,
            proposal.script_outline,
            draft,
            final_script,
            findings_json,
        )
        trace_request(
            "4R",
            "Gemini Consistency Repair",
            "Gemini",
            self._settings.gemini_review_model,
            REPAIR_SYSTEM,
            user_prompt,
            0.2,
        )
        response = self._gemini_generate(
            model=self._settings.gemini_review_model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=REPAIR_SYSTEM,
                response_mime_type="application/json",
                temperature=0.2,
                thinking_config=types.ThinkingConfig(thinking_level="high"),
            ),
            label="Gemini Consistency Repair",
        )
        trace_raw_response("4R", "Gemini Consistency Repair", response.text)
        result = ReviewResult.from_dict(parse_json_object(response.text))
        trace_parsed_response(
            "4R",
            "Gemini Consistency Repair",
            {
                "optimization_report": result.optimization_report,
                "final_script": result.final_script,
            },
        )
        return result


class DemoContentProvider:
    """Deterministic provider for local evaluation without API credentials."""

    def analyze(self, raw_data: str) -> Proposal:
        logger.debug("Demo analysis input:\n%s", raw_data)
        user_prompt = analysis_prompt(raw_data)
        trace_request(1, "Gemini Analysis (Demo)", "Demo", "demo-gemini-analysis", ANALYSIS_SYSTEM, user_prompt, 0.4)
        proposal = Proposal(
            suggested_title="Canh cua bi mat vua duoc mo lai sau 3.000 nam",
            target_duration="Video ngắn 60 giây",
            script_outline=(
                "0-5s: Hook; 5-15s: bối cảnh; 15-45s: ba bằng chứng; "
                "45-55s: giải mã; 55-60s: kết luận và câu hỏi mở."
            ),
        )
        trace_raw_response(1, "Gemini Analysis (Demo)", proposal.to_dict())
        trace_parsed_response(1, "Gemini Analysis (Demo)", proposal.to_dict())
        return proposal

    def write(self, proposal: Proposal) -> str:
        logger.debug("Demo writer proposal:\n%s", json.dumps(proposal.to_dict(), ensure_ascii=False, indent=2))
        user_prompt = writer_prompt(
            proposal.suggested_title,
            proposal.target_duration,
            proposal.script_outline,
        )
        trace_request(2, "DeepSeek Writer (Demo)", "Demo", "demo-deepseek-writer", WRITER_SYSTEM, user_prompt, 0.7)
        draft = (
            "[0-15s] Thu nam im sau buc tuong nay suot 3.000 nam khong phai vang. "
            "No la mot manh bang chung co the viet lai cau chuyen ma chung ta van tin.\n\n"
            "[15-90s] Cuoc khai quat bat dau tu mot dau vet rat nho. Cac nha khao co "
            "khong tim kho bau; ho tim loi giai cho mot khoang trong trong lich su.\n\n"
            "[90-360s] Dau tien la vi tri. Tiep theo la ky hieu tren be mat. Cuoi cung, "
            "ket qua phan tich vat lieu da noi hai dau vet ay thanh mot cau chuyen.\n\n"
            "[360-450s] Phat hien khong chung minh moi gia thuyet, nhung no loai bo "
            "cach giai thich pho bien nhat va mo ra mot huong nghien cuu moi.\n\n"
            "[450-480s] Canh cua da mo, nhung cau hoi lon hon van con do: ai da dong no?"
        )
        trace_raw_response(2, "DeepSeek Writer (Demo)", draft)
        trace_parsed_response(2, "DeepSeek Writer (Demo)", draft)
        return draft

    def review(self, proposal: Proposal, draft: str) -> ReviewResult:
        logger.debug("Demo review draft:\n%s", draft)
        user_prompt = review_prompt(
            proposal.suggested_title,
            proposal.target_duration,
            proposal.script_outline,
            draft,
        )
        trace_request(3, "Gemini Reviewer (Demo)", "Demo", "demo-gemini-reviewer", REVIEW_SYSTEM, user_prompt, 0.2)
        result = ReviewResult(
            optimization_report=(
                "Rut gon hook, loai bo cau chuyen doan lap va dua loi hua cua tieu de "
                "tro lai phan ket."
            ),
            final_script=draft.replace(
                "Thu nam im sau buc tuong nay suot 3.000 nam khong phai vang.",
                "Sau buc tuong 3.000 nam tuoi khong co vang.",
            ),
        )
        payload = {
            "optimization_report": result.optimization_report,
            "final_script": result.final_script,
        }
        trace_raw_response(3, "Gemini Reviewer (Demo)", payload)
        trace_parsed_response(3, "Gemini Reviewer (Demo)", payload)
        return result

    @staticmethod
    def _passing_audit(auditor: str) -> AuditReport:
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
                    "final_claim": "Cánh cửa đã được mở sau 3.000 năm.",
                    "source_evidence": "Proposal và bản nháp demo cùng mô tả sự kiện này.",
                    "status": "supported",
                    "explanation": "Claim không thay đổi giữa các bước demo.",
                }
            ],
            summary="Dữ liệu demo nhất quán với proposal, bản nháp và bản final.",
        )

    def audit_deepseek(
        self, raw_data: str, proposal: Proposal, draft: str, final_script: str
    ) -> AuditReport:
        prompt = audit_prompt(
            "DeepSeek Auditor", raw_data, proposal.suggested_title,
            proposal.target_duration, proposal.script_outline, draft, final_script
        )
        trace_request("4A", "DeepSeek Consistency Auditor (Demo)", "Demo", "demo-deepseek-auditor", AUDIT_SYSTEM, prompt, 0.0)
        report = self._passing_audit("deepseek")
        trace_raw_response("4A", "DeepSeek Consistency Auditor (Demo)", report.to_dict())
        trace_parsed_response("4A", "DeepSeek Consistency Auditor (Demo)", report.to_dict())
        return report

    def audit_gemini(
        self, raw_data: str, proposal: Proposal, draft: str, final_script: str
    ) -> AuditReport:
        prompt = audit_prompt(
            "Gemini Auditor", raw_data, proposal.suggested_title,
            proposal.target_duration, proposal.script_outline, draft, final_script
        )
        trace_request("4B", "Gemini Consistency Auditor (Demo)", "Demo", "demo-gemini-auditor", AUDIT_SYSTEM, prompt, 0.0)
        report = self._passing_audit("gemini")
        trace_raw_response("4B", "Gemini Consistency Auditor (Demo)", report.to_dict())
        trace_parsed_response("4B", "Gemini Consistency Auditor (Demo)", report.to_dict())
        return report

    def repair(
        self,
        raw_data: str,
        proposal: Proposal,
        draft: str,
        final_script: str,
        findings: Mapping[str, Any],
    ) -> ReviewResult:
        return ReviewResult(
            optimization_report="Đã sửa theo báo cáo consistency demo.",
            final_script=final_script,
        )
