from pathlib import Path

from youtube_pipeline.api.datapull import build_connect_command, token_path, token_status


def test_channel_token_path_isolated(tmp_path):
    channel_token = token_path(tmp_path, user_id="user-a", channel_id="channel-a")
    assert channel_token == tmp_path / "users/user-a/channels/channel-a/runtime/oauth/token.json"
    assert token_path(tmp_path) == tmp_path / "token.json"


def test_token_status_uses_channel_token_file(tmp_path):
    path = token_path(tmp_path, user_id="user-a", channel_id="channel-a")
    path.parent.mkdir(parents=True)
    path.write_text('{"scopes": ["https://www.googleapis.com/auth/youtube.force-ssl", "https://www.googleapis.com/auth/yt-analytics.readonly"], "expiry": "tomorrow"}')
    result = token_status(tmp_path, user_id="user-a", channel_id="channel-a")
    assert result["exists"] is True
    assert result["scopes_ok"] is True
    assert token_status(tmp_path)["exists"] is False


def test_connect_command_sets_scoped_token_before_import(tmp_path):
    command = build_connect_command("python", token_file=tmp_path / "token.json")
    assert "TOKEN_FILE" in command[-1]
    assert str(tmp_path / "token.json") in command[-1]
    assert "import youtube_pull" in command[-1]


def test_token_status_reports_claimed_identity_mismatch(tmp_path):
    path = token_path(tmp_path, user_id="user-a", channel_id="channel-a")
    path.parent.mkdir(parents=True)
    path.write_text('{"scopes": [], "youtube_channel_id": "UC-other"}')
    result = token_status(
        tmp_path,
        user_id="user-a",
        channel_id="channel-a",
        expected_youtube_channel_id="UC-registered",
    )
    assert result["identity_ok"] is False
    assert result["scopes_ok"] is False
