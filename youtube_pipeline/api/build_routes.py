"""API Dựng video (Flow 3) — trạng thái tài nguyên + job dựng video cho 1 run.

Tách hẳn khỏi pipeline: job chạy `python -m youtube_pipeline.build_service`
(subprocess, fd kế thừa) — server không ghi run_state.json, không đụng engine.
Build job độc lập với pipeline run và data job (3 runner riêng, 3 cổng busy).
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Response

from .. import build_service
from . import paths
from .build_runner import BuildBusyError, build_job_command, build_runner
from .datapull import read_log_page
from .routes import _check_job_id, _check_run_id, _require_scoped_channel, _require_state, _run_path


def _run_dir(run_id: str, user_id: str | None = None, channel_id: str | None = None) -> Path:
    if user_id and channel_id:
        return paths.channel_run_dir(user_id, channel_id, run_id)
    return _run_path(run_id, _require_state(run_id, user_id, channel_id))


def _scope_kwargs(user_id: str | None, channel_id: str | None) -> tuple[str | None, str | None]:
    if bool(user_id) != bool(channel_id):
        raise HTTPException(status_code=400, detail="user_id và channel_id phải được truyền cùng nhau")
    return user_id, channel_id


def _require_run(run_id: str, user_id: str | None, channel_id: str | None) -> Path:
    _check_run_id(run_id)
    user_id, channel_id = _scope_kwargs(user_id, channel_id)
    _require_scoped_channel(user_id, channel_id)
    _require_state(run_id, user_id, channel_id)
    return _run_dir(run_id, user_id, channel_id)


def _safe_source_dir(source_dir: str, user_id: str | None, channel_id: str | None) -> str:
    """Keep scoped image imports inside the selected channel root."""
    source = Path(source_dir).expanduser().resolve()
    if user_id and channel_id:
        root = paths.channel_root(user_id, channel_id).resolve()
        if not source.is_relative_to(root):
            raise HTTPException(status_code=400, detail="source_dir phải nằm trong channel root hiện tại")
    return str(source)


# All build operations resolve the persisted run location, including channel-scoped runs.



router = APIRouter(prefix="/api/build")


def _busy_409(exc: BuildBusyError) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "message": str(exc),
            "key": "busy",
            "active_job_id": exc.job_id,
        },
    )


# ------------------------------------------------------------- trạng thái run


@router.get("/runs/{run_id}/status")
def build_status(run_id: str, user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> dict:
    """Còn thiếu gì để dựng video — không spawn gì cả."""
    run_dir = _require_run(run_id, user_id, channel_id)
    assets = build_service.check_assets(run_dir)
    report = assets.get("report") or {}
    return {
        "run_id": run_id,
        "active_job": build_runner.active_job(user_id=user_id, channel_id=channel_id),
        "busy": build_runner.busy(user_id=user_id, channel_id=channel_id),
        "pipeline_ready": assets["pipeline_ready"],
        "missing_artifacts": assets["missing_artifacts"],
        "timeline_status": assets["timeline_status"],
        "audio": assets["audio"],
        "audio_ready": assets["audio_ready"],
        "tts_chunks": assets["tts_chunks"],
        "sections_count": assets["sections_count"],
        "events_count": assets["events_count"],
        "unique_images": assets["unique_images"],
        "images": assets["images"],
        "images_ready": assets["images_ready"],
        "pack_ready": assets["pack_ready"],
        "pack_files": assets["pack_files"],
        "video_exists": assets["video_exists"],
        "video_ready": assets["video_ready"],
        "missing_reason": assets["missing_reason"],
        "last_report": {
            "status": report.get("status"),
            "generated_at": report.get("generated_at"),
            "next_step": report.get("next_step"),
            "error": report.get("error"),
        }
        if report
        else None,
        "tool": {
            "build_video_script": str(build_service.build_video_script()),
        },
    }


@router.post("/runs/{run_id}/merge-tts-chunks")
def merge_tts_chunks(run_id: str, user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> dict:
    """Merge TTS audio created from script/audio-chunks into normal narration audio."""
    run_dir = _require_run(run_id, user_id, channel_id)
    try:
        result = build_service.merge_tts_audio_chunks(run_dir)
    except build_service.BuildError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"run_id": run_id, **result}


# ------------------------------------------------------------- style phụ đề


@router.get("/runs/{run_id}/sub-style")
def get_sub_style(run_id: str, user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> dict:
    """Style phụ đề hiện tại (defaults nếu chưa có video-build/sub-style.json)."""
    run_dir = _require_run(run_id, user_id, channel_id)
    return {"run_id": run_id, "style": build_service.read_sub_style(run_dir)}


@router.put("/runs/{run_id}/sub-style")
def save_sub_style(run_id: str, body: dict, user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> dict:
    """Validate + ghi video-build/sub-style.json — build-video.py --subtitles tự đọc."""
    run_dir = _require_run(run_id, user_id, channel_id)
    try:
        style = build_service.write_sub_style(run_dir, body or {})

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"run_id": run_id, "saved": True, "style": style}


# ------------------------------------------------------------- import ảnh


@router.post("/runs/{run_id}/import-images")
def import_pack_images(run_id: str, body: dict, user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> dict:
    """Import ảnh đã gen (thư mục server-side) -> video-build/images/.

    Body params:
    - source_dir (required): thư mục chứa ảnh cần import
    - apply (bool, default false): false = xem trước, true = thực hiện đổi tên
    - insert (str): 'IMG-12:tên_file' — chèn ảnh vào vị trí cụ thể

    Mapping ảnh -> IMG-xx: nếu source_dir có IMPORT_MANIFEST.txt
    (`IMG-xx | filename.jpg | mô tả`) thì dùng mapping trong đó (chính xác 100%).
    Chưa có + apply=false -> service ghi manifest khung kèm mô tả scene để user
    đối chiếu, sửa rồi gọi lại apply=true. Response có `source` ("manifest"|"auto")
    và `manifest_written` khi vừa ghi file.
    """
    run_dir = _require_run(run_id, user_id, channel_id)
    body = body or {}
    source_dir = body.get("source_dir")
    if not isinstance(source_dir, str) or not source_dir.strip():
        raise HTTPException(status_code=400, detail="source_dir (thư mục ảnh đã gen) là bắt buộc")
    if build_runner.busy(user_id=user_id, channel_id=channel_id):
        active = build_runner.active_job(user_id=user_id, channel_id=channel_id)
        raise _busy_409(BuildBusyError(str(active["id"]) if active else "unknown"))
    insert = body.get("insert")
    if insert is not None and (not isinstance(insert, str) or ":" not in insert):
        raise HTTPException(status_code=400, detail="insert phải dạng 'IMG-12:tên_file'")
    apply = body.get("apply")
    if apply is not None and not isinstance(apply, bool):
        raise HTTPException(status_code=400, detail="apply phải là boolean")
    result = build_service.import_pack_images(
        run_dir,
        _safe_source_dir(source_dir.strip(), user_id, channel_id),
        insert=insert,
        apply=bool(apply),
    )
    return {"run_id": run_id, "apply": bool(apply), **result}


# ------------------------------------------------------------- job dựng video


def _validated_options(body: dict) -> dict:
    """Lọc + validate options dựng video; ValueError -> 400."""
    options: dict = {}
    if "render" in body:
        if not isinstance(body["render"], bool):
            raise ValueError("render phải là boolean")
        options["render"] = body["render"]
    if "motion" in body:
        if not isinstance(body["motion"], bool):
            raise ValueError("motion phải là boolean")
        options["motion"] = body["motion"]
    if "animation" in body:
        if not isinstance(body["animation"], str) or body["animation"] not in build_service.ANIM_MODES:
            raise ValueError("animation phải là một trong: %s"
                             % "|".join(build_service.ANIM_MODES))
        options["animation"] = body["animation"]
    if "dry_run" in body:
        if not isinstance(body["dry_run"], bool):
            raise ValueError("dry_run phải là boolean")
        options["dry_run"] = body["dry_run"]
    if "subtitles" in body:
        if not isinstance(body["subtitles"], bool):
            raise ValueError("subtitles phải là boolean")
        options["subtitles"] = body["subtitles"]
    if "logo_cleanup" in body:
        if not isinstance(body["logo_cleanup"], bool):
            raise ValueError("logo_cleanup phải là boolean")
        options["logo_cleanup"] = body["logo_cleanup"]
    if "logo_mode" in body:
        if body["logo_mode"] not in ("delogo", "blur"):
            raise ValueError("logo_mode phải là delogo hoặc blur")
        options["logo_mode"] = body["logo_mode"]
    if "transition" in body:
        transition = body["transition"]
        if not isinstance(transition, (int, float)) or isinstance(transition, bool):
            raise ValueError("transition phải là số giây")
        if not (0 <= transition <= 2):
            raise ValueError("transition phải nằm trong 0–2 giây")
        options["transition"] = float(transition)
    if "resolution" in body:
        resolution = body["resolution"]
        if (
            not isinstance(resolution, list)
            or len(resolution) != 2
            or not all(isinstance(v, int) and not isinstance(v, bool) for v in resolution)
            or not all(64 <= v <= 4096 for v in resolution)
        ):
            raise ValueError("resolution phải là [w, h] với mỗi chiều 64–4096")
        options["resolution"] = list(resolution)
    return options


@router.post("/runs/{run_id}/build")
def start_build(run_id: str, body: dict, user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> dict:
    run_dir = _require_run(run_id, user_id, channel_id)
    try:
        options = _validated_options(body or {})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if build_runner.busy(user_id=user_id, channel_id=channel_id):
        active = build_runner.active_job(user_id=user_id, channel_id=channel_id)
        raise _busy_409(BuildBusyError(str(active["id"]) if active else "unknown"))

    if not (run_dir / "video-build").is_dir():
        (run_dir / "video-build").mkdir(parents=True, exist_ok=True)
    argv = build_job_command(run_dir, options)
    try:
        job = build_runner.start(
            run_id, argv, cwd=paths.backend_root(), user_id=user_id, channel_id=channel_id
        )
    except BuildBusyError as exc:
        raise _busy_409(exc)
    return {"job_id": job["id"], "run_id": run_id, "started_at": job["started_at"]}


# ------------------------------------------------------------------------ jobs


@router.post("/jobs/{job_id}/cancel")
def cancel_build_job(job_id: str, user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> dict:
    _check_job_id(job_id)
    _require_scoped_channel(user_id, channel_id)
    _scope_kwargs(user_id, channel_id)
    if not build_runner.cancel(job_id, user_id=user_id, channel_id=channel_id):
        raise HTTPException(status_code=404, detail="Job không đang chạy — không thể hủy")
    return {"cancelled": True, "job_id": job_id}


@router.get("/jobs/{job_id}")
def build_job_status(job_id: str, user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> dict:
    _check_job_id(job_id)
    _require_scoped_channel(user_id, channel_id)
    _scope_kwargs(user_id, channel_id)
    job = build_runner.job_status(job_id, user_id=user_id, channel_id=channel_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy job: %s" % job_id)
    return job


@router.get("/jobs/{job_id}/log")
def build_job_log(
    job_id: str, offset: int = 0, limit: int = 200, download: int = 0,
    user_id: str | None = Query(None), channel_id: str | None = Query(None),
) -> Response:
    _check_job_id(job_id)
    _require_scoped_channel(user_id, channel_id)
    _scope_kwargs(user_id, channel_id)
    limit = max(1, min(limit, 1000))
    log_file = build_runner.log_path(job_id, user_id=user_id, channel_id=channel_id)
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
