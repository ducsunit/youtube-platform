from pathlib import Path

import pytest

from youtube_pipeline.channel_context import ChannelContext, validate_scope_id
from youtube_pipeline.api import paths


def test_channel_context_namespaces(tmp_path: Path):
    context = ChannelContext("user-1", "kokoro", "UCL3xu", tmp_path)
    assert context.content_dir == tmp_path / "content"
    assert context.runs_dir == tmp_path / "runs"
    assert context.snapshots_dir == tmp_path / "data/snapshots"
    assert context.to_dict()["flow_profile"] == "resource_pack"


def test_scoped_paths_are_user_channel_specific(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(paths, "_BACKEND_ROOT", tmp_path)
    result = paths.channel_run_dir("user-1", "kokoro", "run-1")
    assert result == tmp_path / "users/user-1/channels/kokoro/runs/run-1"
    assert paths.channel_log_path("user-1", "kokoro", "run-1") == tmp_path / "users/user-1/channels/kokoro/runtime/logs/run-1.log"
    assert paths.channel_pid_path("user-1", "kokoro", "run-1") == tmp_path / "users/user-1/channels/kokoro/runtime/logs/run-1.pid"


def test_scope_ids_reject_traversal():
    with pytest.raises(ValueError):
        validate_scope_id("../other", "channel_id")
