"""Detached runner for Japanese script-to-SRT jobs."""
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
from .datapull import _read_pid_info, kill_process_group, read_log_page


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SrtBusyError(Exception):
    def __init__(self, job_id: str) -> None:
        super().__init__("Một job gen SRT đang chạy: %s" % job_id)
        self.job_id = job_id


class SrtRunner:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._job: Optional[dict] = None
        self._finished: dict[str, dict] = {}

    def _active_unlocked(self) -> Optional[dict]:
        if self._proc is not None and self._proc.poll() is None and self._job:
            return {**self._job, "status": "running", "orphaned": False}
        directory = paths.srt_jobs_dir()
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

    def start(self, run_id: str, run_dir: Path, audio: Path, model: str, device: str, mode: str, max_chars: int) -> dict:
        with self._lock:
            active = self._active_unlocked()
            if active:
                raise SrtBusyError(str(active["id"]))
            job_id = uuid.uuid4().hex
            output = run_dir / "subtitles" / "subtitles.srt"
            log_path = paths.srt_jobs_dir() / (job_id + ".log")
            log_path.parent.mkdir(parents=True, exist_ok=True)
            argv = [sys.executable, "-u", "-m", "youtube_pipeline.srt_job", str(run_dir / "script" / "script.txt"), str(audio), str(output), model, device, mode, str(max_chars)]
            handle = open(log_path, "ab")
            handle.write(("=== start %s kind=srt job=%s run=%s ===\n" % (_now_iso(), job_id, run_id)).encode())
            handle.flush()
            try:
                proc = subprocess.Popen(argv, cwd=str(paths.backend_root()), env=os.environ.copy(), stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
            finally:
                handle.close()
            (paths.srt_jobs_dir() / (job_id + ".pid")).write_text(json.dumps({"pid": proc.pid, "kind": "srt", "run_id": run_id}), encoding="utf-8")
            self._proc = proc
            self._job = {"id": job_id, "run_id": run_id, "started_at": _now_iso(), "log_path": str(log_path), "output_path": "subtitles/subtitles.srt"}
            threading.Thread(target=self._waiter, args=(proc, job_id, run_id), daemon=True).start()
            return self._job.copy()

    def _waiter(self, proc: subprocess.Popen, job_id: str, run_id: str) -> None:
        code = proc.wait()
        with self._lock:
            if self._proc is proc:
                self._proc = None
                self._job = None
            self._finished[job_id] = {"id": job_id, "run_id": run_id, "status": "complete" if code == 0 else "failed", "exit_code": code, "finished_at": _now_iso(), "output_path": "subtitles/subtitles.srt"}
        try:
            with open(paths.srt_jobs_dir() / (job_id + ".log"), "ab") as handle:
                handle.write(("=== exit code %d ===\n" % code).encode())
            (paths.srt_jobs_dir() / (job_id + ".pid")).unlink(missing_ok=True)
        except OSError:
            pass

    def job_status(self, job_id: str) -> Optional[dict]:
        with self._lock:
            if self._job and self._job["id"] == job_id and self._proc and self._proc.poll() is None:
                return {**self._job, "status": "running", "exit_code": None}
            if job_id in self._finished:
                return self._finished[job_id].copy()
        log_path = paths.srt_jobs_dir() / (job_id + ".log")
        info = _read_pid_info(paths.srt_jobs_dir() / (job_id + ".pid"))
        if info and _pid_alive(info["pid"]):
            return {"id": job_id, "run_id": info.get("run_id"), "status": "running", "exit_code": None}
        if log_path.is_file():
            text = log_path.read_text(encoding="utf-8", errors="replace")
            code = 0 if "=== exit code 0 ===" in text else 1
            return {"id": job_id, "status": "complete" if code == 0 else "failed", "exit_code": code, "output_path": "subtitles/subtitles.srt"}
        return None

    def _terminate_job(self, job_id: str) -> bool:
        """Killpg proc trong bộ nhớ hoặc orphan qua pid file. True nếu đã gửi tín hiệu."""
        with self._lock:
            if self._proc is not None and self._job and self._job["id"] == job_id and self._proc.poll() is None:
                if not kill_process_group(self._proc.pid):
                    self._proc.terminate()  # fallback: SIGTERM riêng pid chính
                return True
        info = _read_pid_info(paths.srt_jobs_dir() / (job_id + ".pid"))
        if info and _pid_alive(info["pid"]):
            return kill_process_group(info["pid"])
        return False

    def cancel(self, job_id: str) -> bool:
        return self._terminate_job(job_id)

    def cancel_for_run(self, run_id: str) -> list[str]:
        """Hủy mọi job SRT thuộc run (kể cả orphan sau restart)."""
        cancelled: list[str] = []
        with self._lock:
            if self._proc is not None and self._job and self._job.get("run_id") == run_id and self._proc.poll() is None:
                kill_process_group(self._proc.pid)
                cancelled.append(self._job["id"])
        directory = paths.srt_jobs_dir()
        if directory.is_dir():
            for pid_file in directory.glob("*.pid"):
                info = _read_pid_info(pid_file)
                if info and info.get("run_id") == run_id and _pid_alive(info["pid"]) and pid_file.stem not in cancelled:
                    if kill_process_group(info["pid"]):
                        cancelled.append(pid_file.stem)
        return cancelled

    def get_log(self, job_id: str, offset: int, limit: int) -> dict:
        return {"job_id": job_id, **read_log_page(paths.srt_jobs_dir() / (job_id + ".log"), offset, limit)}


srt_runner = SrtRunner()
