"""REST API cho resource pack pipeline — xem & chạy pipeline từ web UI.

Ground truth trạng thái run luôn là runs/<run_id>/run_state.json trên đĩa
(do CLI tự ghi). Server chỉ spawn subprocess, đọc state/artifacts/log và quản
lý guard "chỉ một pipeline đang chạy".
"""
from __future__ import annotations

import json
import os
import re
import socket
import ssl
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Response, Query
from fastapi.responses import StreamingResponse

from . import content, paths
from ..channel_context import validate_scope_id
from .runner import BusyError, runner

router = APIRouter(prefix="/api")


def _registry_database():
    from youtube_pipeline.platform_db import PlatformDatabase
    return PlatformDatabase(paths.backend_root() / "runtime" / "platform.sqlite3")


def _require_registered_channel(
    user_id: str | None,
    channel_id: str | None,
    youtube_channel_id: str | None = None,
) -> dict:
    if not user_id or not channel_id:
        raise HTTPException(status_code=400, detail="user_id và channel_id phải được truyền cùng nhau")
    try:
        validate_scope_id(user_id, "user_id")
        validate_scope_id(channel_id, "channel_id")
        channel = _registry_database().get_channel(
            user_id=user_id, channel_id=channel_id, include_inactive=False
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel chưa được đăng ký hoặc đã bị vô hiệu hóa")
    if youtube_channel_id and channel["youtube_channel_id"] != youtube_channel_id:
        raise HTTPException(status_code=409, detail="youtube_channel_id không khớp channel registry")
    return channel


@router.get("/channels")
def list_channels(user_id: str = Query("dev-user"), include_inactive: bool = Query(False)) -> dict:
    try:
        channels = _registry_database().list_channels(user_id=user_id, include_inactive=include_inactive)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"channels": channels}


@router.post("/channels", status_code=201)
def register_channel(body: dict) -> dict:
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Payload channel phải là object.")
    user_id = str(body.get("user_id") or "dev-user")
    try:
        channel = _registry_database().register_channel(
            user_id=user_id,
            channel_id=str(body.get("channel_id") or ""),
            youtube_channel_id=str(body.get("youtube_channel_id") or ""),
            title=body.get("title"),
            flow_profile=str(body.get("flow_profile") or "resource_pack"),
        )
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=409 if "đã được đăng ký" in detail else 400, detail=detail) from exc
    return {"channel": channel}


