"""Kéo data YouTube — spawn `youtube_pull.py` (project data-analysis-youtube
ngoài repo này) làm subprocess và theo dõi giống PipelineRunner.

Luật bất biến: KHÔNG sửa/copy puller. Chỉ spawn với `cwd = thư mục puller`
để nó tự `load_dotenv()` (OAuth CLIENT_ID/SECRET) và dùng `token.json` sẵn có
(TOKEN_FILE của puller là CWD-relative). Output ghi vào thư mục gốc backend để
`GET /api/config` quét được -> file xuất hiện ngay trong dropdown "Tạo run mới".

Restart giữa chừng: data job là subprocess độc lập (start_new_session, fd kế
thừa, KHÔNG PIPE) — API server chết job vẫn chạy, log vẫn ghi; server mới đọc
lại pid file (json {pid, kind}) -> báo `orphaned: true`; cancel qua pid file.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional

from . import paths

# Scope puller yêu cầu (youtube_pull.py SCOPES, full URL như token.json lưu).
REQUIRED_SCOPES = (
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
)
DEFAULT_DATASET_FILE = "data/channels/youtube_data.json"
DATASET_DIRECTORIES = (Path("data/channels"),)
DATASET_MAX_AGE_HOURS = 24

# Video ID YouTube: 11 ký tự [A-Za-z0-9_-]; cho phép 1-20 để không quá chặt.
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,20}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Thư mục mặc định của puller (đảo ngược theo thứ tự ưu tiên).
FALLBACK_PULL_DIRS = (
    Path.home() / "Data/youtube/video-youtube/external/data-analysis-youtube",
    Path.home() / "Data/youtube/youtube-v2/data-analysis-youtube",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------------ resolve


def resolve_pull_dir() -> Optional[Path]:
    """Thư mục chứa youtube_pull.py: env YT_DATA_PULL_DIR -> mặc định 2 nơi.

    Env được tin tưởng dù thư mục không tồn tại (để UI hiện đường dẫn sai
    thay vì báo "chưa đặt env"); availability kiểm tra is_dir() ở route.
    """
    env = os.environ.get("YT_DATA_PULL_DIR")
    if env:
        return Path(env).expanduser()
    for cand in FALLBACK_PULL_DIRS:
        if cand.is_dir():
            return cand
    return None


def _venv_has_googleapiclient(py: str) -> bool:
    try:
        r = subprocess.run(
            [py, "-c", "import googleapiclient"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


@lru_cache(maxsize=8)
def resolve_pull_python(pull_dir: str) -> str:
    """Python chạy puller: env YT_DATA_PULL_PYTHON -> .venv quanh pull_dir.

    Kiểm tra `import googleapiclient` với từng ứng viên, fallback sys.executable
    (python của API server). Cached theo pull_dir — server thường chạy lâu.
    """
    candidates: list[Path] = []
    env = os.environ.get("YT_DATA_PULL_PYTHON")
    if env:
        candidates.append(Path(env))
    if pull_dir:
        root = Path(pull_dir)
        candidates.extend(
            [
                root / "../../.venv/bin/python",  # video-youtube/.venv (GUI dùng)
                root / "../.venv/bin/python",
                root / ".venv/bin/python",
            ]
        )
    for cand in candidates:
        if cand.is_file() and _venv_has_googleapiclient(str(cand)):
            return str(cand)
    return sys.executable


# ------------------------------------------------------------- command build


def build_connect_command(python: str, *, token_file: Optional[Path] = None) -> list[str]:
    """Build OAuth connect command with an optional isolated token path."""
    code = "import youtube_pull; youtube_pull.get_credentials()"
    argv = [python, "-u", "-c", code]
    if token_file is not None:
        # youtube_pull reads TOKEN_FILE at import time, so set it before import.
        code = "import os; os.environ['TOKEN_FILE'] = %r; import youtube_pull; youtube_pull.get_credentials()" % str(token_file)
        argv[-1] = code
    return argv


def _job_env(user_id: Optional[str], channel_id: Optional[str]) -> dict[str, str]:
    env = os.environ.copy()
    if user_id and channel_id:
        token_file = token_path(paths.backend_root(), user_id=user_id, channel_id=channel_id)
        token_file.parent.mkdir(parents=True, exist_ok=True)
        env["TOKEN_FILE"] = str(token_file)
        # The puller verifies this identity after OAuth authentication.
        try:
            from youtube_pipeline.platform_db import PlatformDatabase
            registered = PlatformDatabase(paths.backend_root() / "runtime" / "platform.sqlite3").get_channel(
                user_id=user_id, channel_id=channel_id, include_inactive=False
            )
        except (OSError, ValueError):
            registered = None
        if registered:
            env["EXPECTED_YOUTUBE_CHANNEL_ID"] = registered["youtube_channel_id"]
    return env


def build_pull_command(
    python: str,
    mode: str,
    out: Path,
    video_ids: Optional[list[str]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    max_comments: Optional[int] = None,
    max_replies: Optional[int] = None,
    no_replies: bool = False,
) -> list[str]:
    # `-u`: unbuffered stdout khi log vào file (xem build_connect_command).
    argv = [python, "-u", "youtube_pull.py", "--out", str(out)]
    if mode == "video_ids":
        argv += ["--videos"] + list(video_ids or [])
    elif mode == "range":
        argv += ["--start-date", str(start_date), "--end-date", str(end_date)]
    elif mode == "all":
        # Puller tự động tìm toàn bộ video trong analytics window mặc định
        # khi không truyền --videos/--start-date/--end-date. Không dùng
        # --all-videos vì youtube_pull.py không có flag này.
        pass
    else:
        raise ValueError("mode không hợp lệ: %s" % mode)
    if max_comments is not None:
        argv += ["--max-comments", str(max_comments)]
    if max_replies is not None:
        argv += ["--max-replies-per-thread", str(max_replies)]
    if no_replies:
        argv.append("--no-replies")
    return argv


def build_reporting_command(python: str, action: str, out: Path) -> list[str]:
    if action == "setup":
        return [python, "-u", "youtube_pull.py", "--setup-reporting"]
    if action == "sync":
        # sync đọc job reporting sẵn có và ghi kết quả vào file --out đã tồn tại.
        return [python, "-u", "youtube_pull.py", "--sync-reporting", "--out", str(out)]
    raise ValueError("action không hợp lệ: %s" % action)


# ---------------------------------------------------------------- validation


def validate_video_ids(video_ids) -> list[str]:
    if not video_ids:
        raise ValueError("video_ids bắt buộc cho mode video_ids")
    ids = [i.strip() for i in video_ids if isinstance(i, str) and i.strip()]
    for i in ids:
        if not _VIDEO_ID_RE.match(i):
            raise ValueError("video ID không hợp lệ: %s" % i)
    return ids


def validate_dates(start_date, end_date) -> tuple[str, str]:
    if not start_date or not end_date:
        raise ValueError("start_date và end_date bắt buộc cho mode range")
    start_date, end_date = str(start_date), str(end_date)
    if not _DATE_RE.match(start_date) or not _DATE_RE.match(end_date):
        raise ValueError("Ngày phải theo định dạng YYYY-MM-DD")
    if start_date > end_date:
        raise ValueError("start_date phải <= end_date")
    return start_date, end_date


def resolve_out_file(out_file: Optional[str] = None, *, user_id: Optional[str] = None, channel_id: Optional[str] = None) -> Path:
    """Resolve a dataset under legacy or channel-scoped data namespace."""
    if bool(user_id) != bool(channel_id):
        raise ValueError("user_id và channel_id phải được truyền cùng nhau")
    name = (out_file or DEFAULT_DATASET_FILE).strip()
    if user_id and channel_id and (out_file is None or name == DEFAULT_DATASET_FILE):
        name = str(paths.channel_data_dir(user_id, channel_id) / "youtube_data.json")
    elif user_id and channel_id and not Path(name).is_absolute() and not name.startswith("users/"):
        name = str(paths.channel_data_dir(user_id, channel_id) / Path(name).name)
    if Path(name).is_absolute():
        out = Path(name).resolve()
    else:
        out = (paths.backend_root() / name).resolve()
    root = paths.backend_root().resolve()
    data_root = (paths.channel_data_dir(user_id, channel_id).resolve() if user_id and channel_id else (root / "data/channels").resolve())
    if not out.is_relative_to(data_root):
        raise ValueError("out_file phải nằm trong namespace channel data")
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def _legacy_resolve_out_file(out_file: Optional[str] = None) -> Path:
    """Legacy implementation retained for callers that need global paths."""
    name = (out_file or DEFAULT_DATASET_FILE).strip()
    if not name.endswith(".json"):
        raise ValueError("out_file phải kết thúc bằng .json")
    root = paths.backend_root().resolve()
    out = (root / name).resolve()
    data_root = (root / "data/channels").resolve()
    if not out.is_relative_to(data_root):
        raise ValueError("out_file phải nằm trong data/channels")
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def _dataset_metadata(path: Path) -> Optional[dict]:
    """Return safe, UI-ready metadata for a persisted channel snapshot."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("videos"), (dict, list)):
        return None
    generated_at = data.get("generated_at")
    age_hours = None
    freshness = "unknown"
    if isinstance(generated_at, str):
        try:
            generated = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
            if generated.tzinfo is None:
                generated = generated.replace(tzinfo=timezone.utc)
            age_hours = max(0.0, (datetime.now(timezone.utc) - generated.astimezone(timezone.utc)).total_seconds() / 3600)
            freshness = "stale" if age_hours > DATASET_MAX_AGE_HOURS else "fresh"
        except ValueError:
            freshness = "invalid_timestamp"
    videos = data["videos"]
    rows = list(videos.values()) if isinstance(videos, dict) else videos
    has_reach = any(
        isinstance(row, dict)
        and isinstance((row.get("analytics") or {}).get("reach"), dict)
        and (row.get("analytics") or {}).get("reach", {}).get("impressions_ctr") is not None
        for row in rows
    )
    root = paths.backend_root().resolve()
    return {
        "file": str(path.resolve().relative_to(root)),
        # Compatibility for consumers that predate explicit dataset metadata.
        "name": str(path.resolve().relative_to(root)),
        "generated_at": generated_at,
        "age_hours": round(age_hours, 1) if age_hours is not None else None,
        "freshness": freshness,
        "video_count": len(rows),
        "channel_id": data.get("channel_id"),
        "analytics_window": data.get("analytics_window"),
        "has_reporting_reach": has_reach,
        "size_bytes": path.stat().st_size,
        "modified_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
    }


