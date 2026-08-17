"""Độ phân giải mọi đường dẫn của API server — điểm duy nhất test có thể patch.

Module attr `_BACKEND_ROOT` (hoặc env `YT_API_BACKEND_ROOT`) ghi đè root của
project backend. Mọi hàm đọc override tại thời điểm gọi.
"""
from __future__ import annotations

import os
from pathlib import Path

_BACKEND_ROOT: Path | None = None

# run_id hợp lệ cho mọi endpoint dùng nó làm path segment (chống path injection).
RUN_ID_PATTERN = r"^[A-Za-z0-9._-]{1,80}$"


def backend_root() -> Path:
    if _BACKEND_ROOT is not None:
        return _BACKEND_ROOT
    env = os.environ.get("YT_API_BACKEND_ROOT")
    if env:
        return Path(env).resolve()
    # youtube_pipeline/api/paths.py -> parents[2] = project root
    return Path(__file__).resolve().parents[2]


def runs_dir() -> Path:
    return backend_root() / "runs"


def logs_dir() -> Path:
    return backend_root() / "runtime" / "logs" / "api-runs"


def data_jobs_dir() -> Path:
    """Log + pid của các data job (kéo data YouTube) — tách khỏi pipeline runs."""
    return backend_root() / "runtime" / "logs" / "api-data"


def build_jobs_dir() -> Path:
    """Log + pid của các job Dựng video (build service) — tách riêng 3 runner."""
    return backend_root() / "runtime" / "logs" / "api-build"



def veo_jobs_dir() -> Path:
    """Log + pid của các job Veo — tách riêng khỏi build/data jobs."""
    return backend_root() / "runtime" / "logs" / "api-veo"

def run_dir(run_id: str) -> Path:
    return runs_dir() / run_id


def run_state_path(run_id: str) -> Path:
    return run_dir(run_id) / "run_state.json"


def manifest_path(run_id: str) -> Path:
    return run_dir(run_id) / "resource_manifest.json"


def log_path(run_id: str) -> Path:
    return logs_dir() / ("%s.log" % run_id)


def pid_path(run_id: str) -> Path:
    return logs_dir() / ("%s.pid" % run_id)
