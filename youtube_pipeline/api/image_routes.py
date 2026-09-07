"""API for generating resource-pack still images with OpenAI gpt-image-2."""
from __future__ import annotations

import os
import re
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from . import paths
from .image_runner import ImageBusyError, image_runner
from .. import image_config
from .routes import _check_job_id, _check_run_id, _require_scoped_channel, _require_state, _run_path

router = APIRouter(prefix="/api/images")
_IMAGE_ID_RE = re.compile(r"^IMG-\d{1,4}$")
DEFAULT_MODEL = "gpt-image-2"
MODELS = image_config.SUPPORTED_MODELS
SIZES = image_config.SUPPORTED_SIZES
QUALITIES = image_config.SUPPORTED_QUALITIES
logger = logging.getLogger(__name__)


def _scope_kwargs(user_id: str | None, channel_id: str | None) -> tuple[str | None, str | None]:
    if bool(user_id) != bool(channel_id):
        raise HTTPException(status_code=400, detail="user_id và channel_id phải được truyền cùng nhau")
    return user_id, channel_id


def _has_key(user_id: str | None = None, channel_id: str | None = None) -> bool:
    return bool(image_config.resolve_api_key(paths.backend_root(), user_id, channel_id))


@router.get("/config")
def image_config_get(user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> dict:
    _require_scoped_channel(user_id, channel_id)
    user_id, channel_id = _scope_kwargs(user_id, channel_id)
    return image_config.snapshot(paths.backend_root(), user_id, channel_id)


@router.put("/config")
def image_config_put(body: dict, user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> dict:
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Payload image config phải là object.")
    _require_scoped_channel(user_id, channel_id)
    user_id, channel_id = _scope_kwargs(user_id, channel_id)
    try:
        result = image_config.update(paths.backend_root(), body, user_id, channel_id)
        logger.info("image_config updated model=%s base_url=%s api_key_env=%s default_size=%s default_quality=%s key_configured=%s", result["model"], result["base_url"], result["api_key_env"], result["default_size"], result["default_quality"], result["api_key_configured"])
        return result
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _run_dir(run_id: str, user_id: str | None = None, channel_id: str | None = None) -> Path:
    if user_id and channel_id:
        return paths.channel_run_dir(user_id, channel_id, run_id)
    return _run_path(run_id, _require_state(run_id, user_id, channel_id))


def _require_run(run_id: str, user_id: str | None, channel_id: str | None) -> Path:
    _check_run_id(run_id)
    user_id, channel_id = _scope_kwargs(user_id, channel_id)
    _require_scoped_channel(user_id, channel_id)
    _require_state(run_id, user_id, channel_id)
    return _run_dir(run_id, user_id, channel_id)


def _prompt_rows(run_id: str, user_id: str | None = None, channel_id: str | None = None) -> tuple[Path, list[dict]]:
    path = _require_run(run_id, user_id, channel_id) / "visuals" / "prompt-pack.json"
    if not path.is_file():
        return path, []
    try:
        payload = __import__("json").loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="prompt-pack.json không hợp lệ: %s" % exc) from exc
    rows = payload.get("images") if isinstance(payload, dict) else []
    return path, [row for row in rows if isinstance(row, dict) and _IMAGE_ID_RE.match(str(row.get("image_id", "")))]


def _find_image(run_dir: Path, image_id: str) -> Path | None:
    for ext in ("png", "jpg", "jpeg", "webp"):
        candidate = run_dir / "video-build" / "images" / (image_id + "." + ext)
        if candidate.is_file():
            return candidate
    return None


@router.get("/status")
def image_status(user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> dict:
    user_id, channel_id = _scope_kwargs(user_id, channel_id)
    try:
        import openai  # noqa: F401

        sdk_ready = True
    except ImportError:
        sdk_ready = False
    return {"available": _has_key(user_id, channel_id) and sdk_ready, "has_api_key": _has_key(user_id, channel_id), "sdk_ready": sdk_ready, "model": DEFAULT_MODEL, "models": list(MODELS), "sizes": list(SIZES), "qualities": list(QUALITIES), "active_job": image_runner.active_job(user_id=user_id, channel_id=channel_id), "busy": image_runner.busy(user_id=user_id, channel_id=channel_id)}


@router.get("/runs/{run_id}/prompts")
def image_prompts(run_id: str, user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> dict:
    run_dir = _require_run(run_id, user_id, channel_id)
    path, rows = _prompt_rows(run_id, user_id, channel_id)
    entries = []
    for row in rows:
        image_id = str(row["image_id"])
        output = _find_image(run_dir, image_id)
        entries.append({"image_id": image_id, "prompt": str(row.get("prompt", "")), "exists": output is not None, "path": "video-build/images/%s" % output.name if output else None, "size_bytes": output.stat().st_size if output else None})
    return {"run_id": run_id, "prompt_pack_exists": path.is_file(), "images_dir": "video-build/images", "total": len(entries), "generated": sum(1 for row in entries if row["exists"]), "prompts": entries, "active_job": image_runner.active_job(user_id=user_id, channel_id=channel_id), "busy": image_runner.busy(user_id=user_id, channel_id=channel_id)}


@router.post("/runs/{run_id}/generate", status_code=202)
def start_image_generation(run_id: str, body: dict, user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> dict:
    run_dir = _require_run(run_id, user_id, channel_id)
    body = body or {}
    raw = body.get("images")
    _, rows = _prompt_rows(run_id, user_id, channel_id)
    available = {str(row["image_id"]) for row in rows}
    indices = [str(item).strip() for item in raw] if isinstance(raw, list) and raw else sorted(available)
    indices = list(dict.fromkeys(indices))
    if not indices:
        raise HTTPException(status_code=400, detail="Run chưa có image prompts.")
    invalid = [item for item in indices if item not in available]
    if invalid:
        raise HTTPException(status_code=400, detail="Image IDs không có trong prompt pack: %s" % ", ".join(invalid))
    if len(indices) > 200:
        raise HTTPException(status_code=400, detail="Tối đa 200 ảnh mỗi job.")
    configured = image_config.load(paths.backend_root(), user_id, channel_id)
    model = str(body.get("model") or configured["model"])
    size = str(body.get("size") or configured["default_size"])
    quality = str(body.get("quality") or configured["default_quality"])
    if model not in MODELS or size not in SIZES or quality not in QUALITIES:
        raise HTTPException(status_code=400, detail="model/size/quality không được hỗ trợ.")
    if not _has_key(user_id, channel_id):
        raise HTTPException(status_code=400, detail={"message": "Thiếu OPENAI_API_KEY trên API server.", "key": "images.noKey"})
    if image_runner.busy(user_id=user_id, channel_id=channel_id):
        active = image_runner.active_job(user_id=user_id, channel_id=channel_id)
        raise HTTPException(status_code=409, detail={"message": "Một job gen ảnh đang chạy.", "key": "busy", "active_job_id": active.get("id") if active else None})
    if body.get("skip_existing", True):
        indices = [item for item in indices if _find_image(run_dir, item) is None]
    if not indices:
        logger.info("image_generation skipped run=%s reason=all_images_exist", run_id)
        return {"job_id": None, "run_id": run_id, "status": "complete", "images": [], "message": "Tất cả ảnh đã tồn tại."}
    try:
        job = image_runner.start(run_id, run_dir, indices, model, size, quality, user_id=user_id, channel_id=channel_id)
    except ImageBusyError as exc:
        raise HTTPException(status_code=409, detail={"message": str(exc), "key": "busy", "active_job_id": exc.job_id}) from exc
    logger.info("image_generation accepted job=%s run=%s model=%s size=%s quality=%s images=%d", job["id"], run_id, model, size, quality, len(indices))
    return {"job_id": job["id"], "run_id": run_id, "images": indices, "model": model, "size": size, "quality": quality, "started_at": job["started_at"]}


@router.get("/jobs/{job_id}")
def image_job(job_id: str, user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> dict:
    _check_job_id(job_id)
    _require_scoped_channel(user_id, channel_id)
    _scope_kwargs(user_id, channel_id)
    status = image_runner.job_status(job_id, user_id=user_id, channel_id=channel_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy image job.")
    return status


@router.get("/jobs/{job_id}/log")
def image_job_log(job_id: str, offset: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=2000), user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> dict:
    _check_job_id(job_id)
    _require_scoped_channel(user_id, channel_id)
    _scope_kwargs(user_id, channel_id)
    return image_runner.get_log(job_id, offset, limit, user_id=user_id, channel_id=channel_id)


@router.post("/jobs/{job_id}/cancel")
def image_job_cancel(job_id: str, user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> dict:
    _check_job_id(job_id)
    _require_scoped_channel(user_id, channel_id)
    _scope_kwargs(user_id, channel_id)
    return {"cancelled": image_runner.cancel(job_id, user_id=user_id, channel_id=channel_id), "job_id": job_id}
