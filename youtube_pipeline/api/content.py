"""Đọc artifact an toàn: guard traversal, content-type, JSON pretty, cap inline."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import HTTPException

INLINE_MAX_BYTES = 10 * 1024 * 1024  # 10 MB

_TEXT_SUFFIXES = {".txt", ".md", ".srt", ".tsv", ".csv", ".vtt"}
_AUDIO = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
}
_IMAGE = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
_VIDEO = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
}


def content_type_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "application/json"
    if suffix in _TEXT_SUFFIXES:
        return "text/plain; charset=utf-8"
    if suffix in _AUDIO:
        return _AUDIO[suffix]
    if suffix in _IMAGE:
        return _IMAGE[suffix]
    if suffix in _VIDEO:
        return _VIDEO[suffix]
    return "application/octet-stream"


def resolve_artifact(run_dir: Path, rel_path: str) -> Path:
    """Giải quyết path tương đối trong run_dir với guard traversal 3 bước.

    1) path rỗng / absolute / chứa segment ".." (hoặc backslash) -> 400
    2) resolve() phải nằm trong run_dir (cũng chặn symlink trỏ ra ngoài) -> 404
    3) phải là file -> 404
    """
    if not rel_path:
        raise HTTPException(status_code=400, detail="Thiếu tham số path")
    if rel_path.startswith("/") or "\\" in rel_path:
        raise HTTPException(status_code=400, detail="path phải tương đối")
    parts = Path(rel_path).parts
    if not parts or any(p in ("..", "") for p in parts):
        raise HTTPException(status_code=400, detail="path không hợp lệ")
    root = run_dir.resolve()
    candidate = (run_dir / rel_path).resolve()
    if not candidate.is_relative_to(root):
        raise HTTPException(status_code=404, detail="File nằm ngoài run dir")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Không tìm thấy file: %s" % rel_path)
    return candidate


def inline_body(path: Path, ctype: str) -> bytes:
    """Body inline: JSON pretty (indent=2, giữ tiếng Nhật), cap 10MB."""
    size = path.stat().st_size
    if size > INLINE_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "message": "File quá lớn để xem — hãy tải về",
                "key": "too_large",
                "size_bytes": size,
            },
        )
    if ctype == "application/json":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        except (OSError, json.JSONDecodeError):
            pass  # JSON hỏng -> trả bytes thô
    return path.read_bytes()