def list_datasets(*, user_id: Optional[str] = None, channel_id: Optional[str] = None) -> list[dict]:
    """Discover datasets globally or within one channel namespace."""
    if bool(user_id) != bool(channel_id):
        raise ValueError("user_id và channel_id phải được truyền cùng nhau")
    root = paths.backend_root().resolve()
    found: list[dict] = []
    seen: set[Path] = set()
    directories = [paths.channel_data_dir(user_id, channel_id)] if user_id and channel_id else [root / relative for relative in DATASET_DIRECTORIES]
    for raw_directory in directories:
        directory = Path(raw_directory).resolve()
        if user_id and channel_id:
            directory = directory / "snapshots" if (directory / "snapshots").is_dir() else directory
        else:
            directory = directory

        directory = directory.resolve()
        if not directory.is_dir() or not directory.is_relative_to(root):
            continue
        if not directory.is_dir() or not directory.is_relative_to(root):
            continue
        iterator = directory.rglob("*.json")
        for path in iterator:
            resolved = path.resolve()
            if resolved in seen or not resolved.is_file() or not resolved.is_relative_to(root):
                continue
            seen.add(resolved)
            metadata = _dataset_metadata(resolved)
            if metadata:
                found.append(metadata)
    return sorted(found, key=lambda item: (item.get("generated_at") or "", item["modified_at"]), reverse=True)


