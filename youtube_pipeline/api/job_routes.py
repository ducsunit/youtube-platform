"""API tổng hợp mọi worker nền đang chạy + kill trực tiếp.

GET  /api/jobs/active                — danh sách job của TẤT CẢ runner
POST /api/jobs/{kind}/{job_id}/cancel — SIGTERM process group của job

Job được spawn detached (start_new_session) nên đây là nơi duy nhất để biết
"đang có gì chạy ngầm" — kể cả job mồ côi sau khi API server restart.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException

from . import paths
from .build_runner import build_runner
from .datapull import _pid_alive, _read_pid_info, data_runner
from .image_runner import image_runner
from .runner import runner as pipeline_runner
from .srt_runner import srt_runner
from .veo_runner import veo_runner

router = APIRouter(prefix="/api/jobs")

# ---- progress per kind -------------------------------------------------------

_BUILD_SEG_RE = re.compile(r"\[(\d+)/(\d+)\] dang rap")
_BUILD_DONE_RE = re.compile(r"\[(\d+)/(\d+)\] xong")


def _read_tail(path, limit: int = 400_000) -> str:
    """Đọc phần cuối file log (đủ để tìm marker mới nhất, không đọc cả file khổng lồ)."""
    if not path:
        return ""
    p = Path(path)
    if not p.is_file():
        return ""
    try:
        size = p.stat().st_size
        with p.open("rb") as fh:
            if size > limit:
                fh.seek(size - limit)
            return fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _progress_pipeline(run_id: str) -> dict | None:
    """% stage đã pass trong run_state.json."""
    try:
        state = json.loads(paths.run_state_path(run_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    records = state.get("stage_records") or {}
    total = len(records)
    if not total:
        return None
    done = sum(
        1 for v in records.values()
        if isinstance(v, dict) and v.get("status") in ("passed", "complete", "done")
    )
    detail = "%d/%d stages" % (done, total)
    return {"percent": 100 if done >= total else min(99, round(done / total * 100)), "detail": detail}


def _progress_tts(run_id: str) -> dict | None:
    """% chunk mp3 đã gen theo manifest; merge xong = 100%."""
    run_root = paths.run_dir(run_id)
    if (run_root / "audio" / "narration-merged.mp3").is_file():
        return {"percent": 100, "detail": "merged"}
    try:
        manifest = json.loads((run_root / "script/audio-chunks/manifest.json").read_text(encoding="utf-8"))
        chunks = manifest.get("chunks") or []
    except (OSError, ValueError):
        return None
    if not chunks:
        return None
    done = sum(1 for c in chunks if (run_root / str(c.get("audio_output") or "")).is_file())
    return {"percent": min(99, round(done / len(chunks) * 100)), "detail": "%d/%d chunks" % (done, len(chunks))}


def _progress_build(log_text: str) -> dict | None:
    # Marker "xong" (in khi segment render hoàn tất) chính xác hơn "dang rap"
    # khi render song song — ưu tiên dùng nếu có.
    done_matches = _BUILD_DONE_RE.findall(log_text)
    if done_matches:
        k, n = int(done_matches[-1][0]), int(done_matches[-1][1])
        done = len({m[0] for m in done_matches})
        if n > 0:
            return {"percent": min(90, round(done / n * 90)), "detail": "segment %d/%d" % (done, n)}
    matches = _BUILD_SEG_RE.findall(log_text)
    if matches:
        k, n = int(matches[-1][0]), int(matches[-1][1])
        if n > 0:
            return {"percent": min(90, round(k / n * 90)), "detail": "segment %d/%d" % (k, n)}
    if "cue đã burn" in log_text or "cue đã burn" in log_text:
        return {"percent": 99, "detail": "burn phụ đề"}
    if "Rap xong tat ca segment" in log_text or "dang ghep video" in log_text:
        return {"percent": 93, "detail": "ghép + mux audio"}
    # Fallback thô cho job spawn bằng code cũ (log không có marker segment):
    if "Hoàn tất:" in log_text:
        return {"percent": 100, "detail": "xong"}
    if "Chạy build-video.py" in log_text:
        return {"percent": 40, "detail": "đang rap video"}
    if "Cắt audio" in log_text:
        return {"percent": 15, "detail": "cắt audio theo section"}
    if "Sinh prompts-build" in log_text:
        return {"percent": 5, "detail": "chuẩn bị pack"}
    return None


def _progress_veo(log_text: str) -> dict | None:
    started = set(re.findall(r"\[IMG-(\d+)\] (?:Ảnh:|Đã có clip|LỖI: Không tìm thấy)", log_text))
    if not started:
        return None
    done = set(re.findall(r"\[IMG-(\d+)\] (?:✓ OK|LỖI:|Đã có clip)", log_text))
    return {"percent": min(99, round(len(done) / len(started) * 100)),
            "detail": "%d/%d clips" % (len(done), len(started))}


def _progress_image(log_text: str) -> dict | None:
    match = re.search(r"images=(\d+)", log_text)
    if not match:
        return None
    total = int(match.group(1))
    done = len(re.findall(r"OUTPUT saved|SKIP image_id=|SKIP-FAILED image_id=", log_text))
    if not total:
        return None
    percent = min(99, round(done / total * 100))
    detail = "%d/%d ảnh" % (done, total)
    # ETA từ khoảng cách trung bình giữa các ảnh hoàn thành (theo timestamp log)
    stamps = re.findall(r"\[(\d{4}-[\dT:.\-+]+)\] (?:OUTPUT saved|SKIP image_id=|SKIP-FAILED)", log_text)
    if len(stamps) >= 2:
        try:
            from datetime import datetime

            times = [datetime.fromisoformat(s) for s in stamps]
            avg_sec = (times[-1] - times[0]).total_seconds() / (len(times) - 1)
            remain_min = max(0, total - done) * avg_sec / 60
            if remain_min >= 1:
                detail += " · ETA ~%d phút" % round(remain_min)
        except ValueError:
            pass
    return {"percent": percent, "detail": detail}


def _job_progress(job: dict) -> dict | None:
    kind = job.get("kind")
    if kind == "pipeline":
        return _progress_pipeline(str(job.get("id")))
    if kind == "tts":
        return _progress_tts(str(job.get("run_id") or job.get("id")))
    text = _read_tail(job.get("log_path"))
    if kind == "build":
        return _progress_build(text)
    if kind == "veo":
        return _progress_veo(text)
    if kind == "image":
        return _progress_image(text)
    return None  # srt/data: chưa có marker đáng tin


def _tts_pid_path(run_id: str):
    return paths.tts_jobs_dir() / ("%s.pid" % run_id)


def _scan_tts_jobs() -> list[dict]:
    """Job TTS không có runner singleton — liệt kê bằng pid file."""
    jobs: list[dict] = []
    directory = paths.tts_jobs_dir()
    if not directory.is_dir():
        return jobs
    for pid_file in sorted(directory.glob("*.pid")):
        info = _read_pid_info(pid_file)
        if info is None or not _pid_alive(info["pid"]):
            pid_file.unlink(missing_ok=True)
            continue
        run_id = str(info.get("run_id") or pid_file.stem)
        jobs.append({
            "id": run_id,
            "kind": "tts",
            "run_id": run_id,
            "started_at": None,
            "log_path": str(paths.logs_dir() / ("%s-tts.log" % run_id)),
            "orphaned": False,
        })
    return jobs


@router.get("/active")
def active_jobs() -> dict:
    """Mọi job nền đang chạy: pipeline, tts, build, veo, image, srt, data."""
    jobs: list[dict] = []

    pipeline = pipeline_runner.active_run()
    if pipeline:
        jobs.append({
            "id": pipeline["run_id"],
            "kind": "pipeline",
            "run_id": pipeline["run_id"],
            "started_at": None,
            "log_path": str(paths.log_path(pipeline["run_id"])),
            "orphaned": bool(pipeline.get("orphaned")),
        })

    jobs.extend(_scan_tts_jobs())

    build = build_runner.active_job()
    if build:
        jobs.append({"id": build["id"], "kind": "build", "run_id": build.get("run_id"),
                     "started_at": build.get("started_at"), "log_path": build.get("log_path"),
                     "orphaned": bool(build.get("orphaned"))})

    veo = veo_runner.active_job()
    if veo and veo.get("id"):
        jobs.append({"id": veo["id"], "kind": "veo", "run_id": veo.get("run_id"),
                     "started_at": veo.get("started_at"), "log_path": veo.get("log_path"),
                     "orphaned": bool(veo.get("orphaned"))})

    image = image_runner.active_job()
    if image and image.get("id") and image.get("status") == "running":
        jobs.append({"id": image["id"], "kind": "image", "run_id": image.get("run_id"),
                     "started_at": image.get("started_at"), "log_path": image.get("log_path"),
                     "orphaned": bool(image.get("orphaned"))})

    srt = srt_runner.active_job()
    if srt and srt.get("id") and srt.get("status") == "running":
        jobs.append({"id": srt["id"], "kind": "srt", "run_id": srt.get("run_id"),
                     "started_at": srt.get("started_at"), "log_path": srt.get("log_path"),
                     "orphaned": bool(srt.get("orphaned"))})

    data = data_runner.active_job()
    if data:
        jobs.append({"id": data["id"], "kind": "data", "run_id": None,
                     "started_at": data.get("started_at"),
                     "log_path": data.get("log_path"),
                     "orphaned": bool(data.get("orphaned"))})

    # Orphan branch của một số runner không trả log_path — dựng từ jobs dir
    # để progress vẫn đọc log được sau khi server restart.
    log_dirs = {
        "build": paths.build_jobs_dir,
        "veo": paths.veo_jobs_dir,
        "image": paths.image_jobs_dir,
        "srt": paths.srt_jobs_dir,
    }
    for job in jobs:
        if not job.get("log_path") and job["kind"] in log_dirs:
            job["log_path"] = str(log_dirs[job["kind"]]() / ("%s.log" % job["id"]))

    for job in jobs:
        try:
            job["progress"] = _job_progress(job)
        except Exception:  # noqa: BLE001 — progress là tiện ích, không được làm hỏng list
            job["progress"] = None

    return {"jobs": jobs, "busy": len(jobs) > 0}


_CANCELERS = {
    # pipeline/tts dùng run_id làm job_id; còn lại là job id của runner tương ứng.
    "pipeline": lambda job_id: pipeline_runner.cancel(job_id),
    "tts": lambda job_id: _cancel_tts_job(job_id),
    "build": build_runner.cancel,
    "veo": veo_runner.cancel,
    "image": image_runner.cancel,
    "srt": srt_runner.cancel,
    "data": data_runner.cancel,
}


def _cancel_tts_job(run_id: str) -> bool:
    from .routes import _cancel_tts_job as cancel_tts

    return cancel_tts(run_id)


@router.post("/{kind}/{job_id}/cancel")
def cancel_background_job(kind: str, job_id: str) -> dict:
    canceller = _CANCELERS.get(kind)
    if canceller is None:
        raise HTTPException(status_code=404, detail="Không biết job loại '%s'." % kind)
    cancelled = bool(canceller(job_id))
    return {"cancelled": cancelled, "kind": kind, "job_id": job_id}
