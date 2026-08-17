"""REST API cho resource pack pipeline — xem & chạy pipeline từ web UI.

Ground truth trạng thái run luôn là runs/<run_id>/run_state.json trên đĩa
(do CLI tự ghi). Server chỉ spawn subprocess, đọc state/artifacts/log và quản
lý guard "chỉ một pipeline đang chạy".
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Response

from . import content, paths
from .runner import BusyError, runner

router = APIRouter(prefix="/api")

_RUN_ID_RE = re.compile(paths.RUN_ID_PATTERN)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check_run_id(run_id: str) -> None:
    if not _RUN_ID_RE.match(run_id):
        raise HTTPException(status_code=400, detail="run_id không hợp lệ")


def _load_state(run_id: str) -> Optional[dict]:
    try:
        return json.loads(paths.run_state_path(run_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _require_state(run_id: str) -> dict:
    state = _load_state(run_id)
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


def _executing(run_id: str) -> bool:
    active = runner.active_run()
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


@router.get("/config")
def config() -> dict:
    root = paths.backend_root()
    input_files = []
    data_root = root / "data" / "channels"
    for p in sorted(data_root.glob("*.json")):
        if p.name.startswith("."):
            continue
        st = p.stat()
        input_files.append(
            {
                "name": str(p.relative_to(root)),
                "size_bytes": st.st_size,
                "modified_at": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            }
        )
    from youtube_pipeline.resource_pack.pipeline import MINIMAX_PROFILE, resource_pack_stages

    active = runner.active_run()
    return {
        "backend_root": str(root),
        "runs_dir": str(paths.runs_dir()),
        "python_executable": sys.executable,
        "input_files": input_files,
        "default_input_file": "data/channels/youtube_data.json",
        "minimax_profile": MINIMAX_PROFILE,
        "stage_order": [s.name for s in resource_pack_stages()],
        "active_run": active,
        "busy": active is not None,
        "poll_interval_ms": 1500,
        "quality_policy": "production",
    }


# ----------------------------------------------------------------------- runs


def _summary(run_id: str, state: dict) -> dict:
    manifest = paths.manifest_path(run_id)
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
        "executing": _executing(run_id),
    }


@router.get("/runs")
def list_runs() -> dict:
    runs = []
    runs_dir = paths.runs_dir()
    if runs_dir.is_dir():
        for entry in sorted(runs_dir.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            state = _load_state(entry.name)
            if state is None:
                continue
            runs.append(_summary(entry.name, state))
    runs.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
    return {"runs": runs}


@router.get("/runs/{run_id}")
def run_detail(run_id: str) -> dict:
    _check_run_id(run_id)
    state = _require_state(run_id)
    manifest = None
    manifest_file = paths.manifest_path(run_id)
    if manifest_file.is_file():
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    active = runner.active_run()
    is_active = bool(active and active.get("run_id") == run_id)
    return {
        "run_id": run_id,
        "run_dir": str(paths.run_dir(run_id)),
        "state": state,
        "manifest": manifest,
        "active": is_active,
        "orphaned": is_active and bool(active.get("orphaned")),
    }


@router.get("/runs/{run_id}/status")
def run_status(run_id: str) -> dict:
    _check_run_id(run_id)
    state = _require_state(run_id)
    records = state.get("stage_records") or {}
    active_stage = None
    names = list(records.keys())
    for name in names:
        if records[name].get("status") == "running":
            active_stage = {"index": names.index(name), "name": name, "status": "running"}
            break
    active = runner.active_run()
    is_active = bool(active and active.get("run_id") == run_id)
    return {
        "run_id": run_id,
        "status": state.get("status") or "unknown",
        "active_stage": active_stage,
        "stage_counts": _stage_counts(state),
        "updated_at": state.get("updated_at"),
        "finished": state.get("status") in ("complete", "failed"),
        "executing": is_active,
        "orphaned": is_active and bool(active.get("orphaned")),
    }


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
    output_dir = body.get("output_dir")
    if output_dir:
        out = Path(output_dir).resolve() if os.path.isabs(output_dir) else (paths.backend_root() / output_dir).resolve()
        if not out.is_relative_to(paths.runs_dir().resolve()):
            raise HTTPException(status_code=400, detail="output_dir phải nằm trong thư mục runs/")
    else:
        out = paths.run_dir(run_id)
    input_file = None
    if mode == "production":
        name = body.get("input_file")
        if not name:
            raise HTTPException(status_code=400, detail="production cần input_file")
        root = paths.backend_root().resolve()
        input_file = (root / name).resolve()
        data_root = (root / "data" / "channels").resolve()
        if not input_file.is_relative_to(data_root) or not input_file.is_file():
            raise HTTPException(status_code=400, detail="Input file phải tồn tại trong data/channels: %s" % name)
    try:
        log_file = runner.start_new(run_id, out, mode, input_file)
    except FileExistsError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except BusyError as exc:
        raise _busy_409(exc)
    return {
        "run_id": run_id,
        "run_dir": str(out),
        "mode": mode,
        "status": "starting",
        "quality": "production",
        "log_path": str(log_file),
    }


@router.post("/runs/{run_id}/resume", status_code=202)
def resume_run(run_id: str) -> dict:
    _check_run_id(run_id)
    state = _require_state(run_id)
    if state.get("status") == "running":
        raise HTTPException(status_code=400, detail="Run đang chạy — không thể resume chồng")
    try:
        log_file = runner.resume(run_id, paths.run_dir(run_id))
    except BusyError as exc:
        raise _busy_409(exc)
    return {
        "run_id": run_id,
        "resumed": True,
        "status": "starting",
        "quality": "production",
        "log_path": str(log_file),
    }


@router.post("/runs/{run_id}/cancel", status_code=202)
def cancel_run(run_id: str) -> dict:
    _check_run_id(run_id)
    if not runner.cancel(run_id):
        raise HTTPException(status_code=404, detail="Run không đang chạy — không thể hủy")
    return {"cancelled": True, "run_id": run_id}


@router.delete("/runs/{run_id}")
def delete_run(run_id: str) -> dict:
    """Xóa run directory hoàn toàn. Không thể xóa run đang chạy."""
    _check_run_id(run_id)

    # Check if run is executing
    if _executing(run_id):
        raise HTTPException(status_code=409, detail="Không thể xóa run đang chạy — hủy nó trước")

    run_dir = paths.run_dir(run_id)
    if not run_dir.exists():
        raise HTTPException(status_code=404, detail=f"Run không tồn tại: {run_id}")

    # Delete the entire run directory
    try:
        shutil.rmtree(run_dir)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Không xóa được: {e}")

    return {"deleted": True, "run_id": run_id}


# ------------------------------------------------------------------- artifacts


@router.get("/runs/{run_id}/log")
def run_log(run_id: str, offset: int = 0, limit: int = 200, download: int = 0) -> Response:
    _check_run_id(run_id)
    limit = max(1, min(limit, 1000))
    log_file = paths.log_path(run_id)
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
def run_artifacts(run_id: str) -> dict:
    _check_run_id(run_id)
    state = _require_state(run_id)
    run_root = paths.run_dir(run_id)
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
def run_artifact(run_id: str, path: str, download: int = 0) -> Response:
    _check_run_id(run_id)
    _require_state(run_id)
    f = content.resolve_artifact(paths.run_dir(run_id), path)
    ctype = content.content_type_for(f)
    disposition = "attachment" if download else "inline"
    headers = {
        "Content-Disposition": '%s; filename="%s"' % (disposition, f.name),
        "X-Content-Type-Options": "nosniff",
    }
    if download:
        return Response(content=f.read_bytes(), media_type=ctype, headers=headers)
    return Response(content=content.inline_body(f, ctype), media_type=ctype, headers=headers)
