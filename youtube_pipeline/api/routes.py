"""REST API cho resource pack pipeline — xem & chạy pipeline từ web UI.

Ground truth trạng thái run luôn là runs/<run_id>/run_state.json trên đĩa
(do CLI tự ghi). Server chỉ spawn subprocess, đọc state/artifacts/log và quản
lý guard "chỉ một pipeline đang chạy".
"""
from __future__ import annotations

import json
import os
import re
import signal
import socket
import ssl
import shutil
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse

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


# ---- Channel profiles (multi-channel) --------------------------------------

_CHANNEL_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _channels_base() -> Path:
    return paths.backend_root() / "config" / "channels"


@router.get("/channels")
def list_channels() -> dict:
    """Danh sách channel profiles cho UI (dropdown tạo run + trang quản lý)."""
    from youtube_pipeline.channel_profile import load_channel_profile

    base = _channels_base()
    items = []
    if base.is_dir():
        for folder in sorted(base.iterdir()):
            path = folder / "profile.json"
            if not folder.is_dir() or not path.is_file():
                continue
            try:
                profile = load_channel_profile(base.parent.parent, folder.name)
            except Exception as exc:  # malformed profile must not break listing
                items.append({
                    "channel_id": folder.name,
                    "display_name": folder.name,
                    "language": None,
                    "valid": False,
                    "error": str(exc),
                })
                continue
            items.append({
                "channel_id": folder.name,
                "display_name": str(profile.get("display_name") or folder.name),
                "language": profile.get("language"),
                "youtube_channel_ids": profile.get("youtube_channel_ids") or [],
                "has_overrides": bool(
                    profile.get("competitor") or profile.get("sources")
                    or profile.get("claims") or profile.get("style_locks")
                ),
                "valid": True,
            })
    return {"channels": items}


@router.get("/channels/{channel_id}")
def get_channel(channel_id: str) -> dict:
    if not _CHANNEL_ID_RE.match(channel_id):
        raise HTTPException(status_code=400, detail="channel id không hợp lệ")
    path = _channels_base() / channel_id / "profile.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Không tìm thấy channel profile.")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="Profile không phải JSON hợp lệ: %s" % exc)


