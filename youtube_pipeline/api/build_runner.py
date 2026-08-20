"""Runner cho job Dựng video (Flow 3) — spawn build_service làm subprocess.

Giống hệt DataPullRunner: singleton + lock, tối đa MỘT build job đang chạy,
độc lập với PipelineRunner và DataPullRunner (build không chặn pipeline/data
và ngược lại). Log + pid ở `runtime/logs/api-build/`; fd kế thừa KHÔNG PIPE — server
chết giữa chừng thì job (gồm cả ffmpeg con của build-video.py, cùng process
group) vẫn chạy và ghi log; server mới đọc lại pid file -> báo `orphaned`.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import paths
from .datapull import _pid_alive, _read_pid_info, read_log_page


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_job_command(run_dir: Path, options: dict) -> list[str]:
    """Command chạy service Dựng video: `python -m youtube_pipeline.build_service`."""
    argv = [sys.executable, "-u", "-m", "youtube_pipeline.build_service", str(run_dir)]
    if options.get("render") is False:
        argv.append("--prepare-only")
    if not options.get("motion", True):
        argv.append("--no-motion")
    animation = options.get("animation")
    if animation:
        argv += ["--animation", animation]
    if options.get("transition") is not None:
        argv += ["--transition", str(options["transition"])]
    resolution = options.get("resolution")
    if resolution:
        argv += ["--resolution", "%dx%d" % tuple(resolution)]
    if options.get("dry_run"):
        argv.append("--dry-run")
    if options.get("subtitles"):
        argv.append("--subtitles")
    if options.get("logo_cleanup"):
        argv.append("--logo-cleanup")
        argv += ["--logo-mode", str(options.get("logo_mode", "delogo"))]
    return argv


class BuildBusyError(Exception):
    """Đã có một build job đang chạy — chuyển thành HTTP 409."""

    def __init__(self, job_id: str) -> None:
        super().__init__("Một job Dựng video đang chạy: %s" % job_id)
        self.job_id = job_id


class BuildRunner:
    """Singleton — tối đa một build job. Trạng thái trong bộ nhớ hoặc trên đĩa."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._job: Optional[dict] = None
        self._finished: dict[str, dict] = {}

    # --------------------------------------------------------------- query

    def active_job(self) -> Optional[dict]:
        """{id, run_id, started_at, log_path, orphaned} | None."""
        with self._lock:
            return self._active_unlocked()

    def busy(self) -> bool:
        return self.active_job() is not None

    def _active_unlocked(self) -> Optional[dict]:
        if self._proc is not None and self._proc.poll() is None and self._job:
            return {
                "id": self._job["id"],
                "run_id": self._job.get("run_id"),
                "started_at": self._job["started_at"],
                "log_path": self._job["log_path"],
                "orphaned": False,
            }
        jobs_dir = paths.build_jobs_dir()
        if jobs_dir.is_dir():
            for pid_file in sorted(jobs_dir.glob("*.pid")):
                info = _read_pid_info(pid_file)
                if info is None or not _pid_alive(info["pid"]):
                    try:
                        pid_file.unlink()
                    except OSError:
                        pass
                    continue
                return {
                    "id": pid_file.stem,
                    "run_id": info.get("run_id"),
                    "started_at": None,
                    "log_path": str(jobs_dir / ("%s.log" % pid_file.stem)),
                    "orphaned": True,
                }
        return None

    # --------------------------------------------------------------- start

    def start(self, run_id: str, argv: list[str], cwd: Path) -> dict:
        """Spawn build job; trả {id, run_id, started_at, log_path}."""
        with self._lock:
            active = self._active_unlocked()
            if active is not None:
                raise BuildBusyError(str(active["id"]))
            job_id = uuid.uuid4().hex
            log_file = paths.build_jobs_dir() / ("%s.log" % job_id)
            log_file.parent.mkdir(parents=True, exist_ok=True)
            # fd kế thừa — KHÔNG PIPE: server chết -> child không bị SIGPIPE,
            # log tiếp tục ghi, server mới đọc lại được.
            handle = open(log_file, "ab")
            try:
                handle.write(
                    ("=== start %s kind=build job=%s run=%s ===\n" % (_now_iso(), job_id, run_id)).encode(
                        "utf-8"
                    )
                )
                handle.flush()
                proc = subprocess.Popen(
                    argv,
                    cwd=str(cwd),  # backend root — `-m youtube_pipeline.*` import được
                    env=os.environ.copy(),
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            except Exception:
                handle.close()
                raise
            # Child đã có fd riêng (kế thừa) — bản của parent đóng lại được ngay,
            # không giữ thì mỗi job start là một fd rò rỉ.
            handle.close()
            try:
                # pid info dạng json {pid, kind} (đọc linh hoạt) + run_id cho orphan.
                (paths.build_jobs_dir() / ("%s.pid" % job_id)).write_text(
                    json.dumps({"pid": proc.pid, "kind": "build", "run_id": run_id}),
                    encoding="utf-8",
                )
            except OSError:
                pass
            self._proc = proc
            started_at = _now_iso()
            self._job = {
                "id": job_id,
                "run_id": run_id,
                "started_at": started_at,
                "log_path": str(log_file),
            }
            threading.Thread(
                target=self._waiter, args=(proc, job_id, run_id, started_at), daemon=True
            ).start()
            return {"id": job_id, "run_id": run_id, "started_at": started_at, "log_path": str(log_file)}

    def _waiter(self, proc: subprocess.Popen, job_id: str, run_id: str, started_at: str) -> None:
        code = proc.wait()
        with self._lock:
            if self._proc is proc:
                self._proc = None
                self._job = None
            self._finished[job_id] = {
                "id": job_id,
                "run_id": run_id,
                "status": "complete" if code == 0 else "failed",
                "exit_code": code,
                "started_at": started_at,
                "finished_at": _now_iso(),
                "log_path": str(paths.build_jobs_dir() / ("%s.log" % job_id)),
            }
            while len(self._finished) > 20:  # ring nhỏ, không lớn mãi
                self._finished.pop(next(iter(self._finished)))
        try:
            with open(paths.build_jobs_dir() / ("%s.log" % job_id), "ab") as fh:
                fh.write(("=== exit code %d ===\n" % code).encode("utf-8"))
        except OSError:
            pass
        try:
            (paths.build_jobs_dir() / ("%s.pid" % job_id)).unlink()
        except OSError:
            pass

    # --------------------------------------------------------------- status

    def job_status(self, job_id: str) -> Optional[dict]:
        """{id, run_id, status, exit_code, started_at, finished_at} | None."""
        with self._lock:
            if (
                self._job is not None
                and self._job["id"] == job_id
                and self._proc is not None
                and self._proc.poll() is None
            ):
                return {
                    "id": job_id,
                    "run_id": self._job.get("run_id"),
                    "status": "running",
                    "exit_code": None,
                    "started_at": self._job["started_at"],
                    "finished_at": None,
                }
            if job_id in self._finished:
                return dict(self._finished[job_id])
        # Đường đĩa — phục vụ job mồ côi / sau khi server restart.
        jobs_dir = paths.build_jobs_dir()
        log_file = jobs_dir / ("%s.log" % job_id)
        pid_file = jobs_dir / ("%s.pid" % job_id)
        info = _read_pid_info(pid_file)
        if info is not None and _pid_alive(info["pid"]):
            return {
                "id": job_id,
                "run_id": info.get("run_id"),
                "status": "running",
                "exit_code": None,
                "started_at": None,
                "finished_at": None,
            }
        if log_file.is_file():
            text = log_file.read_text(encoding="utf-8", errors="replace")
            markers = text.split("=== exit code ")[1:]
            if markers:
                code = int(markers[-1].split(" ===", 1)[0])
                return {
                    "id": job_id,
                    "run_id": None,
                    "status": "complete" if code == 0 else "failed",
                    "exit_code": code,
                    "started_at": None,
                    "finished_at": None,
                }
            return {
                "id": job_id,
                "run_id": None,
                "status": "failed",
                "exit_code": None,
                "started_at": None,
                "finished_at": None,
            }
        return None

    # --------------------------------------------------------------- cancel

    def cancel(self, job_id: str) -> bool:
        """SIGTERM cả process group; đúng cho proc trong bộ nhớ lẫn orphan."""
        with self._lock:
            if (
                self._proc is not None
                and self._job is not None
                and self._job["id"] == job_id
                and self._proc.poll() is None
            ):
                self._terminate(self._proc)
                return True
        info = _read_pid_info(paths.build_jobs_dir() / ("%s.pid" % job_id))
        if info is not None and _pid_alive(info["pid"]):
            try:
                os.killpg(os.getpgid(info["pid"]), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                return False
            return True
        return False

    @staticmethod
    def _terminate(proc: subprocess.Popen) -> None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass


build_runner = BuildRunner()