@router.get("/channels/{channel_id}")
def get_channel(channel_id: str, user_id: str = Query("dev-user")) -> dict:
    try:
        channel = _registry_database().get_channel(user_id=user_id, channel_id=channel_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if channel is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy channel")
    return {"channel": channel}


@router.patch("/channels/{channel_id}")
def update_channel(channel_id: str, body: dict) -> dict:
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Payload channel phải là object.")
    user_id = str(body.get("user_id") or "dev-user")
    try:
        channel = _registry_database().update_channel(
            user_id=user_id,
            channel_id=channel_id,
            title=body.get("title"),
            flow_profile=body.get("flow_profile"),
            active=body.get("active"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if channel is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy channel")
    return {"channel": channel}


@router.delete("/channels/{channel_id}")
def deactivate_channel(channel_id: str, user_id: str = Query("dev-user")) -> dict:
    try:
        channel = _registry_database().deactivate_channel(user_id=user_id, channel_id=channel_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if channel is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy channel")
    return {"channel": channel}


_RUN_ID_RE = re.compile(paths.RUN_ID_PATTERN)
_JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def _check_job_id(job_id: str) -> None:
    """Validate job identifiers before they reach a runner or filesystem."""
    if not isinstance(job_id, str) or not _JOB_ID_RE.fullmatch(job_id):
        raise HTTPException(status_code=400, detail="job_id không hợp lệ")


def _require_scoped_channel(user_id: str | None, channel_id: str | None) -> dict | None:
    """Require an active registry row whenever a request selects a namespace.

    ``None`` scope deliberately retains legacy development behavior.
    """
    if bool(user_id) != bool(channel_id):
        raise HTTPException(status_code=400, detail="user_id và channel_id phải được truyền cùng nhau")
    return _require_registered_channel(user_id, channel_id) if user_id and channel_id else None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check_run_id(run_id: str) -> None:
    if not _RUN_ID_RE.fullmatch(run_id):
        raise HTTPException(status_code=400, detail="run_id không hợp lệ")



def _find_run_dir(
    run_id: str,
    user_id: str | None = None,
    channel_id: str | None = None,
) -> Optional[Path]:
    if bool(user_id) != bool(channel_id):
        raise HTTPException(status_code=400, detail="user_id và channel_id phải được truyền cùng nhau")
    if user_id and channel_id:
        candidate = paths.channel_run_dir(user_id, channel_id, run_id)
        return candidate if (candidate / "run_state.json").is_file() else None
    legacy = paths.run_dir(run_id)
    if (legacy / "run_state.json").is_file():
        return legacy
    users_root = paths.backend_root() / "users"
    if users_root.is_dir():
        matches = [
            candidate for candidate in users_root.glob(f"*/channels/*/runs/{run_id}")
            if (candidate / "run_state.json").is_file()
        ]
        if len(matches) == 1:
            return matches[0]
    return None


def _load_state(
    run_id: str,
    user_id: str | None = None,
    channel_id: str | None = None,
) -> Optional[dict]:
    run_dir = _find_run_dir(run_id, user_id, channel_id)
    if run_dir is None:
        return None
    try:
        return json.loads((run_dir / "run_state.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _require_state(run_id: str, user_id: str | None = None, channel_id: str | None = None) -> dict:
    state = _load_state(run_id, user_id, channel_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy run: %s" % run_id)
    return state


def _stage_counts(state: dict) -> dict:
    records = state.get("stage_records") or {}
    counts = {"total": len(records), "passed": 0, "failed": 0, "pending": 0, "running": 0}
    for rec in records.values():
        status = rec.get("status")
        if status in counts:
            counts[status] += 1
    return counts


def _executing(
    run_id: str,
    user_id: str | None = None,
    channel_id: str | None = None,
) -> bool:
    active = runner.active_run(user_id=user_id, channel_id=channel_id)
    return bool(active and active.get("run_id") == run_id)


# --------------------------------------------------------------------- system


@router.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "version": "0.1.0",
        "time": _now_iso(),
        "backend_root": str(paths.backend_root()),
    }




# ----------------------------------------------------------- model configuration

def _model_router():
    from youtube_pipeline.config import Settings
    from youtube_pipeline.model_router import ModelRouter
    return ModelRouter(Settings.from_env(require_keys=False), paths.backend_root())


@router.get("/model-config")
def model_config() -> dict:
    router_config = _model_router()
    data = router_config.snapshot()
    for name, profile in data.get("profiles", {}).items():
        profile["api_key_configured"] = router_config.profile_api_key_configured(name)
    return {
        **data,
        "roles": ["analysis", "writer", "reviewer", "editor", "auditor", "packaging"],
        "provider_types": ["gemini", "openai_compatible"],
    }


@router.put("/model-config")
def update_model_config(body: dict) -> dict:
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Payload model-config phải là object.")
    try:
        updated = _model_router().update(body)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    router_config = _model_router()
    for name, profile in updated.get("profiles", {}).items():
        profile["api_key_configured"] = router_config.profile_api_key_configured(name)
    return updated


@router.post("/model-config/preflight")
def preflight_model_config() -> dict:
    """Validate TLS reachability for configured OpenAI-compatible endpoints.

    This intentionally performs no model request and never exposes or sends an
    API key. A valid TLS handshake is enough to catch the common wrong-domain
    certificate/SNI failure before a costly Run Live starts.
    """
    router_config = _model_router()
    results = []
    for name, raw in router_config.snapshot().get("profiles", {}).items():
        provider = str(raw.get("provider", "")).strip()
        base_url = str(raw.get("base_url", "")).strip()
        if provider != "openai_compatible":
            results.append({"profile": name, "provider": provider, "status": "skipped", "detail": "TLS preflight applies to OpenAI-compatible HTTP endpoints only."})
            continue
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            results.append({"profile": name, "provider": provider, "base_url": base_url, "status": "failed", "category": "provider_configuration", "detail": "Base URL phải là HTTPS URL hợp lệ, ví dụ https://provider.example/v1."})
            continue
        port = parsed.port or 443
        try:
            with socket.create_connection((parsed.hostname, port), timeout=8) as raw_socket:
                context = ssl.create_default_context()
                with context.wrap_socket(raw_socket, server_hostname=parsed.hostname) as tls_socket:
                    cipher = tls_socket.cipher()
            results.append({"profile": name, "provider": provider, "base_url": base_url, "status": "ok", "detail": "TLS certificate hợp lệ cho hostname đã cấu hình.", "tls": cipher[0] if cipher else None})
        except ssl.SSLCertVerificationError as exc:
            results.append({"profile": name, "provider": provider, "base_url": base_url, "status": "failed", "category": "tls_certificate", "detail": "TLS certificate không khớp hostname. Provider phải sửa certificate/SNI hoặc cung cấp Base URL khác.", "technical_detail": str(exc)})
        except (OSError, ValueError) as exc:
            results.append({"profile": name, "provider": provider, "base_url": base_url, "status": "failed", "category": "provider_connection", "detail": "Không thể kết nối endpoint từ API server.", "technical_detail": str(exc)})
    return {"results": results, "checked_at": _now_iso()}


@router.get("/config")
def config(
    user_id: str | None = Query(None),
    channel_id: str | None = Query(None),
) -> dict:
    """Return UI configuration in either the legacy or selected-channel namespace.

    Omitting both scope parameters deliberately preserves the original global
    behavior. Once either parameter is supplied, both are required and the
    channel must be registered; this prevents a config request from leaking a
    different channel's datasets or active process state.
    """
    if bool(user_id) != bool(channel_id):
        raise HTTPException(status_code=400, detail="user_id và channel_id phải được truyền cùng nhau")

    root = paths.backend_root()
    from youtube_pipeline.api.datapull import list_datasets
    from youtube_pipeline.resource_pack.pipeline import MINIMAX_PROFILE, resource_pack_stages

    channel = None
    if user_id and channel_id:
        channel = _require_registered_channel(user_id, channel_id)
        input_files = list_datasets(user_id=user_id, channel_id=channel_id)
        runs_dir = paths.channel_runs_dir(user_id, channel_id)
        active = runner.active_run(user_id=user_id, channel_id=channel_id)
        scope = {"user_id": user_id, "channel_id": channel_id}
    else:
        input_files = list_datasets()
        runs_dir = paths.runs_dir()
        active = runner.active_run()
        scope = None

    default_input_file = None
    if input_files:
        preferred = "data/channels/youtube_data.json"
        default_input_file = next(
            (item["file"] for item in input_files if item["file"] == preferred),
            input_files[0]["file"],
        )
    return {
        "backend_root": str(root),
        "scope": scope,
        "channel": channel,
        "channel_scoped": scope is not None,
        "runs_dir": str(runs_dir),
        "python_executable": sys.executable,
        "input_files": input_files,
        "default_input_file": default_input_file,
        # Model routing is intentionally shared/global; channel scope applies
        # to datasets, runs, and execution state only.
        "minimax_profile": MINIMAX_PROFILE,
        "stage_order": [s.name for s in resource_pack_stages()],
        "active_run": active,
        "busy": active is not None,
        "poll_interval_ms": 1500,
    }


@router.post("/platform/reindex")
def reindex_platform() -> dict:
    """Rebuild SQLite metadata from portable run_state/artifact files."""
    from youtube_pipeline.core.state import RunState
    from youtube_pipeline.platform_db import PlatformDatabase
    from youtube_pipeline.topic_history import record_completed

    root = paths.backend_root()
    indexed = 0
    skipped = 0
    failures: list[dict[str, str]] = []
    run_dirs: list[Path] = []
    legacy_root = paths.runs_dir()
    if legacy_root.is_dir():
        run_dirs.extend(p for p in legacy_root.iterdir() if p.is_dir() and not p.name.startswith("."))
    users_root = paths.backend_root() / "users"
    if users_root.is_dir():
        run_dirs.extend(users_root.glob("*/channels/*/runs/*"))
    for run_dir in sorted(run_dirs):
        if not run_dir.is_dir() or run_dir.name.startswith("."):
            continue
        database = PlatformDatabase.for_run_root(run_dir)
        state_file = run_dir / "run_state.json"
        if not state_file.is_file():
            skipped += 1
            continue

        state_file = run_dir / "run_state.json"
        if not state_file.is_file():
            skipped += 1
            continue
        try:
            state = RunState.from_dict(json.loads(state_file.read_text(encoding="utf-8")))
            database.sync_state(state, run_dir)
            selected_file = run_dir / "research/topic-selection.json"
            brief_file = run_dir / "script/psychology-brief.json"
            contract_file = run_dir / "script/contract.json"
            if state.status == "complete" and selected_file.is_file():
                selected = json.loads(selected_file.read_text(encoding="utf-8"))
                brief = json.loads(brief_file.read_text(encoding="utf-8")) if brief_file.is_file() else {}
                contract = json.loads(contract_file.read_text(encoding="utf-8")) if contract_file.is_file() else {}
                record_completed(run_dir, state.run_id, {**selected, "chosen_title": contract.get("chosen_title", "")}, brief)
            indexed += 1
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            failures.append({"run_id": run_dir.name, "run_dir": str(run_dir), "error": str(exc)})
    return {"indexed": indexed, "skipped": skipped, "failures": failures}


# ----------------------------------------------------------------------- runs


def _run_path(
    run_id: str,
    state: Optional[dict] = None,
    user_id: str | None = None,
    channel_id: str | None = None,
) -> Path:
    run_dir = _find_run_dir(run_id, user_id, channel_id)
    return run_dir or (paths.channel_run_dir(user_id, channel_id, run_id) if user_id and channel_id else paths.run_dir(run_id))


def _summary(run_id: str, state: dict, user_id: str | None = None, channel_id: str | None = None) -> dict:
    run_dir = _run_path(run_id, state, user_id, channel_id)
    manifest = run_dir / "manifest.json"
    has_manifest = manifest.is_file()
    timeline_status = None
    if has_manifest:
        try:
            timeline_status = json.loads(manifest.read_text(encoding="utf-8")).get(
                "timeline_status"
            )
        except (OSError, json.JSONDecodeError):
            pass
    return {
        "run_id": run_id,
        "topic": state.get("topic") or "",
        "profile": state.get("profile") or "",
        "status": state.get("status") or "unknown",
        "created_at": state.get("created_at"),
        "updated_at": state.get("updated_at"),
        "stage_counts": _stage_counts(state),
        "warnings": state.get("warnings") or [],
        "errors": state.get("errors") or [],
        "has_manifest": has_manifest,
        "timeline_status": timeline_status,
        "executing": _executing(run_id, user_id, channel_id),
        "run_dir": str(run_dir),
        "user_id": state.get("user_id"),
        "channel_id": state.get("channel_id"),
        "youtube_channel_id": state.get("youtube_channel_id"),
    }


@router.get("/runs")
def list_runs(user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> dict:
    _require_scoped_channel(user_id, channel_id)
    if bool(user_id) != bool(channel_id):
        raise HTTPException(status_code=400, detail="user_id và channel_id phải được truyền cùng nhau")
    runs = []
    runs_dir = paths.channel_runs_dir(user_id, channel_id) if user_id and channel_id else paths.runs_dir()
    if runs_dir.is_dir():
        for entry in sorted(runs_dir.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            state = _load_state(entry.name, user_id, channel_id)
            if state is None:
                continue
            runs.append(_summary(entry.name, state, user_id, channel_id))
    runs.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
    return {"runs": runs}


@router.get("/runs/{run_id}")
def run_detail(run_id: str, user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> dict:
    _check_run_id(run_id)
    state = _require_state(run_id, user_id, channel_id)
    if user_id and channel_id:
        _require_registered_channel(user_id, channel_id)
        if state.get("user_id") != user_id or state.get("channel_id") != channel_id:
            raise HTTPException(status_code=404, detail="Không tìm thấy run trong channel hiện tại")
    run_dir = _run_path(run_id, state, user_id, channel_id)
    manifest = None
    manifest_file = run_dir / "manifest.json"
    if manifest_file.is_file():
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    active = runner.active_run(user_id=user_id, channel_id=channel_id)
    is_active = bool(active and active.get("run_id") == run_id)
    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "state": state,
        "manifest": manifest,
        "active": is_active,
        "orphaned": is_active and bool(active.get("orphaned")),
    }


@router.get("/runs/{run_id}/diagnostics")
def run_diagnostics(run_id: str, user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> dict:
    """Safe provenance and model telemetry, indexed by SQLite when available."""
    _check_run_id(run_id)
    state = _require_state(run_id, user_id, channel_id)
    if user_id and channel_id:
        _require_registered_channel(user_id, channel_id)
        if state.get("user_id") != user_id or state.get("channel_id") != channel_id:
            raise HTTPException(status_code=404, detail="Không tìm thấy run trong channel hiện tại")


    from youtube_pipeline.platform_db import PlatformDatabase

    run_dir = _run_path(run_id, state, user_id, channel_id)
    database_path = PlatformDatabase.path_for_run_root(run_dir)
    if database_path.exists():
        report = PlatformDatabase(database_path).run_diagnostics(
            run_id,
            user_id=state.get("user_id"),
            channel_id=state.get("channel_id"),
        )
        if report is not None:
            return {"run_id": run_id, "source": "sqlite", **report}
    # Old runs predate the index. Expose the frozen route in state without
    # creating a database during a read request.
    return {
        "run_id": run_id,
        "source": "run_state",
        "indexed": False,
        "run_status": state.get("status", "unknown"),
        "updated_at": state.get("updated_at"),
        "routing_snapshot": (state.get("config_snapshot") or {}).get("model_routing"),
        "stages": [],
        "model_calls": {"total": 0, "succeeded": 0, "failed": 0, "duration_ms": 0, "calls": []},
    }


@router.get("/runs/{run_id}/status")
def run_status(run_id: str, user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> dict:
    _check_run_id(run_id)
    state = _require_state(run_id, user_id, channel_id)
    if user_id and channel_id:
        _require_registered_channel(user_id, channel_id)
        if state.get("user_id") != user_id or state.get("channel_id") != channel_id:
            raise HTTPException(status_code=404, detail="Không tìm thấy run trong channel hiện tại")
    records = state.get("stage_records") or {}
    active_stage = None
    names = list(records.keys())
    for name in names:
        if records[name].get("status") == "running":
            active_stage = {"index": names.index(name), "name": name, "status": "running"}
            break
    active = runner.active_run(user_id=user_id, channel_id=channel_id)
    is_active = bool(active and active.get("run_id") == run_id)
    return {
        "run_id": run_id,
        "status": state.get("status") or "unknown",
        "active_stage": active_stage,
        "stage_counts": _stage_counts(state),
        "updated_at": state.get("updated_at"),
        "execution_started_at": state.get("execution_started_at"),
        "execution_finished_at": state.get("execution_finished_at"),
        "execution_elapsed_seconds": state.get("execution_elapsed_seconds"),
        "total_elapsed_seconds": state.get("total_elapsed_seconds", 0.0),
        "finished": state.get("status") in ("complete", "failed"),
        "executing": is_active,
        "orphaned": is_active and bool(active.get("orphaned")),
    }


@router.get("/runs/{run_id}/events")
def run_events(run_id: str, user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> StreamingResponse:
    """Stream run status updates until the subprocess reaches a terminal state."""
    _check_run_id(run_id)
    state = _require_state(run_id, user_id, channel_id)
    if user_id and channel_id:
        _require_registered_channel(user_id, channel_id)
        if state.get("user_id") != user_id or state.get("channel_id") != channel_id:
            raise HTTPException(status_code=404, detail="Không tìm thấy run trong channel hiện tại")


    def stream():
        import time

        previous = ""
        while True:
            state = _load_state(run_id, user_id, channel_id)
            if state is None:
                break
            records = state.get("stage_records") or {}
            active_stage = None
            names = list(records.keys())
            for name in names:
                if records[name].get("status") == "running":
                    active_stage = {"index": names.index(name), "name": name, "status": "running"}
                    break
            active = runner.active_run(user_id=user_id, channel_id=channel_id)
            payload = {
                "run_id": run_id,
                "status": state.get("status") or "unknown",
                "active_stage": active_stage,
                "stage_counts": _stage_counts(state),
                "updated_at": state.get("updated_at"),
                "execution_started_at": state.get("execution_started_at"),
                "execution_finished_at": state.get("execution_finished_at"),
                "execution_elapsed_seconds": state.get("execution_elapsed_seconds"),
                "total_elapsed_seconds": state.get("total_elapsed_seconds", 0.0),
                "finished": state.get("status") in ("complete", "failed"),
                "executing": bool(active and active.get("run_id") == run_id),
                "orphaned": bool(active and active.get("run_id") == run_id and active.get("orphaned")),
                "state": state,
            }
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            if encoded != previous:
                previous = encoded
                yield "event: run_update\ndata: %s\n\n" % encoded
            if payload["finished"]:
                break
            time.sleep(1.0)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _busy_409(exc: BusyError) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "message": "Một pipeline đang chạy: %s" % exc.run_id,
            "key": "busy",
            "active_run_id": exc.run_id,
        },
    )


@router.post("/runs", status_code=202)
def start_run(body: dict) -> dict:
    mode = body.get("mode")
    if mode not in ("demo", "production"):
        raise HTTPException(status_code=400, detail="mode phải là 'demo' hoặc 'production'")
    run_id = body.get("run_id") or uuid.uuid4().hex
    if not _RUN_ID_RE.match(run_id):
        raise HTTPException(status_code=400, detail="run_id không hợp lệ")
    input_file = None
    manual_topic = None
    no_channel_data = False
    channel_id = body.get("channel_id")
    youtube_channel_id = body.get("youtube_channel_id")
    if channel_id and not youtube_channel_id:
        raise HTTPException(status_code=400, detail="channel context thiếu youtube_channel_id")
    user_id = str(body.get("user_id") or "dev-user")
    flow_profile = str(body.get("flow_profile") or "resource_pack")
    output_dir = body.get("output_dir")
    approved_research_brief = None
    if channel_id:
        registered = _require_registered_channel(user_id, channel_id, youtube_channel_id)
        youtube_channel_id = registered["youtube_channel_id"]
        if not body.get("flow_profile"):
            flow_profile = registered["flow_profile"]
        canonical_out = paths.channel_run_dir(user_id, channel_id, run_id).resolve()
    else:
        canonical_out = paths.run_dir(run_id).resolve()
    if output_dir:
        out = Path(output_dir).resolve() if os.path.isabs(output_dir) else (paths.backend_root() / output_dir).resolve()
        if out != canonical_out:
            raise HTTPException(status_code=400, detail="output_dir phải trỏ đúng namespace run hiện tại.")
    else:
        out = canonical_out



    research_run_id = str(body.get("research_run_id") or "").strip()
    if research_run_id:
        if not channel_id:
            raise HTTPException(status_code=400, detail="research_run_id yêu cầu channel scope")
        if mode != "production":
            raise HTTPException(status_code=400, detail="research_run_id chỉ hỗ trợ production run")
        if not _RUN_ID_RE.match(research_run_id):
            raise HTTPException(status_code=400, detail="research_run_id không hợp lệ")
        candidate = paths.channel_root(user_id, channel_id) / "research" / (research_run_id + ".editorial-brief.json")
        try:
            brief = json.loads(candidate.read_text(encoding="utf-8"))
        except OSError as exc:
            raise HTTPException(status_code=404, detail="Không tìm thấy approved research brief") from exc
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="Approved research brief không hợp lệ") from exc
        if brief.get("user_id") != user_id or brief.get("channel_id") != channel_id:
            raise HTTPException(status_code=404, detail="Approved research brief không thuộc channel hiện tại")
        if not isinstance(brief.get("opportunity"), dict):
            raise HTTPException(status_code=400, detail="Approved research brief thiếu opportunity")
        if brief.get("channel_profile", {}).get("stop_before_media_generation") is not True:
            raise HTTPException(status_code=400, detail="Research brief không phải production resource-pack brief")
        approved_research_brief = candidate
        no_channel_data = True
        manual_topic = None

    if mode == "production":
        channel_data_mode = str(body.get("channel_data_mode") or "snapshot")
        if research_run_id:
            channel_data_mode = "none"
        if channel_data_mode not in ("refresh", "snapshot", "none"):
            raise HTTPException(status_code=400, detail="channel_data_mode không hợp lệ")
        if channel_data_mode == "none":
            candidate_topic = str(body.get("manual_topic") or "").strip()
            # Browser form libraries sometimes serialize an unset optional
            # value as a string. Treat those sentinels exactly like an empty
            # field so this path remains competitor-led topic discovery.
            manual_topic = None if candidate_topic.casefold() in {"", "none", "null", "undefined", "n/a"} else candidate_topic
            no_channel_data = True
        name = body.get("input_file")
        if channel_data_mode != "none" and not name:
            raise HTTPException(
                status_code=400,
                detail="Chọn một channel dataset trước khi chạy production.",
            )
        if channel_data_mode != "none":
            from youtube_pipeline.api.datapull import resolve_dataset_file
            try:
                input_file = resolve_dataset_file(
                    str(name), user_id=user_id if channel_id else None,
                    channel_id=channel_id if channel_id else None,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        log_file = runner.start_new(
            run_id, out, mode, input_file, manual_topic, no_channel_data,
            user_id=user_id,
            channel_id=channel_id,
            youtube_channel_id=youtube_channel_id,
            flow_profile=flow_profile,
            approved_research_brief=approved_research_brief,
        )
    except FileExistsError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except BusyError as exc:
        raise _busy_409(exc)
    return {
        "run_id": run_id,
        "run_dir": str(out),
        "mode": mode,
        "status": "starting",
        "log_path": str(log_file),
    }


@router.post("/runs/{run_id}/resume", status_code=202)
def resume_run(run_id: str, user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> dict:
    _check_run_id(run_id)
    state = _require_state(run_id, user_id, channel_id)
    if user_id and channel_id:
        _require_registered_channel(user_id, channel_id)
        if state.get("user_id") != user_id or state.get("channel_id") != channel_id:
            raise HTTPException(status_code=404, detail="Không tìm thấy run trong channel hiện tại")
    run_dir = _find_run_dir(run_id, user_id, channel_id)
    if run_dir is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy run: %s" % run_id)
    if state.get("status") == "running":
        raise HTTPException(status_code=400, detail="Run đang chạy — không thể resume chồng")
    try:
        log_file = runner.resume(
            run_id,
            run_dir,
            user_id=user_id,
            channel_id=channel_id,
            youtube_channel_id=state.get("youtube_channel_id"),
            flow_profile=state.get("flow_profile"),
        )
    except BusyError as exc:
        raise _busy_409(exc)
    return {
        "run_id": run_id,
        "resumed": True,
        "status": "starting",
        "log_path": str(log_file),
    }


@router.post("/runs/{run_id}/topic-status")
def update_topic_status(run_id: str, body: dict, user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> dict:
    """Mark a completed resource pack as published only after the user releases it."""
    _check_run_id(run_id)
    state = _require_state(run_id, user_id, channel_id)
    if user_id and channel_id:
        _require_registered_channel(user_id, channel_id)
    if state.get("user_id") != user_id or state.get("channel_id") != channel_id:
        if user_id or channel_id:
            raise HTTPException(status_code=404, detail="Không tìm thấy run trong channel hiện tại")
    if state.get("status") != "complete":
        raise HTTPException(status_code=400, detail="Chỉ cập nhật lifecycle cho run đã hoàn tất.")
    status = body.get("status") if isinstance(body, dict) else None
    try:
        from youtube_pipeline.topic_history import set_topic_status
        set_topic_status(
            _run_path(run_id, state),
            run_id,
            str(status),
            user_id=user_id,
            channel_id=channel_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"run_id": run_id, "topic_status": status}


@router.post("/runs/{run_id}/cancel", status_code=202)
def cancel_run(run_id: str, user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> dict:
    _check_run_id(run_id)
    state = _require_state(run_id, user_id, channel_id)
    if user_id and channel_id:
        _require_registered_channel(user_id, channel_id)
    run_dir = _run_path(run_id, state, user_id, channel_id)
    if user_id and channel_id and run_dir != paths.channel_run_dir(user_id, channel_id, run_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy run trong channel hiện tại")
    if not runner.cancel(run_id, user_id=user_id, channel_id=channel_id):
        raise HTTPException(status_code=404, detail="Run không đang chạy — không thể hủy")
    return {"cancelled": True, "run_id": run_id}


@router.delete("/runs/{run_id}")
def delete_run(run_id: str, user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> dict:
    """Xóa run directory hoàn toàn. Không thể xóa run đang chạy."""
    _check_run_id(run_id)
    state = _require_state(run_id, user_id, channel_id)
    if user_id and channel_id:
        _require_registered_channel(user_id, channel_id)

    # Check if run is executing
    if _executing(run_id, user_id, channel_id):
        raise HTTPException(status_code=409, detail="Không thể xóa run đang chạy — hủy nó trước")

    run_dir = _find_run_dir(run_id, user_id, channel_id)
    if run_dir is None or not run_dir.exists():
        raise HTTPException(status_code=404, detail=f"Run không tồn tại: {run_id}")

    # Delete the entire run directory
    try:
        shutil.rmtree(run_dir)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Không xóa được: {e}")

    return {"deleted": True, "run_id": run_id}


# ------------------------------------------------------------------- artifacts


@router.get("/runs/{run_id}/log")
def run_log(run_id: str, offset: int = 0, limit: int = 200, download: int = 0, user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> Response:
    _check_run_id(run_id)
    limit = max(1, min(limit, 1000))
    state = _require_state(run_id, user_id, channel_id)
    if user_id and channel_id:
        _require_registered_channel(user_id, channel_id)
    run_dir = _run_path(run_id, state, user_id, channel_id)
    if user_id and channel_id and (state.get("user_id") != user_id or state.get("channel_id") != channel_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy run trong channel hiện tại")
    state = state or {}
    user_id = state.get("user_id")
    channel_id = state.get("channel_id")
    log_file = paths.channel_log_path(user_id, channel_id, run_id) if user_id and channel_id else paths.log_path(run_id)
    if download:
        if not log_file.is_file():
            raise HTTPException(status_code=404, detail="Log không tồn tại")
        return Response(
            content=log_file.read_bytes(),
            media_type="text/plain; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="%s.log"' % run_id,
                "X-Content-Type-Options": "nosniff",
            },
        )
    if not log_file.is_file():
        return Response(
            content=json.dumps(
                {
                    "run_id": run_id,
                    "offset": offset,
                    "limit": limit,
                    "total_lines": 0,
                    "next_offset": offset,
                    "eof": True,
                    "log_exists": False,
                    "lines": [],
                },
                ensure_ascii=False,
            ),
            media_type="application/json",
        )
    lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    total = len(lines)
    start = min(offset, total)
    chunk = lines[start : start + limit]
    return Response(
        content=json.dumps(
            {
                "run_id": run_id,
                "offset": start,
                "limit": limit,
                "total_lines": total,
                "next_offset": start + len(chunk),
                "eof": start + len(chunk) >= total,
                "log_exists": True,
                "lines": chunk,
            },
            ensure_ascii=False,
        ),
        media_type="application/json",
    )


@router.get("/runs/{run_id}/artifacts")
def run_artifacts(run_id: str, user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> dict:
    _check_run_id(run_id)
    state = _require_state(run_id, user_id, channel_id)
    if user_id and channel_id:
        _require_registered_channel(user_id, channel_id)
        if state.get("user_id") != user_id or state.get("channel_id") != channel_id:
            raise HTTPException(status_code=404, detail="Không tìm thấy run trong channel hiện tại")
    run_root = _run_path(run_id, state, user_id, channel_id)
    index = state.get("artifact_index") or {}
    by_path = {}
    for ref in index.values():
        p = ref.get("path")
        if p:
            by_path[p] = ref
    tree: dict = {}
    for f in sorted(run_root.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(run_root)
        rel_posix = rel.as_posix()
        if rel_posix == "run_state.json":
            continue
        ref = by_path.get(rel_posix)
        parent = rel.parent.as_posix()
        tree.setdefault("" if parent == "." else parent, {})[f.name] = {
            "artifact_type": ref.get("artifact_type") if ref else None,
            "size_bytes": f.stat().st_size,
            "content_type": content.content_type_for(f),
            "qa_status": ref.get("qa_status") if ref else None,
            "producer_stage": ref.get("producer_stage") if ref else None,
        }
    return {"run_id": run_id, "tree": tree}


@router.get("/runs/{run_id}/artifact")
def run_artifact(run_id: str, path: str, download: int = 0, user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> Response:
    _check_run_id(run_id)
    state = _require_state(run_id, user_id, channel_id)
    if user_id and channel_id:
        _require_registered_channel(user_id, channel_id)
        if state.get("user_id") != user_id or state.get("channel_id") != channel_id:
            raise HTTPException(status_code=404, detail="Không tìm thấy run trong channel hiện tại")
    f = content.resolve_artifact(_run_path(run_id, state, user_id, channel_id), path)
    ctype = content.content_type_for(f)
    disposition = "attachment" if download else "inline"
    headers = {
        "Content-Disposition": '%s; filename="%s"' % (disposition, f.name),
        "X-Content-Type-Options": "nosniff",
    }
    if download:
        return Response(content=f.read_bytes(), media_type=ctype, headers=headers)
    return Response(content=content.inline_body(f, ctype), media_type=ctype, headers=headers)
