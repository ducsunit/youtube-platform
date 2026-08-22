"""PipelineRunner — spawn CLI resource-pack làm subprocess và theo dõi nó.

Luật bất biến: server KHÔNG bao giờ ghi/sửa run_state.json của run. Ground
truth trạng thái luôn là file trên đĩa do CLI tự ghi (atomic temp+rename).
Server chỉ quản lý: lệnh spawn, file log, file pid, guard "chỉ 1 pipeline".

Restart giữa chừng: nếu API server chết, child vẫn chạy (fd kế thừa nên log
vẫn ghi; run_state.json vẫn cập nhật). Server mới đọc lại pid file + state ->
báo `orphaned: true`; cancel vẫn hoạt động qua pid file.
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
    """Đã có một pipeline đang chạy — chuyển thành HTTP 409."""

    def __init__(self, run_id: str) -> None:
        super().__init__("Một pipeline đang chạy: %s" % run_id)
        self.run_id = run_id


def build_new_run_command(
    run_id: str,
    run_dir: Path,
    mode: str,
    input_file: Optional[Path] = None,
    manual_topic: Optional[str] = None,
    no_channel_data: bool = False,
) -> list[str]:
    """Lệnh chạy resource-pack worker nội bộ cho UI.

    Lưu ý: demo KHÔNG được kèm --input-file — resource_cli._new_input cho
    input_file ưu tiên hơn --demo (nếu kèm cả hai, demo provider sẽ nhận
    youtube_data.json thật).
    """
    argv = [
        sys.executable,
        "-m",
        "youtube_pipeline.api.pipeline_job",
        "--run-id",
        run_id,
        "--output-dir",
        str(run_dir),
    ]
    if mode == "demo":
        argv.append("--demo")
    else:
        if manual_topic:
            argv.extend(["--manual-topic", manual_topic])
        elif no_channel_data:
            argv.append("--no-channel-data")
        elif input_file is not None:
            argv.extend(["--input-file", str(input_file)])
        else:
            raise ValueError("production cần input_file hoặc manual_topic")
    return argv


def build_resume_command(run_id: str, run_dir: Path) -> list[str]:
    """Resume worker nội bộ cho run do Web UI quản lý."""
    return [
        sys.executable,
        "-m",
        "youtube_pipeline.api.pipeline_job",
        "--resume",
        str(run_dir / "run_state.json"),
        "--output-dir",
        str(run_dir),
    ]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_pid(pid_file: Path) -> Optional[int]:
    try:
        return int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _state_status(run_id: str) -> Optional[str]:
    try:
        state = json.loads(paths.run_state_path(run_id).read_text(encoding="utf-8"))
        return state.get("status")
    except (OSError, json.JSONDecodeError):
        return None


class PipelineRunner:
    """Singleton quản lý tối đa một subprocess pipeline đang chạy."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._run_id: Optional[str] = None
        self._mode: Optional[str] = None

    # ------------------------------------------------------------------ query

    def active_run(self) -> Optional[dict]:
        """{run_id, status, orphaned} | None — proc trong bộ nhớ hoặc pid file."""
        with self._lock:
            return self._active_unlocked()

    def busy(self) -> bool:
        return self.active_run() is not None

    def _active_unlocked(self) -> Optional[dict]:
        if self._proc is not None and self._proc.poll() is None:
            return {"run_id": self._run_id, "status": "running", "orphaned": False}
        logs = paths.logs_dir()
        if not logs.is_dir():
            return None
        for pid_file in sorted(logs.glob("*.pid")):
            run_id = pid_file.stem
            pid = _read_pid(pid_file)
            if pid is None or not _pid_alive(pid):
                try:
                    pid_file.unlink()
                except OSError:
                    pass
                continue
            if _state_status(run_id) == "running":
                return {"run_id": run_id, "status": "running", "orphaned": True}
        return None

    # ------------------------------------------------------------------ start

    def start_new(
        self,
        run_id: str,
        run_dir: Path,
        mode: str,
        input_file: Optional[Path] = None,
        manual_topic: Optional[str] = None,
        no_channel_data: bool = False,
    ) -> Path:
        """Spawn pipeline mới; trả về đường dẫn file log."""
        if (run_dir / "run_state.json").exists():
            raise FileExistsError("Run %s đã tồn tại — dùng resume hoặc chọn run_id khác" % run_id)
        argv = build_new_run_command(run_id, run_dir, mode, input_file, manual_topic, no_channel_data)
        return self._spawn(run_id, argv, mode)

    def resume(self, run_id: str, run_dir: Path) -> Path:
        """Spawn resume; trả về đường dẫn file log."""
        if not (run_dir / "run_state.json").is_file():
            raise FileNotFoundError("Không có run_state.json cho run %s" % run_id)
        argv = build_resume_command(run_id, run_dir)
        return self._spawn(run_id, argv, "resume")

    def _spawn(self, run_id: str, argv: list[str], mode: str) -> Path:
        with self._lock:
            active = self._active_unlocked()
            if active is not None:
                raise BusyError(str(active["run_id"]))
            log_file = paths.log_path(run_id)
            log_file.parent.mkdir(parents=True, exist_ok=True)
            # fd kế thừa — KHÔNG PIPE: server chết -> child không bị SIGPIPE,
            # log tiếp tục ghi, server mới đọc lại được.
            handle = open(log_file, "ab")
            try:
                handle.write(
                    ("=== start %s mode=%s run=%s ===\n" % (_now_iso(), mode, run_id)).encode("utf-8")
                )
                handle.flush()
                proc = subprocess.Popen(
                    argv,
                    cwd=str(paths.backend_root()),  # để child load_dotenv() tìm .env
                    env=os.environ.copy(),
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            except Exception:
                handle.close()
                raise
            # Child đã có fd riêng (kế thừa) — bản của parent đóng lại được ngay,
            # không giữ thì mỗi lần spawn là một fd rò rỉ.
            handle.close()
            try:
                paths.pid_path(run_id).write_text(str(proc.pid), encoding="utf-8")
            except OSError:
                pass
            self._proc = proc
            self._run_id = run_id
            self._mode = mode
            threading.Thread(
                target=self._waiter, args=(proc, run_id), daemon=True
            ).start()
            return log_file

    def _waiter(self, proc: subprocess.Popen, run_id: str) -> None:
        code = proc.wait()
        with self._lock:
            if self._proc is proc:
                self._proc = None
                self._run_id = None
                self._mode = None
        try:
            with open(paths.log_path(run_id), "ab") as fh:
                fh.write(("=== exit code %d ===\n" % code).encode("utf-8"))
        except OSError:
            pass
        try:
            paths.pid_path(run_id).unlink()
        except OSError:
            pass

    # ----------------------------------------------------------------- cancel

    def cancel(self, run_id: str) -> bool:
        """SIGTERM cả process group; đúng cho proc trong bộ nhớ lẫn orphan."""
        with self._lock:
            if (
                self._proc is not None
                and self._run_id == run_id
                and self._proc.poll() is None
            ):
                self._terminate(self._proc)
                return True
        pid = _read_pid(paths.pid_path(run_id))
        if pid is not None and _pid_alive(pid):
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
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


runner = PipelineRunner()