def resolve_dataset_file(name: str, *, user_id: Optional[str] = None, channel_id: Optional[str] = None) -> Path:
    """Resolve a dataset from the global catalog or one channel catalog."""
    catalog = {item["file"]: item for item in list_datasets(user_id=user_id, channel_id=channel_id)}
    if name not in catalog:
        raise ValueError("Dataset không tồn tại trong namespace channel hiện tại: %s" % name)
    path = (paths.backend_root().resolve() / name).resolve()
    if not path.is_file():
        raise ValueError("Dataset không còn tồn tại: %s" % name)
    return path


def _scoped_dataset_path(user_id: Optional[str], channel_id: Optional[str], out_file: Optional[str] = None) -> Path:
    return resolve_out_file(out_file, user_id=user_id, channel_id=channel_id)


# ------------------------------------------------------------------ token


def token_path(pull_dir: Path, *, user_id: Optional[str] = None, channel_id: Optional[str] = None) -> Path:
    if bool(user_id) != bool(channel_id):
        raise ValueError("user_id và channel_id phải được truyền cùng nhau")
    if user_id and channel_id:
        return paths.channel_root(user_id, channel_id) / "runtime" / "oauth" / "token.json"
    return pull_dir / "token.json"


def token_status(
    pull_dir: Path,
    *,
    user_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    expected_youtube_channel_id: Optional[str] = None,
) -> dict:
    """Đọc token.json của puller -> {exists, expires_at, scopes_ok}.

    Token hết hạn nhưng refresh được vẫn coi là kết nối được — puller tự
    refresh; `scopes_ok` thiếu scope mới là vấn đề (puller tự exit).
    """
    token_file = token_path(pull_dir, user_id=user_id, channel_id=channel_id)
    if not token_file.is_file():
        return {"exists": False, "expires_at": None, "scopes_ok": False, "identity_ok": None}
    try:
        data = json.loads(token_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"exists": True, "expires_at": None, "scopes_ok": False, "identity_ok": False}
    raw_scopes = data.get("scopes") or []
    # Token lưu list URL scope; vài flow cũ lưu chuỗi cách nhau dấu cách.
    if isinstance(raw_scopes, str):
        raw_scopes = raw_scopes.split()
    scopes = set(raw_scopes)
    identity = data.get("youtube_channel_id")
    # google-auth token.json normally has no channel claim; the puller performs
    # the authoritative ``mine=true`` check at job start.  Only compare a
    # persisted claim when one is available.
    identity_ok = None if expected_youtube_channel_id is None or not identity else identity == expected_youtube_channel_id
    return {
        "exists": True,
        "expires_at": data.get("expiry"),
        "scopes_ok": set(REQUIRED_SCOPES).issubset(scopes),
        "identity_ok": identity_ok,
    }


