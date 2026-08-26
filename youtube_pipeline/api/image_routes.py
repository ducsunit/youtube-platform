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
from .routes import _check_run_id, _require_state
from ..image_gen import is_valid_image_file

router = APIRouter(prefix="/api/images")
_IMAGE_ID_RE = re.compile(r"^IMG-\d{1,4}$")
DEFAULT_MODEL = "gpt-image-2"
SUPPORTED_SIZES = image_config.SUPPORTED_SIZES
SUPPORTED_QUALITIES = image_config.SUPPORTED_QUALITIES
logger = logging.getLogger(__name__)


def _has_key() -> bool:
    return bool(image_config.resolve_api_key(paths.backend_root()))


@router.get("/config")
def image_config_get() -> dict:
    return image_config.snapshot(paths.backend_root())


@router.put("/config")
def image_config_put(body: dict) -> dict:
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Payload image config phải là object.")
    try:
        result = image_config.update(paths.backend_root(), body)
        logger.info("image_config updated model=%s base_url=%s api_key_env=%s default_size=%s default_quality=%s key_configured=%s", result["model"], result["base_url"], result["api_key_env"], result["default_size"], result["default_quality"], result["api_key_configured"])
        return result
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _prompt_rows(run_id: str) -> tuple[Path, list[dict]]:
    path = paths.run_dir(run_id) / "visuals" / "prompt-pack.json"
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
        if is_valid_image_file(candidate):
            return candidate
    return None


@router.get("/status")
def image_status() -> dict:
    try:
        import openai  # noqa: F401

        sdk_ready = True
    except ImportError:
        sdk_ready = False
    backend_root = paths.backend_root()
    supported_models = image_config.get_supported_models(backend_root)
    return {"available": _has_key() and sdk_ready, "has_api_key": _has_key(), "sdk_ready": sdk_ready, "model": (list(supported_models) or [DEFAULT_MODEL])[0], "models": list(supported_models), "sizes": list(SUPPORTED_SIZES), "qualities": list(SUPPORTED_QUALITIES), "active_job": image_runner.active_job(), "busy": image_runner.busy()}


@router.get("/runs/{run_id}/prompts")
def image_prompts(run_id: str) -> dict:
    _check_run_id(run_id)
    _require_state(run_id)
    path, rows = _prompt_rows(run_id)
    run_dir = paths.run_dir(run_id)
    entries = []
    for row in rows:
        image_id = str(row["image_id"])
        output = _find_image(run_dir, image_id)
        entries.append({"image_id": image_id, "prompt": str(row.get("prompt", "")), "exists": output is not None, "path": "video-build/images/%s" % output.name if output else None, "size_bytes": output.stat().st_size if output else None})
    return {"run_id": run_id, "prompt_pack_exists": path.is_file(), "images_dir": "video-build/images", "total": len(entries), "generated": sum(1 for row in entries if row["exists"]), "prompts": entries, "active_job": image_runner.active_job(), "busy": image_runner.busy()}


@router.post("/runs/{run_id}/generate", status_code=202)
def start_image_generation(run_id: str, body: dict) -> dict:
    _check_run_id(run_id)
    _require_state(run_id)
    body = body or {}
    raw = body.get("images")
    _, rows = _prompt_rows(run_id)
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
    configured = image_config.load(paths.backend_root())
    model = str(body.get("model") or configured["model"])
    size = str(body.get("size") or configured["default_size"])
    quality = str(body.get("quality") or configured["default_quality"])
    supported_models = image_config.get_supported_models(paths.backend_root())
    if model not in supported_models or size not in SUPPORTED_SIZES or quality not in SUPPORTED_QUALITIES:
        bad = []
        if model not in supported_models:
            bad.append(f"model '{model}' (supported: {', '.join(supported_models)})")
        if size not in SUPPORTED_SIZES:
            bad.append(f"size '{size}'")
        if quality not in SUPPORTED_QUALITIES:
            bad.append(f"quality '{quality}'")
        raise HTTPException(status_code=400, detail="Không được hỗ trợ: %s" % "; ".join(bad))
    if not _has_key():
        raise HTTPException(status_code=400, detail={"message": "Thiếu OPENAI_API_KEY trên API server.", "key": "images.noKey"})
    if image_runner.busy():
        active = image_runner.active_job()
        raise HTTPException(status_code=409, detail={"message": "Một job gen ảnh đang chạy.", "key": "busy", "active_job_id": active.get("id") if active else None})
    if body.get("skip_existing", True):
        indices = [item for item in indices if _find_image(paths.run_dir(run_id), item) is None]
    if not indices:
        logger.info("image_generation skipped run=%s reason=all_images_exist", run_id)
        return {"job_id": None, "run_id": run_id, "status": "complete", "images": [], "message": "Tất cả ảnh đã tồn tại."}
    try:
        concurrency = body.get("concurrency", 1)
        concurrency = concurrency if isinstance(concurrency, int) and not isinstance(concurrency, bool) and 1 <= concurrency <= 4 else 1
        job = image_runner.start(run_id, paths.run_dir(run_id), indices, model, size, quality, concurrency=concurrency)
    except ImageBusyError as exc:
        raise HTTPException(status_code=409, detail={"message": str(exc), "key": "busy", "active_job_id": exc.job_id}) from exc
    logger.info("image_generation accepted job=%s run=%s model=%s size=%s quality=%s images=%d", job["id"], run_id, model, size, quality, len(indices))
    return {"job_id": job["id"], "run_id": run_id, "images": indices, "model": model, "size": size, "quality": quality, "started_at": job["started_at"]}


@router.get("/jobs/{job_id}")
def image_job(job_id: str) -> dict:
    status = image_runner.job_status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy image job.")
    return status


@router.get("/jobs/{job_id}/log")
def image_job_log(job_id: str, offset: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=2000)) -> dict:
    return image_runner.get_log(job_id, offset, limit)


@router.post("/jobs/{job_id}/cancel")
def image_job_cancel(job_id: str) -> dict:
    return {"cancelled": image_runner.cancel(job_id), "job_id": job_id}
