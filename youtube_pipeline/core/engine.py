from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Protocol


class RetryableStageError(Exception):
    """Marker for errors safe to retry at the stage boundary."""


class QualityGateError(Exception):
    """Deterministic quality/validation failure; do not blind-retry."""


from .artifacts import ArtifactStore
from .state import ArtifactRef, RunState, StageRecord, utc_now

logger = logging.getLogger(__name__)


def _classify_retry(exc: Exception) -> str:
    """Classify failures so deterministic bugs are not blindly retried."""
    name = type(exc).__name__
    module = type(exc).__module__
    messages: list[str] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        messages.append(str(current).lower())
        current = current.__cause__ or current.__context__
    message = " | ".join(messages)

    if "deterministic failure" in message or "no blind retry" in message:
        return "deterministic"

    if isinstance(exc, QualityGateError):
        return "quality_gate"
    if isinstance(exc, RetryableStageError):
        return "explicit_retryable"
    if any(marker in message for marker in (
        "certificate name does not match", "certificate verify failed",
        "ssl: certificate", "hostname mismatch", "tlsv",
    )):
        # A certificate/SNI mismatch cannot succeed on a second attempt. It
        # needs a corrected provider endpoint or a repaired provider cert.
        return "provider_configuration"
    if name in {"ValidationError", "JSONDecodeError"} or "invalid json" in message or "json hợp lệ" in message:
        return "model_validation"
    if name in {
        "TimeoutError", "ReadTimeout", "ConnectTimeout", "WriteTimeout",
        "PoolTimeout", "APITimeoutError",
    } or any(marker in message for marker in (
        "timeout", "timed out", "deadline exceeded", "gateway timeout",
        "request timeout", "request timed out",
    )):
        return "timeout"
    code = getattr(exc, "code", None)
    try:
        numeric_code = int(code) if code is not None else None
    except (TypeError, ValueError):
        numeric_code = None
    if numeric_code in {408, 409, 425, 429} or numeric_code is not None and 500 <= numeric_code <= 599:
        return "provider_transient"
    if numeric_code is not None and 400 <= numeric_code <= 499:
        return "provider_configuration"
    if "429" in message or "rate limit" in message or "too many requests" in message:
        return "provider_transient"
    if "503" in message or "service unavailable" in message or "high demand" in message:
        return "provider_transient"
    if name in {"APIConnectionError", "ConnectError", "NetworkError"} or any(marker in message for marker in (
        "connection error", "connection refused", "network is unreachable",
        "name or service not known", "temporary failure in name resolution",
    )):
        return "provider_connection"
    if any(marker in message for marker in ("401", "403", "404", "invalid api key", "model not found", "not found")):
        return "provider_configuration"
    if isinstance(exc, (ValueError, KeyError, TypeError, AttributeError, AssertionError)):
        return "deterministic"
    return "unknown"