# ------------------------------------------------------------------ results


def last_result(*, user_id: Optional[str] = None, channel_id: Optional[str] = None) -> Optional[dict]:
    """Return the latest dataset in the requested namespace."""
    preferred = data_runner.last_out_file(user_id=user_id, channel_id=channel_id)
    datasets = list_datasets(user_id=user_id, channel_id=channel_id)
    if preferred:
        match = next((item for item in datasets if item["file"] == preferred), None)
        if match:
            return match
    return datasets[0] if datasets else None


# -------------------------------------------------------------------- runner


class BusyError(Exception):
    """Đã có một data job đang chạy — chuyển thành HTTP 409."""

    def __init__(self, job_id: str) -> None:
        super().__init__("Một data job đang chạy: %s" % job_id)
        self.job_id = job_id


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


def _read_pid_info(pid_file: Path) -> Optional[dict]:
    """pid file là json {pid, kind}; đọc linh hoạt cả trường hợp chỉ số thuần."""
    try:
        raw = pid_file.read_text(encoding="utf-8").strip()
        data = json.loads(raw)
        if isinstance(data, dict):
            pid = int(data.get("pid") or 0)
            kind = data.get("kind")
        else:
            pid = int(data)
            kind = None
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    if pid <= 0:
        return None
    return {
        "pid": pid,
        "kind": kind,
        "user_id": data.get("user_id") if isinstance(data, dict) else None,
        "channel_id": data.get("channel_id") if isinstance(data, dict) else None,
    }


def _write_pid_info(pid_file: Path, pid: int, kind: str, *, user_id: Optional[str] = None, channel_id: Optional[str] = None) -> None:
    pid_file.write_text(json.dumps({"pid": pid, "kind": kind, "user_id": user_id, "channel_id": channel_id}), encoding="utf-8")


def read_log_page(log_file: Path, offset: int, limit: int) -> dict:
    """Chunk log giống GET /api/runs/{id}/log — trả dict để route bọc Response."""
    if not log_file.is_file():
        return {
            "offset": offset,
            "limit": limit,
            "total_lines": 0,
            "next_offset": offset,
            "eof": True,
            "log_exists": False,
            "lines": [],
        }
    lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    total = len(lines)
    start = min(offset, total)
    chunk = lines[start : start + limit]
    return {
        "offset": start,
        "limit": limit,
        "total_lines": total,
        "next_offset": start + len(chunk),
        "eof": start + len(chunk) >= total,
        "log_exists": True,
        "lines": chunk,
    }


