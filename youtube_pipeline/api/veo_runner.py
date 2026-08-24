"""Runner cho job Veo image-to-video — spawn veo_gen.py làm subprocess.

Giống BuildRunner: singleton + lock, tối đa MỘT veo job đang chạy cùng lúc,
độc lập với pipeline runner / build runner / data runner. Log + pid ở
`runtime/logs/api-veo/`; fd kế thừa KHÔNG PIPE — server chết job vẫn chạy, server
mới đọc lại pid file -> báo `orphaned: true`.
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
from .datapull import _pid_alive, _read_pid_info, kill_process_group, read_log_page


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def veo_jobs_dir() -> Path:
    return paths.veo_jobs_dir()


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
    """Đã có một Veo job đang chạy — chuyển thành HTTP 409."""

    def __init__(self, job_id: str) -> None:
        super().__init__("Một Veo job đang chạy: %s" % job_id)
        self.job_id = job_id


class VeoRunner:
    """Singleton — tối đa một Veo job. Trạng thái trong bộ nhớ hoặc trên đĩa."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._job: Optional[dict] = None
        self._finished: dict[str, dict] = {}

    # --------------------------------------------------------------- query

    def active_job(self) -> Optional[dict]:
        with self._lock:
            return self._active_unlocked()

    def busy(self) -> bool:
        return self.active_job() is not None

    def _active_unlocked(self) -> Optional[dict]:
        if self._proc is not None and self._proc.poll() is None and self._job:
            return dict(self._job)
        # Orphan: server restart nhưng pid file còn.
        jobs_dir = veo_jobs_dir()
        if not jobs_dir.is_dir():
            return None
        for pid_file in jobs_dir.glob("*.pid"):
            info = _read_pid_info(pid_file)
            if info is not None and _pid_alive(info["pid"]):
                return {
                    "id": pid_file.stem,
                    "run_id": info.get("run_id"),
                    "started_at": None,
                    "log_path": str(jobs_dir / ("%s.log" % pid_file.stem)),
                    "orphaned": True,
                }
        return None

    def job_status(self, job_id: str) -> Optional[dict]:
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
        # Orphan / sau server restart — đọc từ đĩa.
        jobs_dir = veo_jobs_dir()
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
            return {"id": job_id, "run_id": None, "status": "failed", "exit_code": None, "started_at": None, "finished_at": None}
        return None

    # --------------------------------------------------------------- start

    def start(self, run_id: str, argv: list[str], cwd: Path) -> dict:
        """Spawn Veo job; trả {id, run_id, started_at, log_path}."""
        with self._lock:
            active = self._active_unlocked()
            if active is not None:
                raise VeoBusyError(str(active["id"]))
            job_id = uuid.uuid4().hex
            jobs_dir = veo_jobs_dir()
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
            # Child đã có fd riêng (kế thừa) — bản của parent đóng lại được ngay,
            # không giữ thì mỗi job start là một fd rò rỉ.
            handle.close()
            try:
                (jobs_dir / ("%s.pid" % job_id)).write_text(
                    json.dumps({"pid": proc.pid, "kind": "veo", "run_id": run_id}),
                    encoding="utf-8",
                )
            except OSError:
                pass
            self._proc = proc
            started_at = _now_iso()
            self._job = {"id": job_id, "run_id": run_id, "started_at": started_at, "log_path": str(log_file)}
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
            finished_at = _now_iso()
            self._finished[job_id] = {
                "id": job_id,
                "run_id": run_id,
                "status": "complete" if code == 0 else "failed",
                "exit_code": code,
                "started_at": started_at,
                "finished_at": finished_at,
            }
            # Giữ tối đa 50 job trong bộ nhớ
            while len(self._finished) > 50:
                self._finished.pop(next(iter(self._finished)))
        try:
            with open(veo_jobs_dir() / ("%s.log" % job_id), "ab") as fh:
                fh.write(("=== exit code %d ===\n" % code).encode("utf-8"))
        except OSError:
            pass
        try:
            (veo_jobs_dir() / ("%s.pid" % job_id)).unlink()
        except OSError:
            pass

    # --------------------------------------------------------------- cancel

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            if (
                self._proc is not None
                and self._job is not None
                and self._job["id"] == job_id
                and self._proc.poll() is None
            ):
                self._terminate(self._proc)
                return True
        info = _read_pid_info(veo_jobs_dir() / ("%s.pid" % job_id))
        if info is not None and _pid_alive(info["pid"]):
            return kill_process_group(info["pid"])
        return False

    def cancel_for_run(self, run_id: str) -> list[str]:
        """Hủy mọi Veo job thuộc run (kể cả orphan sau server restart)."""
        cancelled: list[str] = []
        with self._lock:
            if (
                self._proc is not None
                and self._job is not None
                and self._job.get("run_id") == run_id
                and self._proc.poll() is None
            ):
                self._terminate(self._proc)
                cancelled.append(self._job["id"])
        jobs_dir = veo_jobs_dir()
        if not jobs_dir.is_dir():
            return cancelled
        for pid_file in jobs_dir.glob("*.pid"):
            if pid_file.stem in cancelled:
                continue
            info = _read_pid_info(pid_file)
            if (
                info is not None
                and info.get("run_id") == run_id
                and _pid_alive(info["pid"])
                and kill_process_group(info["pid"])
            ):
                cancelled.append(pid_file.stem)
        return cancelled

    @staticmethod
    def _terminate(proc: subprocess.Popen) -> None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass

    def get_log(self, job_id: str, offset: int = 0, limit: int = 200) -> dict:
        log_file = veo_jobs_dir() / ("%s.log" % job_id)
        return read_log_page(log_file, offset, limit)


veo_runner = VeoRunner()
