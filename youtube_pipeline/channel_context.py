"""Identity and filesystem context for one user's YouTube channel.

Phase 1 introduces this boundary without changing the legacy global layout yet.
New channel-aware code should depend on this object instead of constructing
project-root-relative content/data paths directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def validate_scope_id(value: str, field_name: str = "id") -> str:
    value = str(value or "").strip()
    if not _SAFE_ID.fullmatch(value):
        raise ValueError(f"{field_name} không hợp lệ")
    return value


@dataclass(frozen=True)
class ChannelContext:
    """Stable identity plus all channel-scoped roots.

    ``root_dir`` is intentionally supplied by the caller so deployment can
    later choose local disk, a mounted volume, or object storage without
    changing pipeline stages.
    """

    user_id: str
    channel_id: str
    youtube_channel_id: str
    root_dir: Path
    flow_profile: str = "resource_pack"

    def __post_init__(self) -> None:
        validate_scope_id(self.user_id, "user_id")
        validate_scope_id(self.channel_id, "channel_id")
        if not str(self.youtube_channel_id or "").strip():
            raise ValueError("youtube_channel_id không được rỗng")
        if not str(self.flow_profile or "").strip():
            raise ValueError("flow_profile không được rỗng")
        object.__setattr__(self, "root_dir", Path(self.root_dir).resolve())

    @property
    def data_dir(self) -> Path:
        return self.root_dir / "data"

    @property
    def content_dir(self) -> Path:
        return self.root_dir / "content"

    @property
    def config_dir(self) -> Path:
        return self.root_dir / "config"

    @property
    def assets_dir(self) -> Path:
        return self.root_dir / "assets"

    @property
    def runs_dir(self) -> Path:
        return self.root_dir / "runs"

    @property
    def snapshots_dir(self) -> Path:
        return self.data_dir / "snapshots"

    @property
    def topic_history_path(self) -> Path:
        return self.content_dir / "topic-history.json"

    def to_dict(self) -> dict[str, str]:
        return {
            "user_id": self.user_id,
            "channel_id": self.channel_id,
            "youtube_channel_id": self.youtube_channel_id,
            "root_dir": str(self.root_dir),
            "flow_profile": self.flow_profile,
        }
