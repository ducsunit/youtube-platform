"""LEGACY — flow 7-step cũ (YouTubePipeline + FlowState), KHÔNG còn là flow chính.

Flow production hiện tại là psychology-first ResourcePackPipeline trong
`resource_pack/pipeline.py`. File này
chỉ còn giữ vì CLI entrypoint `youtube-pipeline` (`cli.py`) và re-export
trong `__init__.py` vẫn trỏ vào — nếu dùng CLI, ưu tiên chuyển sang flow mới;
đừng thêm feature mới vào đây.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable, Optional, TypeVar

from .domain.consistency import deterministic_duration_check, evaluate_quality_gate
from .core.engine import run_with_retry
from .domain.models import FlowState
from .infrastructure.model_trace import (
    trace_error,
    trace_handoff,
    trace_parsed_response,
    trace_step_skipped,
)
from .providers import ContentProvider

logger = logging.getLogger(__name__)

T = TypeVar("T")
ProgressCallback = Callable[[str], None]


class PipelineError(RuntimeError):
    """Wraps a failed pipeline step with actionable context."""


class YouTubePipeline:
    def __init__(
        self,
        provider: ContentProvider,
        checkpoint_path: Path,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        consistency_min_score: int = 90,
        consistency_max_rounds: int = 2,
        duration_tolerance: float = 0.25,
        progress: Optional[ProgressCallback] = None,
    ) -> None:
        self.provider = provider
        self.checkpoint_path = checkpoint_path
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.consistency_min_score = consistency_min_score
        self.consistency_max_rounds = consistency_max_rounds
        self.duration_tolerance = duration_tolerance
        self.progress = progress or (lambda _message: None)

    def _retry(self, step_name: str, operation: Callable[[], T]) -> T:
        def on_error(attempt: int, exc: Exception) -> None:
            trace_error("%s | lần %d/%d" % (step_name, attempt, self.max_retries), exc)

        try:
            result, _retry_metadata = run_with_retry(
                step_name,
                operation,
                self.max_retries,
                self.retry_delay,
                self.progress,
                on_error,
            )
            # The shared retry engine returns telemetry alongside the value;
            # this legacy pipeline still exposes the historical value-only API.
            return result
        except RuntimeError as exc:
            raise PipelineError(str(exc)) from exc

    def save_checkpoint(self, state: FlowState) -> None:
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.checkpoint_path.with_suffix(self.checkpoint_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(state.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.checkpoint_path)
        logger.info("Đã lưu checkpoint | path=%s", self.checkpoint_path)
        logger.debug(
            "Checkpoint state:\n%s",
            json.dumps(state.to_dict(), ensure_ascii=False, indent=2),
        )

    @staticmethod
    def load_checkpoint(path: Path) -> FlowState:
        logger.info("Đang đọc checkpoint | path=%s", path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise PipelineError("Khong doc duoc checkpoint %s: %s" % (path, exc)) from exc
        except json.JSONDecodeError as exc:
            raise PipelineError("Checkpoint khong phai JSON hop le: %s" % path) from exc
        state = FlowState.from_dict(data)
        logger.info("Đã đọc checkpoint | completed_steps=%s", state.completed_steps)
        logger.debug("Loaded checkpoint:\n%s", json.dumps(data, ensure_ascii=False, indent=2))
        return state

    def run(self, state: FlowState) -> FlowState:
        logger.info("Bắt đầu pipeline | completed_steps=%s", state.completed_steps)
        logger.debug(
            "Pipeline initial state:\n%s",
            json.dumps(state.to_dict(), ensure_ascii=False, indent=2),
        )
        if "analysis" not in state.completed_steps:
            self.progress("[1/4] Gemini đang phân tích dữ liệu kênh...")
            state.gemini_proposal = self._retry(
                "Buoc phan tich", lambda: self.provider.analyze(state.raw_youtube_data)
            )
            state.completed_steps.append("analysis")
            self.save_checkpoint(state)
        else:
            logger.info("Bỏ qua bước analysis vì đã hoàn thành")
            trace_step_skipped(1, "Gemini Analysis", "Đã có trong checkpoint")

        if state.gemini_proposal is None:
            raise PipelineError("Checkpoint thieu de xuat Gemini cho buoc viet.")

        if "writing" not in state.completed_steps:
            trace_handoff(
                "STEP 1 Gemini Analysis",
                "STEP 2 DeepSeek Writer",
                state.gemini_proposal.to_dict(),
                "Proposal của Gemini được dùng để tạo prompt viết kịch bản.",
            )
            self.progress("[2/4] DeepSeek đang viết bản nháp...")
            state.deepseek_draft = self._retry(
                "Buoc viet", lambda: self.provider.write(state.gemini_proposal)
            )
            state.completed_steps.append("writing")
            self.save_checkpoint(state)
        else:
            logger.info("Bỏ qua bước writing vì đã hoàn thành")
            trace_step_skipped(2, "DeepSeek Writer", "Đã có trong checkpoint")

        if "review" not in state.completed_steps:
            trace_handoff(
                "STEP 2 DeepSeek Writer",
                "STEP 3 Gemini Reviewer",
                {
                    "gemini_proposal": state.gemini_proposal.to_dict(),
                    "deepseek_draft": state.deepseek_draft,
                },
                "Proposal gốc và bản nháp DeepSeek được chuyển sang Gemini review.",
            )
            self.progress("[3/4] Gemini đang review và tối ưu retention...")
            review = self._retry(
                "Buoc review",
                lambda: self.provider.review(
                    state.gemini_proposal, state.deepseek_draft
                ),
            )
            state.optimization_report = review.optimization_report
            state.final_script = review.final_script
            state.completed_steps.append("review")
            self.save_checkpoint(state)
        else:
            logger.info("Bỏ qua bước review vì đã hoàn thành")
            trace_step_skipped(3, "Gemini Reviewer", "Đã có trong checkpoint")

        if "consistency" not in state.completed_steps:
            trace_handoff(
                "STEP 3 Gemini Reviewer",
                "STEP 4A/4B Consistency Auditors",
                {
                    "raw_youtube_data": state.raw_youtube_data,
                    "gemini_proposal": state.gemini_proposal.to_dict(),
                    "deepseek_draft": state.deepseek_draft,
                    "final_script": state.final_script,
                },
                "Cùng một bộ dữ liệu bất biến được gửi độc lập cho hai auditor.",
            )
            start_round = len(state.consistency_audits) + 1
            for round_offset in range(self.consistency_max_rounds):
                round_number = start_round + round_offset
                self.progress(
                    "[4/4] Đang kiểm tra tính nhất quán, vòng %d/%d..."
                    % (round_offset + 1, self.consistency_max_rounds)
                )
                deepseek_audit = self._retry(
                    "DeepSeek consistency audit",
                    lambda: self.provider.audit_deepseek(
                        state.raw_youtube_data,
                        state.gemini_proposal,
                        state.deepseek_draft,
                        state.final_script,
                    ),
                )
                gemini_audit = self._retry(
                    "Gemini consistency audit",
                    lambda: self.provider.audit_gemini(
                        state.raw_youtube_data,
                        state.gemini_proposal,
                        state.deepseek_draft,
                        state.final_script,
                    ),
                )
                duration_check = deterministic_duration_check(
                    state.gemini_proposal.target_duration,
                    state.final_script,
                    self.duration_tolerance,
                )
                gate = evaluate_quality_gate(
                    deepseek_audit,
                    gemini_audit,
                    duration_check,
                    self.consistency_min_score,
                )
                gate["round"] = round_number
                state.consistency_audits.append(gate)
                trace_parsed_response("4G", "Python Quality Gate", gate)
                logger.info(
                    "Consistency gate vòng %d | passed=%s | failures=%s",
                    round_number,
                    gate["passed"],
                    gate["failures"],
                )
                self.save_checkpoint(state)
                if gate["passed"]:
                    state.consistency_passed = True
                    state.completed_steps.append("consistency")
                    self.save_checkpoint(state)
                    break

                if round_offset < self.consistency_max_rounds - 1:
                    trace_handoff(
                        "STEP 4 Quality Gate",
                        "STEP 4R Gemini Repair",
                        gate,
                        "Các lỗi audit được gửi cho Gemini sửa có giới hạn.",
                    )
                    repair = self._retry(
                        "Gemini consistency repair",
                        lambda: self.provider.repair(
                            state.raw_youtube_data,
                            state.gemini_proposal,
                            state.deepseek_draft,
                            state.final_script,
                            gate,
                        ),
                    )
                    state.optimization_report = (
                        state.optimization_report + "\n" + repair.optimization_report
                    ).strip()
                    state.final_script = repair.final_script
                    state.revision_count += 1
                    self.save_checkpoint(state)

            if not state.consistency_passed:
                raise PipelineError(
                    "Kịch bản không vượt qua consistency quality gate sau %d vòng; "
                    "không xuất bản final." % self.consistency_max_rounds
                )
        else:
            logger.info("Bỏ qua consistency gate vì đã hoàn thành")
            trace_step_skipped(4, "Consistency Quality Gate", "Đã có trong checkpoint")
        logger.info("Pipeline hoàn tất | completed_steps=%s", state.completed_steps)
        logger.debug(
            "Pipeline final state:\n%s",
            json.dumps(state.to_dict(), ensure_ascii=False, indent=2),
        )
        return state


def script_metrics(script: str, words_per_minute: int = 150) -> dict:
    word_count = len(script.split())
    seconds = round(word_count / words_per_minute * 60) if word_count else 0
    return {
        "word_count": word_count,
        "estimated_speaking_seconds": seconds,
        "words_per_minute": words_per_minute,
    }


def write_outputs(state: FlowState, output_dir: Path) -> tuple:
    if not state.consistency_passed or "consistency" not in state.completed_steps:
        raise PipelineError(
            "Từ chối xuất final_script vì consistency quality gate chưa pass."
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    script_path = output_dir / "final_script.txt"
    result_path = output_dir / "result.json"
    script_path.write_text(state.final_script + "\n", encoding="utf-8")
    payload = state.to_dict()
    payload["metrics"] = script_metrics(state.final_script)
    result_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    logger.info("Đã ghi output | script=%s | json=%s", script_path, result_path)
    logger.debug("Output result payload:\n%s", json.dumps(payload, ensure_ascii=False, indent=2))
    return script_path, result_path
