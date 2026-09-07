"""Subprocess runner for resource-pack pipeline runs.

Runs are isolated by ``(user_id, channel_id)`` when channel context is supplied;
legacy callers without a scope retain the original global namespace and one-run
busy guard.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import paths


class BusyError(Exception):
    def __init__(self, run_id: str) -> None:
        super().__init__("Một pipeline đang chạy: %s" % run_id)
        self.run_id = run_id


def _scope(user_id: str | None, channel_id: str | None) -> tuple[str | None, str | None]:
    if bool(user_id) != bool(channel_id):
        raise ValueError("user_id và channel_id phải được truyền cùng nhau")
    return user_id, channel_id


def build_new_run_command(run_id: str, run_dir: Path, mode: str,
                          input_file: Optional[Path] = None,
                          manual_topic: Optional[str] = None,
                          no_channel_data: bool = False,
                          user_id: Optional[str] = None,
                          channel_id: Optional[str] = None,
                          youtube_channel_id: Optional[str] = None,
                          flow_profile: Optional[str] = None,
                          approved_research_brief: Optional[Path] = None) -> list[str]:
    argv = [sys.executable, "-m", "youtube_pipeline.api.pipeline_job", "--run-id", run_id,
            "--output-dir", str(run_dir)]
    if user_id: argv.extend(["--user-id", user_id])
    if channel_id: argv.extend(["--channel-id", channel_id])
    if youtube_channel_id: argv.extend(["--youtube-channel-id", youtube_channel_id])
    if flow_profile: argv.extend(["--flow-profile", flow_profile])
    if approved_research_brief: argv.extend(["--approved-research-brief", str(approved_research_brief)])
    if mode == "demo":
        argv.append("--demo")
    else:
        if approved_research_brief:
            argv.append("--no-channel-data")
        elif manual_topic: argv.extend(["--manual-topic", manual_topic])
        elif no_channel_data: argv.append("--no-channel-data")
        elif input_file is not None: argv.extend(["--input-file", str(input_file)])
        else: raise ValueError("production cần input_file hoặc manual_topic")
    return argv


def build_resume_command(run_id: str, run_dir: Path, *, user_id: str | None = None,
                          channel_id: str | None = None,
                          youtube_channel_id: str | None = None,
                          flow_profile: str | None = None) -> list[str]:
    argv = [sys.executable, "-m", "youtube_pipeline.api.pipeline_job", "--resume",
            str(run_dir / "run_state.json"), "--output-dir", str(run_dir)]
    if user_id: argv.extend(["--user-id", user_id])
    if channel_id: argv.extend(["--channel-id", channel_id])
    if youtube_channel_id: argv.extend(["--youtube-channel-id", youtube_channel_id])
    if flow_profile: argv.extend(["--flow-profile", flow_profile])
    return argv


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pid_alive(pid: int) -> bool:
    if pid <= 0: return False
    try: os.kill(pid, 0)
    except ProcessLookupError: return False
    except PermissionError: return True
    return True


def _read_pid(pid_file: Path) -> Optional[int]:
    try: return int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError): return None


class PipelineRunner:
    """At most one pipeline per namespace; disk state survives API restart."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._procs: dict[tuple[str | None, str | None], tuple[subprocess.Popen, str, Path, Path, Path]] = {}
        # Compatibility attributes retained for existing tests/callers.
        self._proc: Optional[subprocess.Popen] = None
        self._run_id: Optional[str] = None
        self._mode: Optional[str] = None
        self._log_file: Optional[Path] = None
        self._pid_file: Optional[Path] = None

    @staticmethod
    def _scoped_job_paths(run_dir: Path, run_id: str) -> tuple[Path, Path]:
        run_dir = Path(run_dir).resolve()
        parts = run_dir.parts
        if "users" in parts and run_dir.parent.name == "runs":
            i = parts.index("users")
            try:
                return (paths.channel_log_path(parts[i + 1], parts[i + 3], run_id),
                        paths.channel_pid_path(parts[i + 1], parts[i + 3], run_id))
            except IndexError: pass
        return paths.log_path(run_id), paths.pid_path(run_id)

    @staticmethod
    def _state_status_at(run_dir: Path) -> Optional[str]:
        try: return json.loads((Path(run_dir) / "run_state.json").read_text(encoding="utf-8")).get("status")
        except (OSError, json.JSONDecodeError): return None

    def _active_unlocked(self, scope: tuple[str | None, str | None] = (None, None)) -> Optional[dict]:
        current = self._procs.get(scope)
        if current and current[0].poll() is None:
            _, run_id, run_dir, log_file, _ = current
            return {"run_id": run_id, "status": "running", "orphaned": False,
                    "user_id": scope[0], "channel_id": scope[1], "run_dir": str(run_dir),
                    "log_path": str(log_file)}
        log_dir = paths.channel_log_dir(*scope) if scope[0] and scope[1] else paths.logs_dir()
        if not log_dir.is_dir(): return None
        for pid_file in sorted(log_dir.glob("*.pid")):
            pid = _read_pid(pid_file)
            if pid is None or not _pid_alive(pid):
                pid_file.unlink(missing_ok=True); continue
            run_id = pid_file.stem
            run_dir = paths.channel_run_dir(scope[0], scope[1], run_id) if scope[0] and scope[1] else paths.run_dir(run_id)
            if self._state_status_at(run_dir) == "running":
                return {"run_id": run_id, "status": "running", "orphaned": True,
                        "user_id": scope[0], "channel_id": scope[1],
                        "run_dir": str(run_dir), "log_path": str(pid_file.with_suffix(".log"))}
        return None

    def active_run(self, *, user_id: str | None = None, channel_id: str | None = None) -> Optional[dict]:
        scope = _scope(user_id, channel_id)
        with self._lock: return self._active_unlocked(scope)

    def busy(self, *, user_id: str | None = None, channel_id: str | None = None) -> bool:
        return self.active_run(user_id=user_id, channel_id=channel_id) is not None

    def start_new(self, run_id: str, run_dir: Path, mode: str, input_file: Optional[Path] = None,
                  manual_topic: Optional[str] = None, no_channel_data: bool = False,
                  user_id: Optional[str] = None, channel_id: Optional[str] = None,
                  youtube_channel_id: Optional[str] = None, flow_profile: Optional[str] = None,
                  approved_research_brief: Optional[Path] = None) -> Path:
        if (run_dir / "run_state.json").exists(): raise FileExistsError("Run %s đã tồn tại — dùng resume hoặc chọn run_id khác" % run_id)
        argv = build_new_run_command(run_id, run_dir, mode, input_file, manual_topic, no_channel_data,
                                     user_id, channel_id, youtube_channel_id, flow_profile, approved_research_brief)
        return self._spawn(run_id, argv, mode, run_dir, user_id, channel_id)

    def resume(self, run_id: str, run_dir: Path, *, user_id: str | None = None,
               channel_id: str | None = None, youtube_channel_id: str | None = None,
               flow_profile: str | None = None) -> Path:
        if not (run_dir / "run_state.json").is_file(): raise FileNotFoundError("Không có run_state.json cho run %s" % run_id)
        return self._spawn(
            run_id,
            build_resume_command(
                run_id,
                run_dir,
                user_id=user_id,
                channel_id=channel_id,
                youtube_channel_id=youtube_channel_id,
                flow_profile=flow_profile,
            ),
            "resume", run_dir, user_id, channel_id,
        )

    def _spawn(self, run_id: str, argv: list[str], mode: str, run_dir: Path,
               user_id: str | None, channel_id: str | None) -> Path:
        scope = _scope(user_id, channel_id)
        with self._lock:
            active = self._active_unlocked(scope)
            if active: raise BusyError(str(active["run_id"]))
            log_file, pid_file = self._scoped_job_paths(run_dir, run_id)
            log_file.parent.mkdir(parents=True, exist_ok=True)
            handle = open(log_file, "ab")
            try:
                handle.write(("=== start %s mode=%s run=%s ===\n" % (_now_iso(), mode, run_id)).encode())
                handle.flush()
                proc = subprocess.Popen(argv, cwd=str(paths.backend_root()), env=os.environ.copy(),
                                        stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
            except Exception:
                handle.close(); raise
            handle.close()
            pid_file.write_text(str(proc.pid), encoding="utf-8")
            self._procs[scope] = (proc, run_id, run_dir, log_file, pid_file)
            # Preserve legacy introspection for unscoped callers.
            if scope == (None, None): self._proc, self._run_id, self._mode, self._log_file, self._pid_file = proc, run_id, mode, log_file, pid_file
            threading.Thread(target=self._waiter, args=(proc, scope, run_id, log_file, pid_file), daemon=True).start()
            return log_file

    def _waiter(self, proc: subprocess.Popen, scope, run_id: str, log_file: Path, pid_file: Path) -> None:
        code = proc.wait()
        with self._lock:
            current = self._procs.get(scope)
            if current and current[0] is proc: self._procs.pop(scope, None)
            if scope == (None, None): self._proc = self._run_id = self._mode = self._log_file = self._pid_file = None
        try: log_file.open("ab").write(("=== exit code %d ===\n" % code).encode())
        except OSError: pass
        pid_file.unlink(missing_ok=True)

    def cancel(self, run_id: str, *, user_id: str | None = None, channel_id: str | None = None) -> bool:
        scope = _scope(user_id, channel_id)
        with self._lock:
            current = self._procs.get(scope)
            if current and current[1] == run_id and current[0].poll() is None:
                self._terminate(current[0]); return True
        run_dir = paths.channel_run_dir(user_id, channel_id, run_id) if user_id and channel_id else paths.run_dir(run_id)
        _, pid_file = self._scoped_job_paths(run_dir, run_id)
        pid = _read_pid(pid_file)
        if pid and _pid_alive(pid):
            try: os.killpg(os.getpgid(pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError): return False
            return True
        return False

    @staticmethod
    def _terminate(proc: subprocess.Popen) -> None:
        try: os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError): pass


runner = PipelineRunner()
