"""API for generating SRT from a run script and its narration audio."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from ..video.timeline import find_audio_file
from . import paths
from .routes import _check_job_id, _check_run_id, _require_scoped_channel, _require_state, _run_path
from .srt_runner import SrtBusyError, srt_runner

router = APIRouter(prefix="/api/srt")
MODELS = ("tiny", "base", "small", "medium", "large-v3")
DEVICES = ("cpu", "auto", "cuda")
MODES = ("fast", "accurate")


def _scope_kwargs(user_id: str | None, channel_id: str | None) -> tuple[str | None, str | None]:
    if bool(user_id) != bool(channel_id):
        raise HTTPException(status_code=400, detail="user_id và channel_id phải được truyền cùng nhau")
    return user_id, channel_id


def _run_dir(run_id: str, user_id: str | None = None, channel_id: str | None = None):
    if user_id and channel_id:
        return paths.channel_run_dir(user_id, channel_id, run_id)
    return _run_path(run_id, _require_state(run_id, user_id, channel_id))


def _require_run(run_id: str, user_id: str | None, channel_id: str | None):
    _check_run_id(run_id)
    user_id, channel_id = _scope_kwargs(user_id, channel_id)
    _require_scoped_channel(user_id, channel_id)
    _require_state(run_id, user_id, channel_id)
    return _run_dir(run_id, user_id, channel_id)


def _run_inputs(run_id: str, user_id: str | None, channel_id: str | None) -> tuple[dict, Path]:
    run_dir = _require_run(run_id, user_id, channel_id)
    script = run_dir / "script" / "script.txt"
    audio = find_audio_file(run_dir / "audio")
    return {"script": script, "audio": audio}, run_dir


@router.get("/status")
def srt_status(user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> dict:
    _require_scoped_channel(user_id, channel_id)
    _scope_kwargs(user_id, channel_id)
    try:
        import faster_whisper  # noqa: F401
        sdk_ready = True
    except ImportError:
        sdk_ready = False
    try:
        import stable_whisper  # noqa: F401
        accurate_ready = True
    except ImportError:
        accurate_ready = False
    return {"sdk_ready": sdk_ready, "accurate_ready": accurate_ready, "models": list(MODELS), "devices": list(DEVICES), "modes": list(MODES), "active_job": srt_runner.active_job(user_id=user_id, channel_id=channel_id), "busy": srt_runner.busy(user_id=user_id, channel_id=channel_id)}


@router.get("/runs/{run_id}/inputs")
def srt_inputs(run_id: str, user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> dict:
    inputs, run_dir = _run_inputs(run_id, user_id, channel_id)
    output = run_dir / "subtitles" / "subtitles.srt"
    return {"run_id": run_id, "script_exists": inputs["script"].is_file(), "script_path": "script/script.txt" if inputs["script"].is_file() else None, "audio_exists": inputs["audio"] is not None, "audio_path": "audio/%s" % inputs["audio"].name if inputs["audio"] else None, "audio_size_bytes": inputs["audio"].stat().st_size if inputs["audio"] else None, "srt_exists": output.is_file(), "srt_path": "subtitles/subtitles.srt" if output.is_file() else None, "active_job": srt_runner.active_job(user_id=user_id, channel_id=channel_id), "busy": srt_runner.busy(user_id=user_id, channel_id=channel_id)}


@router.post("/runs/{run_id}/generate", status_code=202)
def start_srt(run_id: str, body: dict, user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> dict:
    inputs, run_dir = _run_inputs(run_id, user_id, channel_id)
    if not inputs["script"].is_file():
        raise HTTPException(status_code=400, detail="Run chưa có script/script.txt.")
    if inputs["audio"] is None:
        raise HTTPException(status_code=400, detail="Chưa có audio ghép trong audio/. Hãy gen TTS trước.")
    body = body or {}
    model = str(body.get("model") or "large-v3")
    device = str(body.get("device") or "cpu")
    mode = str(body.get("mode") or "accurate")
    try:
        max_chars = int(body.get("max_chars", 24))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="max_chars phải là số.") from exc
    if model not in MODELS or device not in DEVICES or mode not in MODES or not 8 <= max_chars <= 50:
        raise HTTPException(status_code=400, detail="model/device/mode/max_chars không hợp lệ.")
    if mode == "accurate":
        try:
            import stable_whisper  # noqa: F401
        except ImportError as exc:
            raise HTTPException(status_code=400, detail="Chưa cài stable-ts cho chế độ forced alignment.") from exc
    if srt_runner.busy(user_id=user_id, channel_id=channel_id):
        active = srt_runner.active_job(user_id=user_id, channel_id=channel_id)
        raise HTTPException(status_code=409, detail={"message": "Một job gen SRT đang chạy.", "key": "busy", "active_job_id": active.get("id") if active else None})
    try:
        job = srt_runner.start(run_id, run_dir, inputs["audio"], model, device, mode, max_chars, user_id=user_id, channel_id=channel_id)
    except SrtBusyError as exc:
        raise HTTPException(status_code=409, detail={"message": str(exc), "key": "busy", "active_job_id": exc.job_id}) from exc
    return {"job_id": job["id"], "run_id": run_id, "model": model, "device": device, "mode": mode, "output_path": job["output_path"], "started_at": job["started_at"]}


@router.get("/jobs/{job_id}")
def srt_job(job_id: str, user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> dict:
    _check_job_id(job_id)
    _require_scoped_channel(user_id, channel_id)
    _scope_kwargs(user_id, channel_id)
    status = srt_runner.job_status(job_id, user_id=user_id, channel_id=channel_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy SRT job.")
    return status


@router.get("/jobs/{job_id}/log")
def srt_job_log(job_id: str, offset: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=2000), user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> dict:
    _check_job_id(job_id)
    _require_scoped_channel(user_id, channel_id)
    _scope_kwargs(user_id, channel_id)
    return srt_runner.get_log(job_id, offset, limit, user_id=user_id, channel_id=channel_id)


@router.post("/jobs/{job_id}/cancel")
def srt_job_cancel(job_id: str, user_id: str | None = Query(None), channel_id: str | None = Query(None)) -> dict:
    _check_job_id(job_id)
    _require_scoped_channel(user_id, channel_id)
    _scope_kwargs(user_id, channel_id)
    return {"cancelled": srt_runner.cancel(job_id, user_id=user_id, channel_id=channel_id), "job_id": job_id}
