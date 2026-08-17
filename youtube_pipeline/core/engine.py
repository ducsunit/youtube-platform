from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Protocol

from .artifacts import ArtifactStore
from .state import ArtifactRef, RunState, StageRecord, utc_now
from .timing import ElapsedTimer, elapsed_seconds, format_duration

logger = logging.getLogger(__name__)


def run_with_retry(
    step_name: str,
    operation: Callable[[], Any],
    max_retries: int,
    retry_delay: float,
    progress: Callable[[str], None] | None = None,
    on_error: Callable[[int, Exception], None] | None = None,
) -> Any:
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            result = operation()
            logger.info("%s | success attempt %d/%d", step_name, attempt, max_retries)
            return result
        except Exception as exc:
            last_error = exc
            if on_error:
                on_error(attempt, exc)
            logger.exception("%s | failed attempt %d/%d", step_name, attempt, max_retries)
            if attempt == max_retries:
                break
            if progress:
                progress("%s lỗi (lần %d/%d), đang thử lại..." % (step_name, attempt, max_retries))
            time.sleep(retry_delay * attempt)
    raise RuntimeError("%s failed after %d attempts: %s" % (step_name, max_retries, last_error)) from last_error


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
    cache: dict[str, Any] = field(default_factory=dict)

    def invalidate_artifacts(self, artifact_types: Iterable[str]) -> None:
        for artifact_type in artifact_types:
            self.cache.pop(artifact_type, None)


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
        execution_started_at = utc_now()
        timer = ElapsedTimer()
        state.status = "running"
        state.execution_started_at = execution_started_at
        state.execution_finished_at = None
        state.execution_elapsed_seconds = None
        if not state.total_started_at:
            state.total_started_at = execution_started_at
        context.store.save_state(state)
        context.progress("[timer 00:00:00] Pipeline bắt đầu")
        for position, stage in enumerate(self.stages, start=1):
            for requirement in stage.requires:
                state.artifact(requirement)
            fingerprint = self._fingerprint(stage, context)
            record = state.stage_records.get(stage.name)
            if record and self._reusable(record, fingerprint, context):
                context.progress("[timer %s] [%d/%d] %s: dùng lại artifact đã pass" % (timer.formatted, position, len(self.stages), stage.name))
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
            context.progress("[timer %s] [%d/%d] %s" % (timer.formatted, position, len(self.stages), stage.name))
            try:
                def operation() -> StageResult:
                    record.attempts += 1
                    return stage.execute(context)

                result = run_with_retry(
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
                record.metrics = result.metrics
                record.warnings = result.warnings
                context.store.save_state(state)
            except Exception as exc:
                record.status = "failed"
                record.finished_at = utc_now()
                record.error = "%s: %s" % (type(exc).__name__, exc)
                state.status = "failed"
                state.errors.append(record.error)
                execution_finished_at = utc_now()
                state.execution_finished_at = execution_finished_at
                state.execution_elapsed_seconds = elapsed_seconds(state.execution_started_at, execution_finished_at)
                state.total_finished_at = execution_finished_at
                state.total_elapsed_seconds = elapsed_seconds(state.total_started_at, execution_finished_at)
                context.store.save_state(state)
                context.progress("[timer %s] Pipeline thất bại sau %s" % (timer.formatted, format_duration(state.execution_elapsed_seconds)))
                raise
        execution_finished_at = utc_now()
        state.execution_finished_at = execution_finished_at
        state.execution_elapsed_seconds = elapsed_seconds(state.execution_started_at, execution_finished_at)
        state.total_finished_at = execution_finished_at
        state.total_elapsed_seconds = elapsed_seconds(state.total_started_at, execution_finished_at)
        state.status = "complete"
        context.store.save_state(state)
        context.progress("[timer %s] Pipeline hoàn thành | tổng thời gian %s" % (timer.formatted, format_duration(state.total_elapsed_seconds)))
        return state
