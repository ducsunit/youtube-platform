"""Detached runner for OpenAI image-generation batches."""
from __future__ import annotations

import json
import os
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
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._job: Optional[dict] = None
        self._finished: dict[str, dict] = {}

    def _active_unlocked(self) -> Optional[dict]:
        if self._proc is not None and self._proc.poll() is None and self._job:
            return {**self._job, "status": "running", "orphaned": False}
        directory = paths.image_jobs_dir()
        if directory.is_dir():
            for pid_file in sorted(directory.glob("*.pid")):
                info = _read_pid_info(pid_file)
                if info and _pid_alive(info["pid"]):
                    return {"id": pid_file.stem, "run_id": info.get("run_id"), "status": "running", "orphaned": True}
                pid_file.unlink(missing_ok=True)
        return None

    def active_job(self) -> Optional[dict]:
        with self._lock:
            return self._active_unlocked()

    def busy(self) -> bool:
        return self.active_job() is not None

    def start(self, run_id: str, run_dir: Path, indices: list[str], model: str, size: str, quality: str) -> dict:
        with self._lock:
            active = self._active_unlocked()
            if active:
                raise ImageBusyError(str(active["id"]))
            job_id = uuid.uuid4().hex
            log_path = paths.image_jobs_dir() / (job_id + ".log")
            log_path.parent.mkdir(parents=True, exist_ok=True)
            argv = [sys.executable, "-u", "-m", "youtube_pipeline.image_gen", str(run_dir), model, size, quality, *indices]
            handle = open(log_path, "ab")
            handle.write(("=== start %s kind=image-gen job=%s run=%s ===\n" % (_now_iso(), job_id, run_id)).encode())
            handle.write(("REQUEST model=%s size=%s quality=%s images=%d ids=%s python=%s cwd=%s\n" % (model, size, quality, len(indices), ",".join(indices), sys.executable, paths.backend_root())).encode())
            handle.flush()
            try:
                proc = subprocess.Popen(argv, cwd=str(paths.backend_root()), env=os.environ.copy(), stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
            finally:
                handle.close()
            (paths.image_jobs_dir() / (job_id + ".pid")).write_text(json.dumps({"pid": proc.pid, "kind": "image-gen", "run_id": run_id}), encoding="utf-8")
            self._proc = proc
            self._job = {"id": job_id, "run_id": run_id, "started_at": _now_iso(), "log_path": str(log_path)}
            threading.Thread(target=self._waiter, args=(proc, job_id, run_id), daemon=True).start()
            return self._job.copy()

    def _waiter(self, proc: subprocess.Popen, job_id: str, run_id: str) -> None:
        code = proc.wait()
        with self._lock:
            if self._proc is proc:
                self._proc = None
                self._job = None
            self._finished[job_id] = {"id": job_id, "run_id": run_id, "status": "complete" if code == 0 else "failed", "exit_code": code, "finished_at": _now_iso()}
        try:
            with open(paths.image_jobs_dir() / (job_id + ".log"), "ab") as handle:
                handle.write(("=== exit %s code=%d ===\n" % (_now_iso(), code)).encode())
            (paths.image_jobs_dir() / (job_id + ".pid")).unlink(missing_ok=True)
        except OSError:
            pass

    def job_status(self, job_id: str) -> Optional[dict]:
        with self._lock:
            if self._job and self._job["id"] == job_id and self._proc and self._proc.poll() is None:
                return {**self._job, "status": "running", "exit_code": None}
            if job_id in self._finished:
                return self._finished[job_id].copy()
        log_path = paths.image_jobs_dir() / (job_id + ".log")
        pid_path = paths.image_jobs_dir() / (job_id + ".pid")
        info = _read_pid_info(pid_path)
        if info and _pid_alive(info["pid"]):
            return {"id": job_id, "run_id": info.get("run_id"), "status": "running", "exit_code": None}
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
                return {"id": job_id, "status": "complete" if code == 0 else "failed", "exit_code": code}
            if "=== exit code 0 ===" in text:  # legacy logs
                return {"id": job_id, "status": "complete", "exit_code": 0}
            return {"id": job_id, "status": "failed", "exit_code": 1}
        return None

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            proc = self._proc if self._job and self._job["id"] == job_id else None
        if proc and proc.poll() is None:
            proc.terminate()
            return True
        return False

    def get_log(self, job_id: str, offset: int, limit: int) -> dict:
        return {"job_id": job_id, **read_log_page(paths.image_jobs_dir() / (job_id + ".log"), offset, limit)}


image_runner = ImageRunner()
