"""API Gen video Veo (image-to-video) for legacy or channel-scoped runs."""
from __future__ import annotations

import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from . import paths
from .routes import _check_job_id, _check_run_id, _require_scoped_channel, _require_state, _run_path
from .veo_runner import VeoBusyError, veo_gen_command, veo_runner

router = APIRouter(prefix="/api/veo")

_IDX_RE = re.compile(r"^\d{1,3}$")

# Model Veo mặc định + danh sách cho dropdown UI.
# Google đã bỏ veo-3.0-* và veo-2.0-* khỏi v1beta (404 NOT_FOUND cho
# predictLongRunning); chỉ còn 3.1. Kiểm tra lại bằng:
#   client.models.list() -> lọc supported_actions chứa 'predictLongRunning'
DEFAULT_MODEL = os.environ.get("VEO_MODEL", "veo-3.1-generate-preview")
AVAILABLE_MODELS = [
    "veo-3.1-generate-preview",
    "veo-3.1-fast-generate-preview",
    "veo-3.1-lite-generate-preview",
]

_IMAGE_EXTS = ("png", "jpg", "jpeg", "webp")
_KEY_NAMES = ("GEMINI_API_KEY", "GOOGLE_API_KEY")


def _scope_kwargs(user_id: str | None, channel_id: str | None) -> tuple[str | None, str | None]:
    if bool(user_id) != bool(channel_id):
        raise HTTPException(status_code=400, detail="user_id và channel_id phải được truyền cùng nhau")
    return user_id, channel_id


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


def _has_api_key() -> bool:
    """Key có sẵn cho subprocess không — env server hoặc .env backend root."""
    if any(os.environ.get(k) for k in _KEY_NAMES):
        return True
    env_file = paths.backend_root() / ".env"
    if not env_file.is_file():
        return False
    try:
        from dotenv import dotenv_values

        values = dotenv_values(env_file)
    except Exception:
        return False
    return any(values.get(k) for k in _KEY_NAMES)


def _busy_409(exc: VeoBusyError) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"message": str(exc), "key": "busy", "active_job_id": exc.job_id},
    )


def _find_image(images_dir: Path, idx: str) -> Path | None:
    for ext in _IMAGE_EXTS:
        p = images_dir / ("IMG-%s.%s" % (idx, ext))
        if p.is_file():
            return p
    return None


def _parse_prompts_video(prompts_file: Path) -> list[dict]:
    """Đọc prompts-video.txt → [{index, motion, prompt}] theo đúng thứ tự file."""
    out: list[dict] = []
    if not prompts_file.is_file():
        return out
    for raw in prompts_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "|" not in line:
            continue
        img_part, rest = line.split("|", 1)
        img_key = img_part.strip()
        if not img_key.startswith("IMG-"):
            continue
        idx = img_key[4:]
        if not _IDX_RE.match(idx):
            continue
        motion, prompt = "", rest.strip()
        for sep in (" — ", " - "):
            if sep in rest:
                motion, prompt = rest.split(sep, 1)
                motion, prompt = motion.strip(), prompt.strip()
                break
        out.append({"index": idx, "motion": motion, "prompt": prompt})
    return out


# --------------------------------------------------------------- trạng thái