@router.put("/channels/{channel_id}")
def save_channel(channel_id: str, body: dict) -> dict:
    """Lưu profile; validate bằng loader trước khi ghi để UI không lưu được rác."""
    from youtube_pipeline.channel_profile import load_channel_profile

    if not _CHANNEL_ID_RE.match(channel_id):
        raise HTTPException(status_code=400, detail="channel id không hợp lệ")
    if not isinstance(body, dict) or not body:
        raise HTTPException(status_code=400, detail="Profile body phải là JSON object khác rỗng.")
    base = _channels_base()
    target = base / channel_id / "profile.json"
    # Validate through the same loader the pipeline uses before writing anything.
    import tempfile
    try:
        probe_dir = Path(tempfile.mkdtemp(prefix="chan-validate-"))
        (probe_dir / "config" / "channels" / channel_id).mkdir(parents=True)
        probe = probe_dir / "config" / "channels" / channel_id / "profile.json"
        probe.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
        load_channel_profile(probe_dir, channel_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        shutil.rmtree(probe_dir, ignore_errors=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"saved": True, "path": str(target)}



# ---- VOICEVOX TTS ------------------------------------------------------------

_TTS_STALE_SECONDS = 3600


def _voicevox_base() -> str:
    return os.getenv("VOICEVOX_URL", "http://127.0.0.1:50021")


def _tts_pid_path(run_id: str) -> Path:
    return paths.tts_jobs_dir() / ("%s.pid" % run_id)


def _read_tts_pid(run_id: str) -> Optional[int]:
    """Đọc pid của job TTS từ pid file (None nếu file hỏng/không có)."""
    path = _tts_pid_path(run_id)
    if not path.is_file():
        return None
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
        pid = int(info.get("pid"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return pid if pid > 0 else None


def _tts_pid_alive(run_id: str) -> bool:
    """Job TTS còn sống thật không — dựa trên pid file, không tin status file."""
    pid = _read_tts_pid(run_id)
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _cancel_tts_job(run_id: str) -> bool:
    """Kill job TTS của run (kể cả orphan) + cập nhật status cho UI."""
    from .datapull import kill_process_group

    pid = _read_tts_pid(run_id)
    killed = False
    if pid is not None:
        try:
            os.kill(pid, 0)
            killed = kill_process_group(pid)
        except ProcessLookupError:
            killed = False
    _tts_pid_path(run_id).unlink(missing_ok=True)
    if killed or _tts_status_from_files(paths.run_dir(run_id)).get("status") == "running":
        status_path = paths.run_dir(run_id) / "audio" / "tts-status.json"
        current: dict = {}
        if status_path.is_file():
            try:
                current = json.loads(status_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                current = {}
        current["status"] = "cancelled"
        current["finished_at"] = _now_iso()
        current.setdefault("error", "Job TTS đã bị hủy.")
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return killed


def _tts_status_from_files(run_root: Path) -> dict:
    status_path = run_root / "audio" / "tts-status.json"
    payload: dict = {}
    if status_path.is_file():
        try:
            payload = json.loads(status_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
    summary_path = run_root / "audio" / "tts-summary.json"
    if summary_path.is_file():
        try:
            payload.setdefault("summary", json.loads(summary_path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass
    if payload.get("status") == "running":
        started_at = str(payload.get("started_at") or "")
        try:
            from datetime import datetime as _dt
            age = (_dt.now().astimezone() - _dt.fromisoformat(started_at)).total_seconds()
            if age > _TTS_STALE_SECONDS:
                payload = {**payload, "status": "failed", "error": "job quá 60 phút không phản hồi."}
        except ValueError:
            pass
    return payload


@router.get("/tts/voices")
def tts_voices() -> dict:
    """Danh sách giọng từ VOICEVOX engine local (offline -> available=False)."""
    import urllib.request

    base = _voicevox_base()
    try:
        raw = urllib.request.urlopen(base.rstrip("/") + "/speakers", timeout=3)
        speakers = json.loads(raw.read())
    except Exception:
        return {"available": False, "base_url": base, "voices": []}
    voices = [
        {
            "character": sp.get("name", ""),
            "styles": [{"id": st.get("id"), "name": st.get("name", "")} for st in sp.get("styles", [])],
        }
        for sp in speakers
    ]
    return {"available": True, "base_url": base, "voices": voices}


@router.post("/tts/preview")
def tts_preview(body: dict) -> Response:
    """Synthesize đoạn ngắn để nghe thử giọng ngay trên UI."""
    import urllib.parse
    import urllib.request

    speaker = int(body.get("speaker") or 21)
    text = str(body.get("text") or "こんにちは。これはボイスのテストです。").strip()[:300]
    speed = float(body.get("speed_scale") or 1.0)
    intonation = float(body.get("intonation_scale") or 0.85)
    base = _voicevox_base()

    params = urllib.parse.urlencode({"speaker": speaker, "text": text})
    req = urllib.request.Request(
        base.rstrip("/") + "/audio_query?" + params,
        data=b"", headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        query = json.loads(urllib.request.urlopen(req, timeout=30).read())
        query.update({
            "speedScale": speed, "pitchScale": 0.0, "intonationScale": intonation,
            "prePhonemeLength": 0.4, "postPhonemeLength": 0.6, "outputSamplingRate": 44100,
        })
        synth = urllib.request.Request(
            base.rstrip("/") + f"/synthesis?{urllib.parse.urlencode({'speaker': speaker})}",
            data=json.dumps(query).encode(),
            headers={"Content-Type": "application/json", "Accept": "audio/wav"},
        )
        wav = urllib.request.urlopen(synth, timeout=120).read()
    except Exception as exc:
        raise HTTPException(status_code=409, detail=f"VOICEVOX offline hoặc lỗi engine: {exc}")
    return Response(content=wav, media_type="audio/wav")


@router.post("/runs/{run_id}/tts")
def start_run_tts(run_id: str, body: dict | None = None) -> dict:
    """Spawn worker regen audio VOICEVOX cho run có sẵn."""
    import subprocess

    _check_run_id(run_id)
    _require_state(run_id)
    run_root = paths.run_dir(run_id)
    if not (run_root / "script/audio-chunks/manifest.json").is_file():
        raise HTTPException(status_code=400, detail="Run chưa có script/audio-chunks/manifest.json.")
    current = _tts_status_from_files(run_root)
    if current.get("status") == "running":
        if _tts_pid_alive(run_id):
            raise HTTPException(status_code=409, detail="Job TTS đang chạy.")
        # status nói running nhưng process đã chết (crash / server restart
        # với job legacy không pid file) — tự dọn thay vì chặn vĩnh viễn.
        _cancel_tts_job(run_id)

    body = body or {}
    force = bool(body.get("force", False))

    logs_dir = paths.backend_root() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / ("%s-tts.log" % run_id)
    argv = [
        sys.executable, "-m", "youtube_pipeline.api.tts_job",
        "--run-id", run_id, "--output-dir", str(run_root),
    ]
    if force:
        argv.append("--force")
    handle = open(log_file, "ab")
    try:
        handle.write(("=== start tts %s ===\n" % _now_iso()).encode("utf-8"))
        handle.flush()
        proc = subprocess.Popen(
            argv, cwd=str(paths.backend_root()), env=os.environ.copy(),
            stdout=handle, stderr=subprocess.STDOUT, start_new_session=True,
        )
    finally:
        handle.close()
    try:
        _tts_pid_path(run_id).write_text(
            json.dumps({"pid": proc.pid, "kind": "tts", "run_id": run_id}),
            encoding="utf-8",
        )
    except OSError:
        pass
    return {"started": True, "pid": proc.pid, "force": force}


@router.post("/runs/{run_id}/tts/cancel")
def cancel_run_tts_route(run_id: str) -> dict:
    """Dừng job TTS của run — kể cả orphan sau khi server restart."""
    _check_run_id(run_id)
    _require_state(run_id)
    killed = _cancel_tts_job(run_id)
    return {"cancelled": bool(killed), "run_id": run_id}


@router.get("/runs/{run_id}/tts/chunks")
def run_tts_chunks(run_id: str) -> dict:
    """Danh sách chunk TTS từ manifest kèm trạng thái file mp3 (đã gen / thiếu)."""
    _check_run_id(run_id)
    _require_state(run_id)
    run_root = paths.run_dir(run_id)
    manifest_path = run_root / "script/audio-chunks/manifest.json"
    if not manifest_path.is_file():
        return {"manifest_exists": False, "total": 0, "generated": 0, "chunks": []}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"manifest_exists": False, "total": 0, "generated": 0, "chunks": []}

    chunks_out = []
    generated = 0
    for chunk in manifest.get("chunks", []):
        rel = str(chunk.get("audio_output") or "")
        mp3 = run_root / rel if rel else None
        exists = bool(mp3 and mp3.is_file() and mp3.stat().st_size > 0)
        text_path = run_root / str(chunk.get("path") or "")
        preview = ""
        if text_path.is_file():
            preview = text_path.read_text(encoding="utf-8", errors="replace")[:220]
        if exists:
            generated += 1
        chunks_out.append({
            "id": chunk.get("id"),
            "index": chunk.get("index"),
            "chars": chunk.get("chars"),
            "path": chunk.get("path"),
            "audio_output": rel,
            "exists": exists,
            "preview": preview,
        })
    return {
        "manifest_exists": True,
        "total": len(chunks_out),
        "generated": generated,
        "merge_exists": (run_root / "audio" / "narration-merged.mp3").is_file(),
        "chunks": chunks_out,
    }


@router.get("/runs/{run_id}/tts/settings")
def run_tts_settings(run_id: str) -> dict:
    """Cấu hình giọng VOICEVOX đang đóng băng trong config_snapshot của run."""
    _check_run_id(run_id)
    _require_state(run_id)
    state_path = paths.run_dir(run_id) / "run_state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise HTTPException(status_code=500, detail="Không đọc được run_state.json: %s" % exc)
    profile = (state.get("config_snapshot") or {}).get("channel_profile") or {}
    tts = profile.get("tts") or {}
    return {
        "channel_id": str(profile.get("channel_id") or ""),
        "tts": {
            "speaker": int(tts.get("speaker", 21)),
            "speed_scale": float(tts.get("speed_scale", 1.0)),
            "pitch_scale": float(tts.get("pitch_scale", 0.0)),
            "intonation_scale": float(tts.get("intonation_scale", 0.85)),
        },
    }


@router.put("/runs/{run_id}/tts/settings")
def update_run_tts_settings(run_id: str, body: dict) -> dict:
    """Sửa cấu hình giọng của run có sẵn (ghi vào run_state.json).

    Job TTS đọc setting từ config_snapshot lúc spawn nên thay đổi áp dụng ngay
    cho lần gen tiếp theo. ``save_to_channel=true`` ghi thêm vào profile kênh
    để các run mới dùng làm mặc định.
    """
    import os as _os

    _check_run_id(run_id)
    _require_state(run_id)
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body phải là JSON object.")

    active = runner.active_run()
    if active and active.get("run_id") == run_id:
        raise HTTPException(status_code=409, detail="Run đang chạy — không sửa được cài đặt lúc này.")

    state_path = paths.run_dir(run_id) / "run_state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise HTTPException(status_code=500, detail="Không đọc được run_state.json: %s" % exc)

    snapshot = state.get("config_snapshot") or {}
    profile = snapshot.get("channel_profile") or {}
    current = profile.get("tts") or {}
    incoming = body.get("tts") or {}

    def _num(key: str, default: float, cast=float) -> float:
        raw = incoming.get(key, current.get(key, default))
        try:
            return cast(raw)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="%s phải là số." % key)

    speaker = _num("speaker", 21, int)
    speed_scale = _num("speed_scale", 1.0)
    pitch_scale = _num("pitch_scale", 0.0)
    intonation_scale = _num("intonation_scale", 0.85)
    if not (0 <= speaker <= 100000):
        raise HTTPException(status_code=400, detail="Speaker ID ngoài phạm vi hợp lệ.")
    tts_block = {
        "speaker": speaker,
        "speed_scale": round(speed_scale, 3),
        "pitch_scale": round(pitch_scale, 3),
        "intonation_scale": round(intonation_scale, 3),
    }

    profile["tts"] = tts_block
    snapshot["channel_profile"] = profile
    state["config_snapshot"] = snapshot

    tmp = state_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _os.replace(tmp, state_path)

    channel_id = str(body.get("channel_id") or profile.get("channel_id") or "")
    saved_channel = False
    if body.get("save_to_channel") and channel_id and _CHANNEL_ID_RE.match(channel_id):
        target = _channels_base() / channel_id / "profile.json"
        if target.is_file():
            chan = json.loads(target.read_text(encoding="utf-8"))
            chan["tts"] = dict(tts_block)
            target.write_text(json.dumps(chan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            saved_channel = True

    return {"saved": True, "saved_channel": saved_channel, "tts": tts_block}


@router.get("/runs/{run_id}/tts")
def run_tts_status(run_id: str) -> dict:
    _check_run_id(run_id)
    _require_state(run_id)
    run_root = paths.run_dir(run_id)
    payload = _tts_status_from_files(run_root)
    # Status file nói "running" nhưng process đã chết (crash/restart) →
    # báo failed thật thay vì treo UI vĩnh viễn.
    if payload.get("status") == "running" and not _tts_pid_alive(run_id):
        payload = {**payload, "status": "failed", "error": "Job TTS đã thoát bất ngờ (process không còn sống)."}
        _tts_pid_path(run_id).unlink(missing_ok=True)
    payload["engine_available"] = None
    try:
        from ..tts_voicevox import engine_available
        payload["engine_available"] = engine_available(_voicevox_base(), timeout=1.5)
    except Exception:
        pass
    payload["merged_exists"] = (run_root / "audio" / "narration-merged.mp3").is_file()
    payload["chunks_count"] = len(list((run_root / "audio" / "chunks").glob("*.mp3"))) \
        if (run_root / "audio" / "chunks").is_dir() else 0
    return payload


@router.get("/config")
def config() -> dict:
    root = paths.backend_root()
    from youtube_pipeline.api.datapull import list_datasets
    input_files = list_datasets()
    from youtube_pipeline.resource_pack.pipeline import VOICEVOX_PROFILE, resource_pack_stages

    active = runner.active_run()
    return {
        "backend_root": str(root),
        "runs_dir": str(paths.runs_dir()),
        "python_executable": sys.executable,
        "input_files": input_files,
        "default_input_file": "data/channels/youtube_data.json" if any(
            item["file"] == "data/channels/youtube_data.json" for item in input_files
        ) else (input_files[0]["file"] if input_files else None),
        "tts_profile": VOICEVOX_PROFILE,
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
    database = PlatformDatabase.for_run_root(paths.runs_dir() / "reindex")
    indexed = 0
    skipped = 0
    failures: list[dict[str, str]] = []
    if not paths.runs_dir().is_dir():
        return {"indexed": 0, "skipped": 0, "failures": []}
    for run_dir in sorted(paths.runs_dir().iterdir()):
        if not run_dir.is_dir() or run_dir.name.startswith("."):
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
            failures.append({"run_id": run_dir.name, "error": str(exc)})
    return {"indexed": indexed, "skipped": skipped, "failures": failures}


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


# ---- Lịch đăng video ---------------------------------------------------------

_SCHEDULE_PATH = paths.backend_root() / "data" / "publish-schedule.json"
_DEFAULT_CADENCE = {"weekdays": [1, 3, 5, 0], "time": "18:00"}  # T2·T4·T6·CN 18h


def _load_schedule() -> dict:
    if _SCHEDULE_PATH.is_file():
        try:
            data = json.loads(_SCHEDULE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("cadence", dict(_DEFAULT_CADENCE))
                data.setdefault("assignments", {})
                return data
        except json.JSONDecodeError:
            pass
    return {"schema_version": 1, "cadence": dict(_DEFAULT_CADENCE), "assignments": {}}


def _save_schedule(data: dict) -> None:
    _SCHEDULE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SCHEDULE_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _topic_status_map() -> dict[str, str]:
    try:
        from youtube_pipeline.topic_history import load_history

        return {
            str(row.get("run_id")): str(row.get("status") or "")
            for row in load_history(paths.backend_root())
            if row.get("run_id")
        }
    except Exception:  # noqa: BLE001
        return {}


def _auto_assign_slots(data: dict, runs: list[dict]) -> dict:
    """Tự gán slot cadence cho run hoàn tất chưa có ngày — người dùng chỉ việc
    tải video + lên lịch YouTube Studio. Chạy lazy mỗi lần load lịch.

    - FIFO: run hoàn tất trước nhận slot trước.
    - Quá giờ đăng hôm nay → bắt đầu từ ngày mai.
    - Run bị "Bỏ khỏi lịch" (skipped) không tự gán lại; gán tay sẽ bỏ skip.
    """
    from datetime import datetime as _dt

    cadence_cfg = data.get("cadence") or {}
    cadence = {int(x) for x in (cadence_cfg.get("weekdays") or [1, 3, 5, 0])}
    time_str = str(cadence_cfg.get("time") or "18:00")
    try:
        hh, mm = (int(x) for x in time_str.split(":")[:2])
    except ValueError:
        hh, mm = 18, 0
    now = _dt.now()
    start = now.date() + (timedelta(days=1) if (now.hour, now.minute) >= (hh, mm) else timedelta(0))

    assignments = data.setdefault("assignments", {})
    skipped = set(data.get("skipped") or [])
    taken = {v.get("date") for v in assignments.values() if isinstance(v, dict) and v.get("date")}
    pending = [
        r for r in runs
        if r.get("topic_status") not in ("published", "archived")
        and r["run_id"] not in assignments
        and r["run_id"] not in skipped
    ]
    pending.sort(key=lambda r: r.get("updated_at") or "")

    changed = False
    for run in pending:
        day = start
        for _ in range(60):
            iso = day.isoformat()
            js_day = (day.weekday() + 1) % 7  # Python T2=0..CN=6 → JS CN=0..T7=6
            if (js_day in cadence or day.weekday() == 6) and iso not in taken:
                assignments[run["run_id"]] = {"date": iso}
                taken.add(iso)
                changed = True
                break
            day += timedelta(days=1)
    if changed:
        _save_schedule(data)
    return data


@router.get("/publish/schedule")
def get_publish_schedule() -> dict:
    """Lịch đăng: cadence + assignments + các run hoàn tất (pool chờ lên lịch)."""
    data = _load_schedule()
    status_by_run = _topic_status_map()
    runs = []
    runs_dir = paths.runs_dir()
    if runs_dir.is_dir():
        for entry in sorted(runs_dir.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            state = _load_state(entry.name)
            if state is None or state.get("status") != "complete":
                continue
            has_video = (entry / "video-build" / "video-final.mp4").is_file()
            runs.append({
                "run_id": entry.name,
                "topic": str(state.get("topic") or ""),
                "status": state.get("status"),
                "topic_status": status_by_run.get(entry.name) or None,
                "updated_at": state.get("updated_at"),
                "has_video": has_video,
            })
    runs.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
    # Tự gán slot cho run hoàn tất chưa có ngày — "chạy xong là có ngày đề xuất"
    data = _auto_assign_slots(data, runs)
    # gắn topic_status vào assignment để UI không phải join
    assignments = {}
    for run_id, value in (data.get("assignments") or {}).items():
        assignments[run_id] = {
            "date": value.get("date") if isinstance(value, dict) else value,
            "topic_status": status_by_run.get(run_id) or None,
        }
    return {
        "cadence": data.get("cadence"),
        "assignments": assignments,
        "runs": runs,
        "skipped": sorted(data.get("skipped") or []),
    }


@router.post("/publish/schedule")
def set_publish_schedule(body: dict) -> dict:
    """Gán/bỏ ngày đăng cho run: {run_id, date: "YYYY-MM-DD"|null}."""
    _check_run_id(str(body.get("run_id") or ""))
    run_id = str(body["run_id"])
    _require_state(run_id)
    data = _load_schedule()
    assignments = data.setdefault("assignments", {})
    date = str(body.get("date") or "").strip()
    if not date:
        # Bỏ lịch → đánh dấu skipped để auto-assign không gán lại oan
        assignments.pop(run_id, None)
        data.setdefault("skipped", [])
        if run_id not in data["skipped"]:
            data["skipped"].append(run_id)
    else:
        try:
            parsed = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="date phải dạng YYYY-MM-DD.")
        # Chặn năm vô lý (gõ thiếu năm trên ô date picker...)
        if not 2024 <= parsed.year <= 2100:
            raise HTTPException(status_code=400, detail="date ngoài phạm vi hợp lệ (2024–2100).")
        assignments[run_id] = {"date": date}
        # Gán tay (cả qua nút Slot kế tiếp) → bỏ skip
        if "skipped" in data and run_id in data["skipped"]:
            data["skipped"].remove(run_id)
    _save_schedule(data)
    return {"saved": True, "run_id": run_id, "date": date or None}


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
    # topic_status (drafted/published/archived) từ topic-history — để UI gắn badge
    try:
        from youtube_pipeline.topic_history import load_history

        status_by_run = {
            str(row.get("run_id")): str(row.get("status") or "")
            for row in load_history(paths.backend_root())
            if row.get("run_id")
        }
        for run in runs:
            run["topic_status"] = status_by_run.get(run["run_id"]) or None
    except Exception:  # noqa: BLE001 — badge là tiện ích, không chặn danh sách
        pass
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


@router.get("/runs/{run_id}/diagnostics")
def run_diagnostics(run_id: str) -> dict:
    """Safe provenance and model telemetry, indexed by SQLite when available."""
    _check_run_id(run_id)
    state = _require_state(run_id)
    from youtube_pipeline.platform_db import PlatformDatabase

    database_path = PlatformDatabase.path_for_run_root(paths.run_dir(run_id))
    if database_path.exists():
        report = PlatformDatabase(database_path).run_diagnostics(run_id)
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
        "execution_started_at": state.get("execution_started_at"),
        "execution_finished_at": state.get("execution_finished_at"),
        "execution_elapsed_seconds": state.get("execution_elapsed_seconds"),
        "total_elapsed_seconds": state.get("total_elapsed_seconds", 0.0),
        "finished": state.get("status") in ("complete", "failed"),
        "executing": is_active,
        "orphaned": is_active and bool(active.get("orphaned")),
    }


@router.get("/runs/{run_id}/events")
def run_events(run_id: str) -> StreamingResponse:
    """Stream run status updates until the subprocess reaches a terminal state."""
    _check_run_id(run_id)
    _require_state(run_id)

    def stream():
        import time

        previous = ""
        while True:
            state = _load_state(run_id)
            if state is None:
                break
            records = state.get("stage_records") or {}
            active_stage = None
            names = list(records.keys())
            for name in names:
                if records[name].get("status") == "running":
                    active_stage = {"index": names.index(name), "name": name, "status": "running"}
                    break
            active = runner.active_run()
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
    output_dir = body.get("output_dir")
    if output_dir:
        out = Path(output_dir).resolve() if os.path.isabs(output_dir) else (paths.backend_root() / output_dir).resolve()
        canonical_out = paths.run_dir(run_id).resolve()
        if out != canonical_out:
            raise HTTPException(
                status_code=400,
                detail="output_dir phải trỏ đúng runs/<run_id>; run khác thư mục sẽ không được UI resume/status nhận diện.",
            )
    else:
        out = paths.run_dir(run_id)
    input_file = None
    manual_topic = None
    no_channel_data = False
    channel = str(body.get("channel") or "").strip() or None
    if channel and not re.match(r"^[A-Za-z0-9._-]{1,64}$", channel):
        raise HTTPException(status_code=400, detail="channel không hợp lệ (A-Z a-z 0-9 . _ -)")
    if mode == "production":
        channel_data_mode = str(body.get("channel_data_mode") or "snapshot")
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
                input_file = resolve_dataset_file(str(name))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        log_file = runner.start_new(run_id, out, mode, input_file, manual_topic, no_channel_data, channel=channel)
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
        "log_path": str(log_file),
    }


@router.post("/runs/{run_id}/topic-status")
def update_topic_status(run_id: str, body: dict) -> dict:
    """Mark a completed resource pack as published only after the user releases it."""
    _check_run_id(run_id)
    state = _require_state(run_id)
    if state.get("status") != "complete":
        raise HTTPException(status_code=400, detail="Chỉ cập nhật lifecycle cho run đã hoàn tất.")
    status = body.get("status") if isinstance(body, dict) else None
    try:
        from youtube_pipeline.topic_history import set_topic_status
        set_topic_status(paths.run_dir(run_id), run_id, str(status))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"run_id": run_id, "topic_status": status}


def _cancel_child_jobs(run_id: str) -> dict:
    """Hủy mọi worker nền thuộc run: TTS, Veo clip, image-gen, SRT.

    Cancel pipeline KHÔNG tự lan xuống các job này (mỗi runner độc lập),
    nên phải gọi tường minh — nếu không job con cứ chạy ngầm đến hết.
    """
    from .image_runner import image_runner
    from .srt_runner import srt_runner
    from .veo_runner import veo_runner

    return {
        "tts": _cancel_tts_job(run_id) or None,
        "veo_jobs": veo_runner.cancel_for_run(run_id),
        "image_jobs": image_runner.cancel_for_run(run_id),
        "srt_jobs": srt_runner.cancel_for_run(run_id),
    }


@router.post("/runs/{run_id}/cancel", status_code=202)
def cancel_run(run_id: str) -> dict:
    _check_run_id(run_id)
    stopped = runner.cancel(run_id)
    children = _cancel_child_jobs(run_id)
    children_active = any(children.values())
    if not stopped and not children_active:
        raise HTTPException(status_code=404, detail="Run không đang chạy — không thể hủy")
    return {"cancelled": bool(stopped), "run_id": run_id, "children": {
        "tts_cancelled": bool(children["tts"]),
        "veo_jobs": children["veo_jobs"],
        "image_jobs": children["image_jobs"],
        "srt_jobs": children["srt_jobs"],
    }}


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


@router.get("/runs/{run_id}/artifacts/{path:path}")
def run_artifact_path(run_id: str, path: str, download: int = 0) -> Response:
    """Path-style alias khớp với artifactUrl() phía UI (audio player, download)."""
    return run_artifact(run_id=run_id, path=path, download=download)


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
