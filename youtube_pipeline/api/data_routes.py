"""REST API cho tính năng "Kéo data YouTube" (prefix /api/data).

Chỉ spawn youtube_pull.py làm subprocess qua DataPullRunner (xem datapull.py).
Gating kết nối nằm phía UI (nút kéo disabled khi chưa connect) — server không
chặn cứng vì puller tự auth lại trong job nếu token hết hạn giữa chừng.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Response

from . import paths
from .routes import _check_job_id, _require_scoped_channel
from .datapull import (
    BusyError,
    build_connect_command,
    build_pull_command,
    build_reporting_command,
    data_runner,
    last_result,
    read_log_page,
    resolve_out_file,
    resolve_pull_dir,
    resolve_pull_python,
    token_status,
    token_path,
    validate_dates,
    validate_video_ids,
)

router = APIRouter(prefix="/api/data")


def _require_registered_channel(user_id: Optional[str], channel_id: Optional[str], youtube_channel_id: Optional[str] = None) -> dict:
    if not user_id or not channel_id:
        raise HTTPException(status_code=400, detail="user_id và channel_id phải được truyền cùng nhau")
    from youtube_pipeline.platform_db import PlatformDatabase
    try:
        channel = PlatformDatabase(paths.backend_root() / "runtime" / "platform.sqlite3").get_channel(
            user_id=user_id, channel_id=channel_id, include_inactive=False
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel chưa được đăng ký hoặc đã bị vô hiệu hóa")
    if youtube_channel_id and youtube_channel_id != channel["youtube_channel_id"]:
        raise HTTPException(status_code=409, detail="youtube_channel_id không khớp channel registry")
    return channel


def _require_pull_env() -> Path:
    pull_dir = resolve_pull_dir()
    if pull_dir is None or not pull_dir.is_dir():
        raise HTTPException(
            status_code=400,
            detail="Không tìm thấy puller youtube_pull.py — đặt YT_DATA_PULL_DIR",
        )
    return pull_dir


def _busy_409(exc: BusyError) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "message": "Một data job đang chạy: %s" % exc.job_id,
            "key": "busy",
            "active_job_id": exc.job_id,
        },
    )


def _start_job(
    kind: str, argv: list[str], pull_dir: Path, out_file: Optional[Path] = None,
    *, user_id: Optional[str] = None, channel_id: Optional[str] = None,
) -> dict:
    try:
        return data_runner.start(kind, argv, pull_dir, out_file=out_file, user_id=user_id, channel_id=channel_id)
    except BusyError as exc:
        raise _busy_409(exc)


def _require_int(name: str, value) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValueError("%s phải là số nguyên" % name)
    if n < 0:
        raise ValueError("%s không được âm" % name)
    return n


# ------------------------------------------------------------------- status


@router.get("/status")
def data_status(user_id: Optional[str] = None, channel_id: Optional[str] = None) -> dict:
    registered = _require_scoped_channel(user_id, channel_id)
    pull_dir = resolve_pull_dir()
    available = pull_dir is not None and pull_dir.is_dir()
    python = None
    token = {"exists": False, "expires_at": None, "scopes_ok": False, "identity_ok": None}
    if available:
        python = resolve_pull_python(str(pull_dir))
        token = token_status(
            pull_dir,
            user_id=user_id,
            channel_id=channel_id,
            expected_youtube_channel_id=registered["youtube_channel_id"] if registered else None,
        )
        if registered and token.get("identity_ok") is False:
            token["scopes_ok"] = False
    active = data_runner.active_job(user_id=user_id, channel_id=channel_id)
    return {
        "available": available,
        "pull_dir": str(pull_dir) if pull_dir is not None else None,
        "python": python,
        "connected": bool(token["exists"] and token["scopes_ok"]),
        "expires_at": token["expires_at"],
        "scopes_ok": token["scopes_ok"],
        "busy": active is not None,
        "active_job": active,
        "datasets": __import__("youtube_pipeline.api.datapull", fromlist=["list_datasets"]).list_datasets(user_id=user_id, channel_id=channel_id),
        "last_result": last_result(user_id=user_id, channel_id=channel_id),
    }


# ------------------------------------------------------------------ actions


@router.post("/connect", status_code=202)
def data_connect(body: dict | None = None) -> dict:
    """Token hợp lệ -> job exit 0 nhanh; ngược lại mở browser flow (job chờ)."""
    body = body if isinstance(body, dict) else {}
    user_id = body.get("user_id")
    channel_id = body.get("channel_id")
    registered = _require_registered_channel(user_id, channel_id, body.get("youtube_channel_id"))
    pull_dir = _require_pull_env()
    python = resolve_pull_python(str(pull_dir))
    token_file = token_path(pull_dir, user_id=registered["user_id"], channel_id=registered["channel_id"])
    job = _start_job(
        "connect", build_connect_command(python, token_file=token_file), pull_dir,
        user_id=registered["user_id"], channel_id=registered["channel_id"],
    )
    return {"job_id": job["id"], "kind": "connect", "user_id": registered["user_id"], "channel_id": registered["channel_id"]}




@router.post("/pull", status_code=202)
def data_pull(body: dict) -> dict:
    pull_dir = _require_pull_env()
    user_id = body.get("user_id")
    channel_id = body.get("channel_id")
    registered = _require_registered_channel(user_id, channel_id, body.get("youtube_channel_id"))
    user_id = registered["user_id"]
    channel_id = registered["channel_id"]
    python = resolve_pull_python(str(pull_dir))
    mode = body.get("mode")
    if mode not in ("video_ids", "range", "all"):
        raise HTTPException(
            status_code=400,
            detail="mode phải là 'video_ids', 'range' hoặc 'all'",
        )
    try:
        out = resolve_out_file(body.get("out_file"), user_id=user_id, channel_id=channel_id)
        kwargs: dict = {}
        if mode == "video_ids":
            kwargs["video_ids"] = validate_video_ids(body.get("video_ids"))
        elif mode == "range":
            start_date, end_date = validate_dates(
                body.get("start_date"), body.get("end_date")
            )
            kwargs["start_date"] = start_date
            kwargs["end_date"] = end_date
        max_comments = body.get("max_comments")
        if max_comments is not None:
            max_comments = _require_int("max_comments", max_comments)
        max_replies = body.get("max_replies")
        if max_replies is not None:
            max_replies = _require_int("max_replies", max_replies)
        kwargs["max_comments"] = max_comments
        kwargs["max_replies"] = max_replies
        kwargs["no_replies"] = bool(body.get("no_replies"))
        argv = build_pull_command(python, mode, out=out, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    job = _start_job("pull", argv, pull_dir, out_file=out, user_id=user_id, channel_id=channel_id)
    return {"job_id": job["id"], "kind": "pull", "mode": mode}


@router.post("/reporting", status_code=202)
def data_reporting(body: dict) -> dict:
    pull_dir = _require_pull_env()
    user_id = body.get("user_id")
    channel_id = body.get("channel_id")
    registered = _require_registered_channel(user_id, channel_id, body.get("youtube_channel_id"))
    user_id = registered["user_id"]
    channel_id = registered["channel_id"]
    python = resolve_pull_python(str(pull_dir))
    action = body.get("action")
    if action not in ("setup", "sync"):
        raise HTTPException(status_code=400, detail="action phải là 'setup' hoặc 'sync'")
    try:
        out = resolve_out_file(body.get("out_file"), user_id=user_id, channel_id=channel_id)
        argv = build_reporting_command(python, action, out)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # sync ghi vào file output; setup chỉ tạo job reporting (không có file).
    job = _start_job(
        "reporting", argv, pull_dir, out_file=out if action == "sync" else None,
        user_id=user_id, channel_id=channel_id,
    )
    return {"job_id": job["id"], "kind": "reporting", "action": action}


# --------------------------------------------------------------------- jobs


@router.post("/jobs/{job_id}/cancel", status_code=202)
def cancel_data_job(job_id: str, user_id: Optional[str] = None, channel_id: Optional[str] = None) -> dict:
    _check_job_id(job_id)
    if bool(user_id) != bool(channel_id):
        raise HTTPException(status_code=400, detail="user_id và channel_id phải được truyền cùng nhau")
    if user_id and channel_id:
        _require_registered_channel(user_id, channel_id)
    if not data_runner.cancel(job_id, user_id=user_id, channel_id=channel_id):
        raise HTTPException(status_code=404, detail="Job không đang chạy — không thể hủy")
    return {"cancelled": True, "job_id": job_id}


@router.get("/jobs/{job_id}")
def data_job_status(job_id: str, user_id: Optional[str] = None, channel_id: Optional[str] = None) -> dict:
    _check_job_id(job_id)
    if bool(user_id) != bool(channel_id):
        raise HTTPException(status_code=400, detail="user_id và channel_id phải được truyền cùng nhau")
    if user_id and channel_id:
        _require_registered_channel(user_id, channel_id)
    job = data_runner.job_status(job_id, user_id=user_id, channel_id=channel_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy job: %s" % job_id)
    return job


@router.get("/jobs/{job_id}/log")
def data_job_log(
    job_id: str, offset: int = 0, limit: int = 200, download: int = 0,
    user_id: Optional[str] = None, channel_id: Optional[str] = None,
) -> Response:
    _check_job_id(job_id)
    if bool(user_id) != bool(channel_id):
        raise HTTPException(status_code=400, detail="user_id và channel_id phải được truyền cùng nhau")
    if user_id and channel_id:
        _require_registered_channel(user_id, channel_id)
    limit = max(1, min(limit, 1000))
    log_file = _job_dir(user_id, channel_id) / ("%s.log" % job_id)
    if data_runner.job_status(job_id, user_id=user_id, channel_id=channel_id) is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy job: %s" % job_id)
    if download:
        if not log_file.is_file():
            raise HTTPException(status_code=404, detail="Log không tồn tại")
        return Response(
            content=log_file.read_bytes(),
            media_type="text/plain; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="%s.log"' % job_id,
                "X-Content-Type-Options": "nosniff",
            },
        )
    page = read_log_page(log_file, offset, limit)
    return Response(
        content=json.dumps({"job_id": job_id, **page}, ensure_ascii=False),
        media_type="application/json",
    )


def _job_dir(user_id: Optional[str] = None, channel_id: Optional[str] = None) -> Path:
    if user_id and channel_id:
        return paths.channel_root(user_id, channel_id) / "runtime" / "data-jobs"
    return paths.data_jobs_dir()
