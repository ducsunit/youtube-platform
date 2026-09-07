"""Resolve API paths, including channel-scoped paths introduced in Phase 1."""
from __future__ import annotations

import os
from pathlib import Path

from ..channel_context import validate_scope_id

_BACKEND_ROOT: Path | None = None
RUN_ID_PATTERN = r"^[A-Za-z0-9._-]{1,80}$"


def backend_root() -> Path:
    if _BACKEND_ROOT is not None:
        return _BACKEND_ROOT
    env = os.environ.get("YT_API_BACKEND_ROOT") or os.environ.get("YOUTUBE_BACKEND_ROOT")
    return Path(env).resolve() if env else Path(__file__).resolve().parents[2]


def users_dir() -> Path:
    return backend_root() / "users"


def channel_root(user_id: str, channel_id: str) -> Path:
    """Return a safe per-user/per-channel root; never accepts traversal."""
    return users_dir() / validate_scope_id(user_id, "user_id") / "channels" / validate_scope_id(channel_id, "channel_id")


def channel_data_dir(user_id: str, channel_id: str) -> Path:
    return channel_root(user_id, channel_id) / "data"


def channel_content_dir(user_id: str, channel_id: str) -> Path:
    return channel_root(user_id, channel_id) / "content"


def channel_config_dir(user_id: str, channel_id: str) -> Path:
    return channel_root(user_id, channel_id) / "config"


def channel_assets_dir(user_id: str, channel_id: str) -> Path:
    return channel_root(user_id, channel_id) / "assets"


def channel_runs_dir(user_id: str, channel_id: str) -> Path:
    return channel_root(user_id, channel_id) / "runs"


def channel_run_dir(user_id: str, channel_id: str, run_id: str) -> Path:
    return channel_runs_dir(user_id, channel_id) / validate_scope_id(run_id, "run_id")


def channel_snapshot_dir(user_id: str, channel_id: str) -> Path:
    return channel_data_dir(user_id, channel_id) / "snapshots"


def channel_log_dir(user_id: str, channel_id: str) -> Path:
    return channel_root(user_id, channel_id) / "runtime" / "logs"


def channel_log_path(user_id: str, channel_id: str, run_id: str) -> Path:
    return channel_log_dir(user_id, channel_id) / f"{validate_scope_id(run_id, 'run_id')}.log"


def channel_pid_path(user_id: str, channel_id: str, run_id: str) -> Path:
    return channel_log_dir(user_id, channel_id) / f"{validate_scope_id(run_id, 'run_id')}.pid"


# Legacy global paths. Keep these until the API routes are migrated in Phase 1C.
def runs_dir() -> Path:
    return backend_root() / "runs"


def _job_logs_dir(kind: str) -> Path:
    runtime = backend_root() / "runtime" / "logs" / kind
    legacy = backend_root() / "logs" / kind
    return legacy if not runtime.exists() and legacy.exists() else runtime


def logs_dir() -> Path:
    return _job_logs_dir("api-runs")


def data_jobs_dir() -> Path:
    return _job_logs_dir("api-data")


def build_jobs_dir() -> Path:
    return _job_logs_dir("api-build")


def image_jobs_dir() -> Path:
    return _job_logs_dir("api-image-gen")


def srt_jobs_dir() -> Path:
    return _job_logs_dir("api-srt")


def veo_jobs_dir() -> Path:
    return _job_logs_dir("api-veo")


def run_dir(run_id: str) -> Path:
    return runs_dir() / run_id


def run_state_path(run_id: str) -> Path:
    return run_dir(run_id) / "run_state.json"


def manifest_path(run_id: str) -> Path:
    return run_dir(run_id) / "resource_manifest.json"


def log_path(run_id: str) -> Path:
    return logs_dir() / (f"{run_id}.log")


def pid_path(run_id: str) -> Path:
    return logs_dir() / (f"{run_id}.pid")