def _job_dir(user_id: Optional[str] = None, channel_id: Optional[str] = None) -> Path:
    if bool(user_id) != bool(channel_id):
        raise ValueError("user_id và channel_id phải được truyền cùng nhau")
    if user_id and channel_id:
        return paths.channel_root(user_id, channel_id) / "runtime" / "data-jobs"
    return paths.data_jobs_dir()


class DataPullRunner:
    """Singleton quản lý tối đa một data job (kéo/connect/reporting) đang chạy.

    Độc lập với PipelineRunner — data job không chặn pipeline run và ngược lại.
    Trạng thái job: trong bộ nhớ (proc) hoặc trên đĩa (pid file + marker
    `=== exit code N ===` trong log) — đủ phục vụ cả job mồ côi sau restart.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[tuple[str | None, str | None], tuple[subprocess.Popen, dict]] = {}
        self._finished: dict[tuple[tuple[str | None, str | None], str], dict] = {}
        self._finished_order: list[tuple[tuple[str | None, str | None], str]] = []
        self._last_out_by_scope: dict[tuple[str | None, str | None], str] = {}

    # --------------------------------------------------------------- query

    def active_job(self, *, user_id: Optional[str] = None, channel_id: Optional[str] = None) -> Optional[dict]:
        """Return the active job in legacy or channel namespace."""
        with self._lock:
            return self._active_unlocked(_job_dir(user_id, channel_id))

    def busy(self, *, user_id: Optional[str] = None, channel_id: Optional[str] = None) -> bool:
        return self.active_job(user_id=user_id, channel_id=channel_id) is not None

    def last_out_file(self, *, user_id: Optional[str] = None, channel_id: Optional[str] = None) -> Optional[str]:
        if bool(user_id) != bool(channel_id):
            raise ValueError("user_id và channel_id phải được truyền cùng nhau")
        with self._lock:
            return self._last_out_by_scope.get((user_id, channel_id))

    def _active_unlocked(self, jobs_dir: Optional[Path] = None) -> Optional[dict]:
        for proc, job in self._jobs.values():
            if proc.poll() is None and (jobs_dir is None or Path(job["log_path"]).parent == jobs_dir):
                return {**job, "orphaned": False}
        jobs_dir = jobs_dir or paths.data_jobs_dir()
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
                    "kind": info.get("kind"),
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
        kind: str,
        argv: list[str],
        cwd: Path,
        out_file: Optional[Path] = None,
        *,
        user_id: Optional[str] = None,
        channel_id: Optional[str] = None,
    ) -> dict:
        """Spawn data job mới; trả {id, kind, started_at, log_path}."""
        jobs_dir = _job_dir(user_id, channel_id)
        with self._lock:
            scope = (user_id, channel_id)
            active = self._active_unlocked(jobs_dir)
            if active is not None:
                raise BusyError(str(active["id"]))
            job_id = uuid.uuid4().hex
            log_file = jobs_dir / ("%s.log" % job_id)
            log_file.parent.mkdir(parents=True, exist_ok=True)
            # fd kế thừa — KHÔNG PIPE: server chết -> child không bị SIGPIPE,
            # log tiếp tục ghi, server mới đọc lại được.
            handle = open(log_file, "ab")
            try:
                handle.write(
                    ("=== start %s kind=%s job=%s ===\n" % (_now_iso(), kind, job_id)).encode(
                        "utf-8"
                    )
                )
                handle.flush()
                proc = subprocess.Popen(
                    argv,
                    cwd=str(cwd),  # bắt buộc: puller load .env + token.json theo CWD
                    env=_job_env(user_id, channel_id),
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
                _write_pid_info(jobs_dir / ("%s.pid" % job_id), proc.pid, kind, user_id=user_id, channel_id=channel_id)
            except OSError:
                pass
            started_at = _now_iso()
            job = {
                "id": job_id,
                "kind": kind,
                "started_at": started_at,
                "log_path": str(log_file),
            }
            self._jobs[scope] = (proc, job)
            if out_file is not None:
                self._last_out_by_scope[scope] = str(out_file.resolve().relative_to(paths.backend_root().resolve()))
            threading.Thread(
                target=self._waiter, args=(proc, job_id, kind, started_at, jobs_dir), daemon=True
            ).start()
            return {"id": job_id, "kind": kind, "started_at": started_at, "log_path": str(log_file)}

    def _waiter(self, proc: subprocess.Popen, job_id: str, kind: str, started_at: str, jobs_dir: Path) -> None:
        code = proc.wait()
        with self._lock:
            scope = next((key for key, value in self._jobs.items() if value[0] is proc), (None, None))
            self._jobs.pop(scope, None)
            job = {
                "id": job_id,
                "kind": kind,
                "status": "complete" if code == 0 else "failed",
                "exit_code": code,
                "started_at": started_at,
                "finished_at": _now_iso(),
                "log_path": str(jobs_dir / ("%s.log" % job_id)),
                "user_id": scope[0],
                "channel_id": scope[1],
            }
            self._finished[(scope, job_id)] = job
            self._finished_order.append((scope, job_id))
            while len(self._finished_order) > 20:
                self._finished.pop(self._finished_order.pop(0), None)
        try:
            with open(jobs_dir / ("%s.log" % job_id), "ab") as fh:
                fh.write(("=== exit code %d ===\n" % code).encode("utf-8"))
        except OSError:
            pass
        try:
            (jobs_dir / ("%s.pid" % job_id)).unlink()
        except OSError:
            pass

    # --------------------------------------------------------------- status

    def job_status(self, job_id: str, *, user_id: Optional[str] = None, channel_id: Optional[str] = None) -> Optional[dict]:
        """{id, kind, status, exit_code, started_at, finished_at} | None."""
        jobs_dir = _job_dir(user_id, channel_id)
        scope = (user_id, channel_id)
        with self._lock:
            for job_scope, (proc, job) in self._jobs.items():
                if job_scope == scope and job["id"] == job_id and proc.poll() is None:
                    return {"id": job_id, "kind": job["kind"], "status": "running", "exit_code": None, "started_at": job["started_at"], "finished_at": None, "user_id": user_id, "channel_id": channel_id}
            finished = self._finished.get((scope, job_id))
            if finished is not None:
                return dict(finished)
        # Đường đĩa — phục vụ job mồ côi / sau khi server restart.
        log_file = jobs_dir / ("%s.log" % job_id)
        pid_file = jobs_dir / ("%s.pid" % job_id)
        info = _read_pid_info(pid_file)
        if info is not None and _pid_alive(info["pid"]):
            return {
                "id": job_id,
                "kind": info.get("kind"),
                "status": "running",
                "exit_code": None,
                "started_at": None,
                "finished_at": None,
                "user_id": info.get("user_id"),
                "channel_id": info.get("channel_id"),
            }
        if log_file.is_file():
            text = log_file.read_text(encoding="utf-8", errors="replace")
            markers = re.findall(r"=== exit code (\d+) ===", text)
            if markers:
                code = int(markers[-1])
                return {
                    "id": job_id,
                    "kind": info.get("kind") if info else None,
                    "status": "complete" if code == 0 else "failed",
                    "exit_code": code,
                    "started_at": None,
                    "finished_at": None,
                    "user_id": info.get("user_id") if info else user_id,
                    "channel_id": info.get("channel_id") if info else channel_id,
                }
            # Log tồn tại nhưng không có marker và pid đã chết: server trước
            # chết giữa chừng — báo failed, không biết exit code.
            return {
                "id": job_id,
                "kind": None,
                "status": "failed",
                "exit_code": None,
                "started_at": None,
                "finished_at": None,
            }
        return None

    # --------------------------------------------------------------- cancel

    def cancel(self, job_id: str, *, user_id: Optional[str] = None, channel_id: Optional[str] = None) -> bool:
        """SIGTERM process group in the requested namespace."""
        jobs_dir = _job_dir(user_id, channel_id)
        scope = (user_id, channel_id)
        with self._lock:
            for job_scope, (proc, job) in self._jobs.items():
                if job_scope == scope and job["id"] == job_id and proc.poll() is None:
                    self._terminate(proc)
                    return True
        info = _read_pid_info(jobs_dir / ("%s.pid" % job_id))
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


data_runner = DataPullRunner()
