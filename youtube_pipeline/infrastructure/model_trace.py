from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from typing import Any, Mapping, Optional

from .logging import MODEL_CALL_LOGGER_NAME

logger = logging.getLogger(MODEL_CALL_LOGGER_NAME)
_run_id: ContextVar[str] = ContextVar("model_call_run_id", default="unknown")


def _serialize(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def start_run(run_id: str, metadata: Mapping[str, Any]) -> None:
    _run_id.set(run_id)
    logger.info(
        "\n%s\nRUN START | run_id=%s\nMETADATA\n%s\n%s",
        "=" * 90,
        run_id,
        _serialize(dict(metadata)),
        "=" * 90,
    )


def trace_request(
    step: Any,
    name: str,
    provider: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
) -> None:
    logger.info(
        "\n%s\nSTEP %s REQUEST | %s | run_id=%s\n"
        "PROVIDER: %s\nMODEL: %s\nTEMPERATURE: %s\n\n"
        "[SYSTEM PROMPT]\n%s\n\n[USER PROMPT]\n%s\n%s",
        "-" * 90,
        step,
        name,
        _run_id.get(),
        provider,
        model,
        temperature,
        system_prompt,
        user_prompt,
        "-" * 90,
    )


def trace_raw_response(step: Any, name: str, response: Any) -> None:
    logger.info(
        "\nSTEP %s RAW RESPONSE | %s | run_id=%s\n%s",
        step,
        name,
        _run_id.get(),
        _serialize(response),
    )


def trace_parsed_response(step: Any, name: str, response: Any) -> None:
    logger.info(
        "\nSTEP %s PARSED RESPONSE | %s | run_id=%s\n%s",
        step,
        name,
        _run_id.get(),
        _serialize(response),
    )


def trace_handoff(
    from_step: str, to_step: str, payload: Any, description: str
) -> None:
    logger.info(
        "\n%s\nHANDOFF | %s -> %s | run_id=%s\nDESCRIPTION: %s\n"
        "[TRANSFERRED DATA]\n%s\n%s",
        ">" * 90,
        from_step,
        to_step,
        _run_id.get(),
        description,
        _serialize(payload),
        ">" * 90,
    )


def trace_step_skipped(step: Any, name: str, reason: str) -> None:
    logger.info(
        "\nSTEP %s SKIPPED | %s | run_id=%s\nREASON: %s",
        step,
        name,
        _run_id.get(),
        reason,
    )


def trace_error(step: str, error: BaseException) -> None:
    logger.exception(
        "\nSTEP ERROR | %s | run_id=%s\n%s",
        step,
        _run_id.get(),
        error,
        exc_info=(type(error), error, error.__traceback__),
    )


def finish_run(status: str, result: Optional[Any] = None) -> None:
    logger.info(
        "\n%s\nRUN END | run_id=%s | status=%s\nRESULT\n%s\n%s\n",
        "=" * 90,
        _run_id.get(),
        status,
        _serialize(result) if result is not None else "(none)",
        "=" * 90,
    )


def trace_call_metrics(
    step: Any,
    provider: str,
    model: str,
    latency_ms: float,
    *,
    cache_hit: bool = False,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    retry_count: int = 0,
) -> None:
    logger.info(
        "LLM_METRICS | step=%s | run_id=%s | provider=%s | model=%s | latency_ms=%.1f | cache_hit=%s | input_tokens=%s | output_tokens=%s | retries=%s",
        step, _run_id.get(), provider, model, latency_ms, cache_hit, input_tokens, output_tokens, retry_count,
    )