def run_with_retry(
    step_name: str,
    operation: Callable[[], Any],
    max_retries: int,
    retry_delay: float,
    progress: Callable[[str], None] | None = None,
    on_error: Callable[[int, Exception], None] | None = None,
) -> tuple[Any, dict[str, Any]]:
    last_error: Exception | None = None
    attempt_elapsed: list[float] = []
    failure_categories: list[str] = []
    attempt_limit = max(1, max_retries)

    for attempt in range(1, attempt_limit + 1):
        attempt_started = time.perf_counter()
        try:
            result = operation()
            elapsed = time.perf_counter() - attempt_started
            attempt_elapsed.append(round(elapsed, 3))
            logger.info(
                "%s | success attempt %d/%d | elapsed=%.2fs | retry_category=%s",
                step_name, attempt, attempt_limit, elapsed,
                failure_categories[-1] if failure_categories else "none",
            )
            return result, {
                "attempt_count": attempt,
                "retry_count": max(0, attempt - 1),
                "attempt_elapsed_seconds": attempt_elapsed,
                "failure_categories": failure_categories,
            }
        except QualityGateError as exc:
            last_error = exc
            category = "quality_gate"
            failure_categories.append(category)
            elapsed = time.perf_counter() - attempt_started
            attempt_elapsed.append(round(elapsed, 3))
            if on_error:
                on_error(attempt, exc)
            logger.error(
                "%s | quality gate failed attempt %d/%d | elapsed=%.2fs",
                step_name, attempt, attempt_limit, elapsed,
            )
            raise RuntimeError("%s quality gate failed: %s" % (step_name, exc)) from exc
        except Exception as exc:
            last_error = exc
            category = _classify_retry(exc)
            failure_categories.append(category)
            elapsed = time.perf_counter() - attempt_started
            attempt_elapsed.append(round(elapsed, 3))
            if on_error:
                on_error(attempt, exc)
            logger.exception(
                "%s | failed attempt %d/%d | category=%s | elapsed=%.2fs",
                step_name, attempt, attempt_limit, category, elapsed,
            )

            # Deterministic validation/programming errors should never burn all retries.
            if category in {"deterministic", "provider_configuration"}:
                # Keep the stable phrase used by run logs and compatibility
                # checks: deterministic failure (no blind retry).
                raise RuntimeError(
                    "%s %s failure (no blind retry): %s" % (
                        step_name,
                        "deterministic" if category == "deterministic" else "provider configuration",
                        exc,
                    )
                ) from exc

            # Malformed model output gets at most one fresh attempt.
            if category == "model_validation" and attempt >= 2:
                break

            if attempt == attempt_limit:
                break
            if progress:
                progress(
                    "%s lỗi category=%s (lần %d/%d), đang thử lại..."
                    % (step_name, category, attempt, attempt_limit)
                )
            time.sleep(retry_delay * attempt)

    category = failure_categories[-1] if failure_categories else "unknown"
    raise RuntimeError(
        "%s failed after %d attempts: category=%s: %s" %
        (step_name, len(attempt_elapsed), category, last_error)
    ) from last_error


@dataclass
class StageResult:
    artifacts: list[ArtifactRef] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class RunContext:
    state: RunState
    store: ArtifactStore
    provider: Any
    raw_data: str
    topic: str
    config: dict[str, Any]
    progress: Callable[[str], None] = print


class Stage(Protocol):
    name: str
    version: str
    requires: tuple[str, ...]

    def execute(self, context: RunContext) -> StageResult:
        ...


@dataclass
class FunctionStage:
    name: str
    handler: Callable[[RunContext], StageResult]
    requires: tuple[str, ...] = ()
    version: str = "1"
    config: dict[str, Any] = field(default_factory=dict)

    def execute(self, context: RunContext) -> StageResult:
        return self.handler(context)


