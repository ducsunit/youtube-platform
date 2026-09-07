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
    """Runner có tối đa một build job cho mỗi namespace user/channel."""

    @staticmethod
    def jobs_dir(user_id: str | None = None, channel_id: str | None = None) -> Path:
        if bool(user_id) != bool(channel_id):
            raise ValueError("user_id và channel_id phải được truyền cùng nhau")
        return (
            paths.channel_root(user_id, channel_id) / "runtime" / "build-jobs"
            if user_id and channel_id
            else paths.build_jobs_dir()
        )

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[tuple[str | None, str | None], tuple[subprocess.Popen, dict]] = {}
        self._finished: dict[tuple[tuple[str | None, str | None], str], dict] = {}
        self._finished_order: list[tuple[tuple[str | None, str | None], str]] = []

    # --------------------------------------------------------------- query

    def active_job(self, *, user_id: str | None = None, channel_id: str | None = None) -> Optional[dict]:
        """{id, run_id, started_at, log_path, orphaned} | None in this namespace."""
        jobs_dir = self.jobs_dir(user_id, channel_id)
        with self._lock:
            return self._active_unlocked(jobs_dir, (user_id, channel_id))

    @staticmethod
    def _scope(user_id: str | None, channel_id: str | None) -> tuple[str | None, str | None]:
        if bool(user_id) != bool(channel_id):
            raise ValueError("user_id và channel_id phải được truyền cùng nhau")
        return user_id, channel_id

    def busy(self, *, user_id: str | None = None, channel_id: str | None = None) -> bool:
        return self.active_job(user_id=user_id, channel_id=channel_id) is not None

    def _active_unlocked(
        self,
        jobs_dir: Path | None = None,
        scope: tuple[str | None, str | None] | None = None,
    ) -> Optional[dict]:
        if jobs_dir is None:
            jobs_dir = paths.build_jobs_dir()
        for job_scope, (proc, job) in self._jobs.items():
            if proc.poll() is None and (scope is None or job_scope == scope):
                return {**job, "orphaned": False}

        if jobs_dir.is_dir():
            for pid_file in sorted(jobs_dir.glob("*.pid")):
                info = _read_pid_info(pid_file)
                if info is None or not _pid_alive(info["pid"]):
                    try:
                        pid_file.unlink()
                    except OSError:
                        pass
                    continue
                info_scope = (info.get("user_id"), info.get("channel_id"))
                if scope is not None and info_scope != scope:
                    continue
                return {
                    "id": pid_file.stem,
                    "run_id": info.get("run_id"),
                    "started_at": None,
                    "log_path": str(jobs_dir / ("%s.log" % pid_file.stem)),
                    "user_id": info.get("user_id"),
                    "channel_id": info.get("channel_id"),
                    "orphaned": True,
                }
        return None

    # --------------------------------------------------------------- start

    def start(
        self,
        run_id: str,
        argv: list[str],
        cwd: Path,
        *,
        user_id: str | None = None,
        channel_id: str | None = None,
    ) -> dict:
        """Spawn build job; trả {id, run_id, started_at, log_path}."""
        jobs_dir = self.jobs_dir(user_id, channel_id)
        scope = self._scope(user_id, channel_id)
        with self._lock:
            active = self._active_unlocked(jobs_dir, scope)
            if active is not None:
                raise BuildBusyError(str(active["id"]))
            job_id = uuid.uuid4().hex
            log_file = jobs_dir / ("%s.log" % job_id)
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
                (jobs_dir / ("%s.pid" % job_id)).write_text(
                    json.dumps(
                        {
                            "pid": proc.pid,
                            "kind": "build",
                            "run_id": run_id,
                            "user_id": user_id,
                            "channel_id": channel_id,
                        }
                    ),
                    encoding="utf-8",
                )
            except OSError:
                pass
            started_at = _now_iso()
            job = {
                "id": job_id,
                "run_id": run_id,
                "user_id": user_id,
                "channel_id": channel_id,
                "started_at": started_at,
                "log_path": str(log_file),
                "jobs_dir": str(jobs_dir),
            }
            self._jobs[scope] = (proc, job)
            threading.Thread(
                target=self._waiter, args=(proc, job_id, run_id, started_at, jobs_dir, scope), daemon=True
            ).start()
            return {"id": job_id, "run_id": run_id, "started_at": started_at, "log_path": str(log_file)}

    def _waiter(
        self,
        proc: subprocess.Popen,
        job_id: str,
        run_id: str,
        started_at: str,
        jobs_dir: Path,
        scope: tuple[str | None, str | None],
    ) -> None:
        code = proc.wait()
        log_path = jobs_dir / ("%s.log" % job_id)
        with self._lock:
            current = self._jobs.get(scope)
            if current is not None and current[0] is proc:
                self._jobs.pop(scope, None)
            self._finished[(scope, job_id)] = {
                "id": job_id,
                "run_id": run_id,
                "user_id": scope[0],
                "channel_id": scope[1],
                "status": "complete" if code == 0 else "failed",
                "exit_code": code,
                "started_at": started_at,
                "finished_at": _now_iso(),
                "log_path": str(log_path),
            }
            self._finished_order.append((scope, job_id))
            while len(self._finished_order) > 20:
                self._finished.pop(self._finished_order.pop(0), None)
        try:
            with open(log_path, "ab") as fh:
                fh.write(("=== exit code %d ===\n" % code).encode("utf-8"))
        except OSError:
            pass
        try:
            (jobs_dir / ("%s.pid" % job_id)).unlink()
        except OSError:
            pass

    def _in_memory_job(
        self, job_id: str, scope: tuple[str | None, str | None]
    ) -> Optional[dict]:
        current = self._jobs.get(scope)
        if current is not None:
            proc, job = current
            if job["id"] == job_id and proc.poll() is None:
                return {
                    **job,
                    "status": "running",
                    "exit_code": None,
                    "finished_at": None,
                }
        finished = self._finished.get((scope, job_id))
        return dict(finished) if finished is not None else None

    def log_path(self, job_id: str, *, user_id: str | None = None, channel_id: str | None = None) -> Path:
        self._scope(user_id, channel_id)
        return self.jobs_dir(user_id, channel_id) / ("%s.log" % job_id)

    # --------------------------------------------------------------- status

    def job_status(self, job_id: str, *, user_id: str | None = None, channel_id: str | None = None) -> Optional[dict]:
        """{id, run_id, status, exit_code, started_at, finished_at} | None."""
        scope = self._scope(user_id, channel_id)
        with self._lock:
            in_memory = self._in_memory_job(job_id, scope)
            if in_memory is not None:
                return in_memory
        # Đường đĩa — phục vụ job mồ côi / sau khi server restart.
        jobs_dir = self.jobs_dir(user_id, channel_id)
        log_file = jobs_dir / ("%s.log" % job_id)
        pid_file = jobs_dir / ("%s.pid" % job_id)
        info = _read_pid_info(pid_file)
        if info is not None and _pid_alive(info["pid"]):
            return {
                "id": job_id,
                "run_id": info.get("run_id"),
                "user_id": info.get("user_id"),
                "channel_id": info.get("channel_id"),
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
                    "user_id": info.get("user_id") if info else user_id,
                    "channel_id": info.get("channel_id") if info else channel_id,
                    "status": "complete" if code == 0 else "failed",
                    "exit_code": code,
                    "started_at": None,
                    "finished_at": None,
                }
            return {
                "id": job_id,
                "run_id": None,
                "user_id": user_id,
                "channel_id": channel_id,
                "status": "failed",
                "exit_code": None,
                "started_at": None,
                "finished_at": None,
            }
        return None

    # --------------------------------------------------------------- cancel

    def cancel(self, job_id: str, *, user_id: str | None = None, channel_id: str | None = None) -> bool:
        """SIGTERM cả process group; đúng cho proc trong bộ nhớ lẫn orphan."""
        with self._lock:
            current = self._jobs.get(self._scope(user_id, channel_id))
            if current is not None and current[1]["id"] == job_id and current[0].poll() is None:
                self._terminate(current[0])
                return True
        info = _read_pid_info(self.jobs_dir(user_id, channel_id) / ("%s.pid" % job_id))
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
