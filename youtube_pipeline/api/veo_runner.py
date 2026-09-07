"""Runner cho Veo image-to-video jobs, isolated per optional channel namespace."""
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


def veo_gen_command(run_dir: Path, indices: list[str], model: str) -> list[str]:
    """Command chạy veo_gen: `python -m youtube_pipeline.veo_gen`."""
    return [
        sys.executable,
        "-u",
        "-m",
        "youtube_pipeline.veo_gen",
        "--run-dir",
        str(run_dir),
        "--images",
        ",".join(indices),
        "--model",
        model,
    ]


class VeoBusyError(Exception):
    """Đã có một Veo job đang chạy trong namespace này."""

    def __init__(self, job_id: str) -> None:
        super().__init__("Một Veo job đang chạy: %s" % job_id)
        self.job_id = job_id


class VeoRunner:
    """At most one Veo job per user/channel namespace; legacy scope remains supported."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[tuple[str | None, str | None], tuple[subprocess.Popen, dict]] = {}
        self._finished: dict[tuple[tuple[str | None, str | None], str], dict] = {}
        self._finished_order: list[tuple[tuple[str | None, str | None], str]] = []

    @staticmethod
    def _scope(user_id: str | None, channel_id: str | None) -> tuple[str | None, str | None]:
        if bool(user_id) != bool(channel_id):
            raise ValueError("user_id và channel_id phải được truyền cùng nhau")
        return user_id, channel_id

    @staticmethod
    def jobs_dir(user_id: str | None = None, channel_id: str | None = None) -> Path:
        if bool(user_id) != bool(channel_id):
            raise ValueError("user_id và channel_id phải được truyền cùng nhau")
        return (
            paths.channel_root(user_id, channel_id) / "runtime" / "veo-jobs"
            if user_id and channel_id
            else paths.veo_jobs_dir()
        )

    # --------------------------------------------------------------- query

    def _active_unlocked(
        self,
        jobs_dir: Path | None = None,
        scope: tuple[str | None, str | None] | None = None,
    ) -> Optional[dict]:
        jobs_dir = jobs_dir or paths.veo_jobs_dir()
        for job_scope, (proc, job) in self._jobs.items():
            if proc.poll() is None and (scope is None or job_scope == scope):
                return {**job, "status": "running", "orphaned": False}
        if not jobs_dir.is_dir():
            return None
        for pid_file in sorted(jobs_dir.glob("*.pid")):
            info = _read_pid_info(pid_file)
            if info is None or not _pid_alive(info["pid"]):
                pid_file.unlink(missing_ok=True)
                continue
            if scope is not None and (info.get("user_id"), info.get("channel_id")) != scope:
                continue
            return {
                "id": pid_file.stem,
                "run_id": info.get("run_id"),
                "user_id": info.get("user_id"),
                "channel_id": info.get("channel_id"),
                "started_at": None,
                "log_path": str(jobs_dir / ("%s.log" % pid_file.stem)),
                "status": "running",
                "orphaned": True,
            }
        return None

    def active_job(self, *, user_id: str | None = None, channel_id: str | None = None) -> Optional[dict]:
        scope = self._scope(user_id, channel_id)
        with self._lock:
            return self._active_unlocked(self.jobs_dir(user_id, channel_id), scope)

    def busy(self, *, user_id: str | None = None, channel_id: str | None = None) -> bool:
        return self.active_job(user_id=user_id, channel_id=channel_id) is not None

    def job_status(self, job_id: str, *, user_id: str | None = None, channel_id: str | None = None) -> Optional[dict]:
        scope = self._scope(user_id, channel_id)
        with self._lock:
            current = self._jobs.get(scope)
            if current is not None and current[1]["id"] == job_id and current[0].poll() is None:
                return {
                    **current[1],
                    "status": "running",
                    "exit_code": None,
                    "finished_at": None,
                }
            finished = self._finished.get((scope, job_id))
            if finished is not None:
                return dict(finished)
        # Orphan / sau server restart — only inspect this namespace's disk state.
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
                try:
                    code = int(markers[-1].split(" ===", 1)[0])
                except ValueError:
                    code = 1
                return {
                    "id": job_id,
                    "run_id": None,
                    "user_id": user_id,
                    "channel_id": channel_id,
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
        """Spawn Veo job; returns its scoped job metadata."""
        scope = self._scope(user_id, channel_id)
        jobs_dir = self.jobs_dir(user_id, channel_id)
        with self._lock:
            active = self._active_unlocked(jobs_dir, scope)
            if active is not None:
                raise VeoBusyError(str(active["id"]))
            job_id = uuid.uuid4().hex
            log_file = jobs_dir / ("%s.log" % job_id)
            log_file.parent.mkdir(parents=True, exist_ok=True)
            handle = open(log_file, "ab")
            try:
                handle.write(
                    ("=== start %s kind=veo job=%s run=%s ===\n" % (_now_iso(), job_id, run_id)).encode("utf-8")
                )
                handle.flush()
                proc = subprocess.Popen(
                    argv,
                    cwd=str(cwd),
                    env=os.environ.copy(),
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            except Exception:
                handle.close()
                raise
            handle.close()
            try:
                (jobs_dir / ("%s.pid" % job_id)).write_text(
                    json.dumps({
                        "pid": proc.pid,
                        "kind": "veo",
                        "run_id": run_id,
                        "user_id": user_id,
                        "channel_id": channel_id,
                    }),
                    encoding="utf-8",
                )
            except OSError:
                pass
            job = {
                "id": job_id,
                "run_id": run_id,
                "user_id": user_id,
                "channel_id": channel_id,
                "started_at": _now_iso(),
                "log_path": str(log_file),
            }
            self._jobs[scope] = (proc, job)
            threading.Thread(target=self._waiter, args=(proc, job, jobs_dir, scope), daemon=True).start()
            return dict(job)

    def _waiter(
        self,
        proc: subprocess.Popen,
        job: dict,
        jobs_dir: Path,
        scope: tuple[str | None, str | None],
    ) -> None:
        code = proc.wait()
        job_id = job["id"]
        with self._lock:
            current = self._jobs.get(scope)
            if current is not None and current[0] is proc:
                self._jobs.pop(scope, None)
            self._finished[(scope, job_id)] = {
                **job,
                "status": "complete" if code == 0 else "failed",
                "exit_code": code,
                "finished_at": _now_iso(),
            }
            self._finished_order.append((scope, job_id))
            while len(self._finished_order) > 50:
                self._finished.pop(self._finished_order.pop(0), None)
        try:
            with open(jobs_dir / ("%s.log" % job_id), "ab") as fh:
                fh.write(("=== exit code %d ===\n" % code).encode("utf-8"))
            (jobs_dir / ("%s.pid" % job_id)).unlink(missing_ok=True)
        except OSError:
            pass

    # --------------------------------------------------------------- cancel

    def cancel(self, job_id: str, *, user_id: str | None = None, channel_id: str | None = None) -> bool:
        scope = self._scope(user_id, channel_id)
        with self._lock:
            current = self._jobs.get(scope)
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

    def get_log(
        self,
        job_id: str,
        offset: int = 0,
        limit: int = 200,
        *,
        user_id: str | None = None,
        channel_id: str | None = None,
    ) -> dict:
        self._scope(user_id, channel_id)
        return read_log_page(self.jobs_dir(user_id, channel_id) / ("%s.log" % job_id), offset, limit)


veo_runner = VeoRunner()
