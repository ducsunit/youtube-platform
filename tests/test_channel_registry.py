from pathlib import Path

from youtube_pipeline.platform_db import PlatformDatabase


def test_registry_isolates_users_and_inactive_channels(tmp_path):
    db = PlatformDatabase(tmp_path / "runtime" / "platform.sqlite3")
    db.register_channel(user_id="u1", channel_id="main", youtube_channel_id="UC1")
    db.register_channel(user_id="u2", channel_id="main", youtube_channel_id="UC1")

    assert len(db.list_channels(user_id="u1")) == 1
    assert db.list_channels(user_id="u1")[0]["user_id"] == "u1"
    db.deactivate_channel(user_id="u1", channel_id="main")
    assert db.list_channels(user_id="u1") == []
    assert len(db.list_channels(user_id="u1", include_inactive=True)) == 1
    assert len(db.list_channels(user_id="u2")) == 1


def test_registry_rejects_duplicate_youtube_channel_within_user(tmp_path):
    db = PlatformDatabase(tmp_path / "runtime" / "platform.sqlite3")
    db.register_channel(user_id="u1", channel_id="main", youtube_channel_id="UC1")
    try:
        db.register_channel(user_id="u1", channel_id="other", youtube_channel_id="UC1")
    except ValueError as exc:
        assert "đã được đăng ký" in str(exc)
    else:
        raise AssertionError("duplicate YouTube channel accepted")


def test_registry_requires_complete_scope(tmp_path):
    db = PlatformDatabase(tmp_path / "runtime" / "platform.sqlite3")
    for values in (("", "main", "UC1"), ("u1", "", "UC1"), ("u1", "main", "")):
        try:
            db.register_channel(
                user_id=values[0], channel_id=values[1], youtube_channel_id=values[2]
            )
        except ValueError:
            continue
        raise AssertionError("empty registry field accepted")


def test_registry_rejects_display_label_as_scope_id(tmp_path):
    db = PlatformDatabase(tmp_path / "runtime" / "platform.sqlite3")
    try:
        db.register_channel(
            user_id="dev-user", channel_id="Kênh nhật", youtube_channel_id="UC1",
            title="Kênh nhật",
        )
    except ValueError as exc:
        assert "channel_id không hợp lệ" in str(exc)
    else:
        raise AssertionError("display label accepted as channel scope id")


def test_registry_keeps_display_label_in_title(tmp_path):
    db = PlatformDatabase(tmp_path / "runtime" / "platform.sqlite3")
    channel = db.register_channel(
        user_id="dev-user", channel_id="kenh-nhat", youtube_channel_id="UC1",
        title="Kênh nhật",
    )
    assert channel["channel_id"] == "kenh-nhat"
    assert channel["title"] == "Kênh nhật"