class PipelineEngine:
    def __init__(
        self,
        stages: Iterable[Stage],
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> None:
        self.stages = list(stages)
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    @staticmethod
    def _fingerprint(stage: Stage, context: RunContext) -> str:
        payload = {
            "stage": stage.name,
            "version": stage.version,
            "config": {**(context.config or {}), **(getattr(stage, "config", None) or {})},
            "requires": {
                name: context.state.artifact(name).sha256 for name in stage.requires
            },
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _reusable(record: StageRecord, fingerprint: str, context: RunContext) -> bool:
        if record.status != "passed" or record.input_fingerprint != fingerprint:
            return False
        for artifact_type in record.artifacts:
            ref = context.state.artifact_index.get(artifact_type)
            if ref is None or not context.store.verify(ref):
                return False
        return True

    def run(self, context: RunContext) -> RunState:
        state = context.state
        # Run-level clock: one current execution plus cumulative time across resume.
        execution_started_at = utc_now()
        previous_total = float(state.total_elapsed_seconds or 0.0)
        execution_started_perf = time.perf_counter()
        if state.total_started_at is None:
            state.total_started_at = state.created_at or execution_started_at
        state.execution_started_at = execution_started_at
        state.execution_finished_at = None
        state.execution_elapsed_seconds = None
        state.status = "running"
        state.updated_at = execution_started_at
        context.store.save_state(state)
        for position, stage in enumerate(self.stages, start=1):
            for requirement in stage.requires:
                state.artifact(requirement)
            fingerprint = self._fingerprint(stage, context)
            record = state.stage_records.get(stage.name)
            if record and self._reusable(record, fingerprint, context):
                context.progress("[%d/%d] %s: dùng lại artifact đã pass" % (position, len(self.stages), stage.name))
                continue
            previous_artifact_types = list(record.artifacts) if record else []
            record = StageRecord(
                stage_name=stage.name,
                stage_version=stage.version,
                status="running",
                attempts=0,
                input_fingerprint=fingerprint,
                started_at=utc_now(),
            )
            state.stage_records[stage.name] = record
            context.store.save_state(state)
            context.progress("[%d/%d] %s" % (position, len(self.stages), stage.name))
            try:
                stage_started_perf = time.perf_counter()

                def operation() -> StageResult:
                    record.attempts += 1
                    return stage.execute(context)

                result, retry_meta = run_with_retry(
                    stage.name,
                    operation,
                    self.max_retries,
                    self.retry_delay,
                    context.progress,
                )
                new_artifact_types = {ref.artifact_type for ref in result.artifacts}
                for artifact_type in previous_artifact_types:
                    if artifact_type not in new_artifact_types:
                        # Artifact là INPUT của stage này (nằm trong requires) không
                        # bao giờ được xóa — nó do stage upstream sở hữu và stage sau
                        # vẫn cần. Trường hợp cũ: structure_check repair tạo lại
                        # final_script (producer=structure_check) rồi lần sau pass
                        # không repair → cleanup xóa final_script khỏi index dù
                        # consistency vừa phát lại ref mới → "Missing artifact" khi resume.
                        if artifact_type in stage.requires:
                            continue
                        # Chỉ xóa artifact do CHÍNH stage này sản xuất ở lần chạy trước.
                        # Artifact cùng type nhưng do stage khác tạo phải được giữ nguyên.
                        old_ref = state.artifact_index.get(artifact_type)
                        if old_ref is not None and old_ref.producer_stage == stage.name:
                            state.artifact_index.pop(artifact_type, None)
                for ref in result.artifacts:
                    state.artifact_index[ref.artifact_type] = ref
                record.status = "passed"
                record.finished_at = utc_now()
                record.artifacts = [ref.artifact_type for ref in result.artifacts]
                record.metrics = {
                    **result.metrics,
                    "attempts": record.attempts,
                    "elapsed_seconds": round(time.perf_counter() - stage_started_perf, 3),
                    **retry_meta,
                }
                record.warnings = result.warnings
                context.store.save_state(state)
            except Exception as exc:
                record.status = "failed"
                record.finished_at = utc_now()
                record.error = "%s: %s" % (type(exc).__name__, exc)
                state.status = "failed"
                state.errors.append(record.error)
                finished_at = utc_now()
                elapsed = round(time.perf_counter() - execution_started_perf, 3)
                state.execution_finished_at = finished_at
                state.execution_elapsed_seconds = elapsed
                state.total_finished_at = finished_at
                state.total_elapsed_seconds = round(previous_total + elapsed, 3)
                state.updated_at = finished_at
                context.store.save_state(state)
                raise
        state.status = "complete"
        finished_at = utc_now()
        elapsed = round(time.perf_counter() - execution_started_perf, 3)
        state.execution_finished_at = finished_at
        state.execution_elapsed_seconds = elapsed
        state.total_finished_at = finished_at
        state.total_elapsed_seconds = round(previous_total + elapsed, 3)
        state.updated_at = finished_at
        context.store.save_state(state)
        return state
