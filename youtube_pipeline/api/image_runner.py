"""Detached runner for OpenAI image-generation batches, isolated per channel namespace."""
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
from .build_runner import _pid_alive
from .datapull import _read_pid_info, read_log_page


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ImageBusyError(Exception):
    def __init__(self, job_id: str) -> None:
        super().__init__("Một job gen ảnh đang chạy: %s" % job_id)
        self.job_id = job_id


class ImageRunner:
    """At most one image job per user/channel namespace; legacy scope remains supported."""

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
            paths.channel_root(user_id, channel_id) / "runtime" / "image-jobs"
            if user_id and channel_id
            else paths.image_jobs_dir()
        )

    def _active_unlocked(
        self,
        jobs_dir: Path | None = None,
        scope: tuple[str | None, str | None] | None = None,
    ) -> Optional[dict]:
        jobs_dir = jobs_dir or paths.image_jobs_dir()
        for job_scope, (proc, job) in self._jobs.items():
            if proc.poll() is None and (scope is None or job_scope == scope):
                return {**job, "status": "running", "orphaned": False}
        if jobs_dir.is_dir():
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

    def start(
        self,
        run_id: str,
        run_dir: Path,
        indices: list[str],
        model: str,
        size: str,
        quality: str,
        *,
        user_id: str | None = None,
        channel_id: str | None = None,
    ) -> dict:
        scope = self._scope(user_id, channel_id)
        jobs_dir = self.jobs_dir(user_id, channel_id)
        with self._lock:
            active = self._active_unlocked(jobs_dir, scope)
            if active:
                raise ImageBusyError(str(active["id"]))
            job_id = uuid.uuid4().hex
            log_path = jobs_dir / (job_id + ".log")
            log_path.parent.mkdir(parents=True, exist_ok=True)
            argv = [sys.executable, "-u", "-m", "youtube_pipeline.image_gen"]
            if user_id and channel_id:
                argv.extend(["--user-id", user_id, "--channel-id", channel_id])
            argv.extend([str(run_dir), model, size, quality, *indices])
            handle = open(log_path, "ab")
            try:
                handle.write(("=== start %s kind=image-gen job=%s run=%s ===\n" % (_now_iso(), job_id, run_id)).encode())
                handle.write(("REQUEST model=%s size=%s quality=%s images=%d ids=%s python=%s cwd=%s\n" % (model, size, quality, len(indices), ",".join(indices), sys.executable, paths.backend_root())).encode())
                handle.flush()
                proc = subprocess.Popen(argv, cwd=str(paths.backend_root()), env=os.environ.copy(), stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
            finally:
                handle.close()
            (jobs_dir / (job_id + ".pid")).write_text(
                json.dumps({"pid": proc.pid, "kind": "image-gen", "run_id": run_id, "user_id": user_id, "channel_id": channel_id}),
                encoding="utf-8",
            )
            job = {
                "id": job_id,
                "run_id": run_id,
                "user_id": user_id,
                "channel_id": channel_id,
                "started_at": _now_iso(),
                "log_path": str(log_path),
            }
            self._jobs[scope] = (proc, job)
            threading.Thread(target=self._waiter, args=(proc, job, jobs_dir, scope), daemon=True).start()
            return job.copy()

    def _waiter(self, proc: subprocess.Popen, job: dict, jobs_dir: Path, scope: tuple[str | None, str | None]) -> None:
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
            while len(self._finished_order) > 20:
                self._finished.pop(self._finished_order.pop(0), None)
        try:
            with open(jobs_dir / (job_id + ".log"), "ab") as handle:
                handle.write(("=== exit %s code=%d ===\n" % (_now_iso(), code)).encode())
            (jobs_dir / (job_id + ".pid")).unlink(missing_ok=True)
        except OSError:
            pass

    def job_status(self, job_id: str, *, user_id: str | None = None, channel_id: str | None = None) -> Optional[dict]:
        scope = self._scope(user_id, channel_id)
        with self._lock:
            current = self._jobs.get(scope)
            if current is not None and current[1]["id"] == job_id and current[0].poll() is None:
                return {**current[1], "status": "running", "exit_code": None}
            finished = self._finished.get((scope, job_id))
            if finished is not None:
                return finished.copy()
        jobs_dir = self.jobs_dir(user_id, channel_id)
        log_path = jobs_dir / (job_id + ".log")
        pid_path = jobs_dir / (job_id + ".pid")
        info = _read_pid_info(pid_path)
        if info and _pid_alive(info["pid"]):
            return {"id": job_id, "run_id": info.get("run_id"), "user_id": info.get("user_id"), "channel_id": info.get("channel_id"), "status": "running", "exit_code": None}
        if log_path.is_file():
            text = log_path.read_text(encoding="utf-8", errors="replace")
            # Image jobs include a timestamp in the exit marker. Accept the
            # same durable marker shape after an API-server restart.
            markers = text.split("=== exit ")[1:]
            if markers:
                try:
                    code = int(markers[-1].split(" code=", 1)[1].split(" ===", 1)[0])
                except (IndexError, ValueError):
                    code = 1
                return {"id": job_id, "user_id": user_id, "channel_id": channel_id, "status": "complete" if code == 0 else "failed", "exit_code": code}
            if "=== exit code 0 ===" in text:  # legacy logs
                return {"id": job_id, "user_id": user_id, "channel_id": channel_id, "status": "complete", "exit_code": 0}
            return {"id": job_id, "user_id": user_id, "channel_id": channel_id, "status": "failed", "exit_code": 1}
        return None

    def cancel(self, job_id: str, *, user_id: str | None = None, channel_id: str | None = None) -> bool:
        scope = self._scope(user_id, channel_id)
        with self._lock:
            current = self._jobs.get(scope)
            if current is not None and current[1]["id"] == job_id and current[0].poll() is None:
                try:
                    os.killpg(os.getpgid(current[0].pid), signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    return False
                return True
        info = _read_pid_info(self.jobs_dir(user_id, channel_id) / (job_id + ".pid"))
        if info and _pid_alive(info["pid"]):
            try:
                os.killpg(os.getpgid(info["pid"]), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                return False
            return True
        return False

    def get_log(self, job_id: str, offset: int, limit: int, *, user_id: str | None = None, channel_id: str | None = None) -> dict:
        self._scope(user_id, channel_id)
        return {"job_id": job_id, **read_log_page(self.jobs_dir(user_id, channel_id) / (job_id + ".log"), offset, limit)}


image_runner = ImageRunner()