@router.get("/status")
def veo_status(user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> dict:
    """Trạng thái Veo trong namespace được yêu cầu."""
    _require_scoped_channel(user_id, channel_id)
    _scope_kwargs(user_id, channel_id)
    has_key = _has_api_key()
    try:
        import google.genai  # noqa: F401

        sdk_ready = True
    except ImportError:
        sdk_ready = False
    return {
        "available": has_key and sdk_ready,
        "has_api_key": has_key,
        "sdk_ready": sdk_ready,
        "default_model": DEFAULT_MODEL,
        "models": AVAILABLE_MODELS,
        "active_job": veo_runner.active_job(user_id=user_id, channel_id=channel_id),
        "busy": veo_runner.busy(user_id=user_id, channel_id=channel_id),
    }


@router.get("/runs/{run_id}/candidates")
def veo_candidates(
    run_id: str,
    user_id: str | None = Query(None),
    channel_id: str | None = Query(None),
) -> dict:
    """Ảnh ứng viên image-to-video của run: prompt, ảnh nguồn, clip đã có."""
    run_dir = _require_run(run_id, user_id, channel_id)
    images_dir = run_dir / "video-build" / "images"
    clips_dir = run_dir / "video-build" / "clips"
    prompts_file = run_dir / "visuals" / "prompts" / "prompts-video.txt"

    entries = _parse_prompts_video(prompts_file)
    candidates = []
    for e in entries:
        idx = e["index"]
        img = _find_image(images_dir, idx)
        clip = clips_dir / ("IMG-%s.mp4" % idx)
        clip_exists = clip.is_file()
        candidates.append(
            {
                "index": idx,
                "name": "IMG-%s" % idx,
                "motion": e["motion"],
                "prompt": e["prompt"],
                "image_exists": img is not None,
                "image_path": ("video-build/images/%s" % img.name) if img else None,
                "clip_exists": clip_exists,
                "clip_path": ("video-build/clips/%s" % clip.name) if clip_exists else None,
                "clip_size_bytes": clip.stat().st_size if clip_exists else None,
            }
        )

    ready = [c for c in candidates if c["image_exists"]]
    return {
        "run_id": run_id,
        "prompts_file_exists": prompts_file.is_file(),
        "images_dir": "video-build/images",
        "clips_dir": "video-build/clips",
        "candidates": candidates,
        "total": len(candidates),
        "images_ready": len(ready),
        "clips_done": len([c for c in candidates if c["clip_exists"]]),
        "active_job": veo_runner.active_job(user_id=user_id, channel_id=channel_id),
        "busy": veo_runner.busy(user_id=user_id, channel_id=channel_id),
    }


# ------------------------------------------------------------------- job


@router.post("/runs/{run_id}/generate", status_code=202)
def veo_generate(
    run_id: str,
    body: dict,
    user_id: str | None = Query(None),
    channel_id: str | None = Query(None),
) -> dict:
    """Bắt đầu job gen clip cho các ảnh được chọn."""
    run_dir = _require_run(run_id, user_id, channel_id)
    body = body or {}

    raw = body.get("images") or []
    if not isinstance(raw, list) or not raw:
        raise HTTPException(status_code=400, detail={"message": "Cần chọn ít nhất một ảnh.", "key": "veo.noImages"})
    indices: list[str] = []
    for item in raw:
        s = str(item).strip()
        if s.startswith("IMG-"):
            s = s[4:]
        if not _IDX_RE.match(s):
            raise HTTPException(status_code=400, detail={"message": "Chỉ số ảnh không hợp lệ: %s" % item, "key": "veo.badIndex"})
        if s not in indices:
            indices.append(s)

    if len(indices) > 20:
        raise HTTPException(status_code=400, detail={"message": "Tối đa 20 ảnh mỗi job (Veo tốn thời gian/quota).", "key": "veo.tooMany"})

    model = str(body.get("model") or DEFAULT_MODEL)
    if model not in AVAILABLE_MODELS:
        raise HTTPException(status_code=400, detail={"message": "Model không hỗ trợ: %s" % model, "key": "veo.badModel"})
    if not _has_api_key():
        raise HTTPException(status_code=400, detail={"message": "Thiếu GEMINI_API_KEY / GOOGLE_API_KEY trong .env.", "key": "veo.noKey"})

    images_dir = run_dir / "video-build" / "images"
    missing = [i for i in indices if _find_image(images_dir, i) is None]
    if missing:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Thiếu ảnh nguồn trong video-build/images/: %s" % ", ".join("IMG-%s" % i for i in missing),
                "key": "veo.missingImages",
                "missing": missing,
            },
        )

    argv = veo_gen_command(run_dir, indices, model)
    if body.get("skip_existing"):
        argv.append("--skip-existing")
    try:
        job = veo_runner.start(run_id, argv, paths.backend_root(), user_id=user_id, channel_id=channel_id)
    except VeoBusyError as exc:
        raise _busy_409(exc) from exc

    return {
        "job_id": job["id"],
        "run_id": run_id,
        "images": indices,
        "model": model,
        "started_at": job["started_at"],
        "log_path": job["log_path"],
    }


@router.get("/jobs/{job_id}")
def veo_job(job_id: str, user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> dict:
    _check_job_id(job_id)
    _require_scoped_channel(user_id, channel_id)
    _scope_kwargs(user_id, channel_id)
    status = veo_runner.job_status(job_id, user_id=user_id, channel_id=channel_id)
    if status is None:
        raise HTTPException(status_code=404, detail={"message": "Không tìm thấy job.", "key": "notFound"})
    return status


@router.get("/jobs/{job_id}/log")
def veo_job_log(
    job_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=2000),
    user_id: str | None = Query(None),
    channel_id: str | None = Query(None),
) -> dict:
    _check_job_id(job_id)
    _require_scoped_channel(user_id, channel_id)
    _scope_kwargs(user_id, channel_id)
    return veo_runner.get_log(job_id, offset, limit, user_id=user_id, channel_id=channel_id)


@router.post("/jobs/{job_id}/cancel")
def veo_job_cancel(job_id: str, user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> dict:
    _check_job_id(job_id)
    _require_scoped_channel(user_id, channel_id)
    _scope_kwargs(user_id, channel_id)
    cancelled = veo_runner.cancel(job_id, user_id=user_id, channel_id=channel_id)
    return {"cancelled": cancelled, "job_id": job_id}
