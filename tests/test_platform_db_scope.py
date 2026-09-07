from youtube_pipeline.core.state import RunState
from youtube_pipeline.platform_db import PlatformDatabase


def test_same_run_id_cannot_cross_channel_namespace(tmp_path):
    db = PlatformDatabase(tmp_path / "runtime" / "platform.sqlite3")
    first = RunState(
        run_id="same-id", profile="resource_pack", topic="first",
        user_id="u1", channel_id="c1", youtube_channel_id="UC1",
    )
    db.sync_state(first, tmp_path / "users/u1/channels/c1/runs/same-id")

    second = RunState(
        run_id="same-id", profile="resource_pack", topic="second",
        user_id="u2", channel_id="c2", youtube_channel_id="UC2",
    )
    try:
        db.sync_state(second, tmp_path / "users/u2/channels/c2/runs/same-id")
    except ValueError as exc:
        assert "namespace channel khác" in str(exc)
    else:
        raise AssertionError("cross-channel run collision was accepted")

    assert db.has_run("same-id", user_id="u1", channel_id="c1")
    assert not db.has_run("same-id", user_id="u2", channel_id="c2")
