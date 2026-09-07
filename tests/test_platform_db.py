import sqlite3

from youtube_pipeline.core.artifacts import ArtifactStore
from youtube_pipeline.core.state import RunState, StageRecord
from youtube_pipeline.infrastructure.model_trace import start_run, trace_parsed_response, trace_request


def _database_path(root):
    return (root.parent.parent if root.parent.name == "runs" else root) / "runtime" / "platform.sqlite3"


def test_state_sync_upserts_run_stage_and_artifact_metadata(tmp_path):
    root = tmp_path / "runs" / "db-run"
    store = ArtifactStore(root)
    state = RunState(run_id="db-run", profile="resource_pack", topic="first topic")
    ref = store.put_text("script", "script/final.txt", "text", "writing")
    state.artifact_index["script"] = ref
    state.stage_records["writing"] = StageRecord("writing", "1", status="passed", attempts=1)
    store.save_state(state)

    state.topic = "updated topic"
    state.stage_records["writing"].attempts = 2
    store.save_state(state)

    connection = sqlite3.connect(_database_path(root))
    assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert connection.execute("SELECT topic FROM runs WHERE run_id='db-run'").fetchone()[0] == "updated topic"
    assert connection.execute("SELECT COUNT(*) FROM run_stages WHERE run_id='db-run'").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM artifacts WHERE run_id='db-run'").fetchone()[0] == 1


def test_model_trace_records_metadata_without_prompt_or_response(tmp_path):
    root = tmp_path / "runs" / "telemetry-run"
    store = ArtifactStore(root)
    store.save_state(RunState(run_id="telemetry-run", profile="resource_pack", topic=""))
    start_run("telemetry-run", {"output_dir": str(root)})
    trace_request("RP_TEST", "test", "openai_compatible", "test-model", "secret system", "secret prompt", 0.2)
    trace_parsed_response("RP_TEST", "test", {"secret": "response"})

    connection = sqlite3.connect(_database_path(root))
    row = connection.execute("SELECT label, provider, model, temperature, status FROM model_calls").fetchone()
    assert row == ("RP_TEST", "openai_compatible", "test-model", 0.2, "succeeded")
    schema = " ".join(part[0] for part in connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='model_calls'"))
    assert "prompt" not in schema.lower()


def test_run_diagnostics_returns_only_safe_model_metadata(tmp_path):
    root = tmp_path / "runs" / "diagnostics-run"
    store = ArtifactStore(root)
    state = RunState(
        run_id="diagnostics-run", profile="resource_pack", topic="",
        config_snapshot={"model_routing": {"profiles": {"writer": {"model": "test"}}}},
    )
    store.save_state(state)
    start_run("diagnostics-run", {"output_dir": str(root)})
    trace_request("RP_SAFE", "safe", "openai_compatible", "test-model", "secret system", "secret prompt", 0.2)
    trace_parsed_response("RP_SAFE", "safe", {"secret": "response"})

    from youtube_pipeline.platform_db import PlatformDatabase
    report = PlatformDatabase(_database_path(root)).run_diagnostics("diagnostics-run")
    assert report is not None
    assert report["routing_snapshot"]["profiles"]["writer"]["model"] == "test"
    assert report["model_calls"]["calls"][0]["label"] == "RP_SAFE"
    assert "prompt" not in str(report).lower()
    assert "response" not in str(report).lower()


def test_channel_registry_isolated_and_rejects_duplicate_youtube_channel(tmp_path):
    from youtube_pipeline.platform_db import PlatformDatabase

    database = PlatformDatabase(tmp_path / "runtime" / "platform.sqlite3")
    first = database.register_channel(
        user_id="user-a", channel_id="main", youtube_channel_id="UC123", title="Main"
    )
    database.register_channel(
        user_id="user-b", channel_id="main", youtube_channel_id="UC123", title="Other user"
    )
    assert [item["channel_id"] for item in database.list_channels(user_id="user-a")] == ["main"]
    assert [item["user_id"] for item in database.list_channels(user_id="user-b")] == ["user-b"]
    assert first["active"] is True

    try:
        database.register_channel(
            user_id="user-a", channel_id="secondary", youtube_channel_id="UC123"
        )
    except ValueError as exc:
        assert "đã được đăng ký" in str(exc)
    else:
        raise AssertionError("duplicate YouTube channel was accepted")


def test_channel_registry_update_and_deactivate(tmp_path):
    from youtube_pipeline.platform_db import PlatformDatabase

    database = PlatformDatabase(tmp_path / "runtime" / "platform.sqlite3")
    database.register_channel(
        user_id="user-a", channel_id="main", youtube_channel_id="UC123"
    )
    updated = database.update_channel(
        user_id="user-a", channel_id="main", title="Updated", flow_profile="custom"
    )
    assert updated is not None
    assert updated["title"] == "Updated"
    assert updated["flow_profile"] == "custom"

    inactive = database.deactivate_channel(user_id="user-a", channel_id="main")
    assert inactive is not None and inactive["active"] is False
    assert database.list_channels(user_id="user-a") == []
    assert database.list_channels(user_id="user-a", include_inactive=True)[0]["active"] is False


def test_channel_registry_validates_required_scope(tmp_path):
    from youtube_pipeline.platform_db import PlatformDatabase

    database = PlatformDatabase(tmp_path / "runtime" / "platform.sqlite3")
    for kwargs in (
        {"user_id": "", "channel_id": "main", "youtube_channel_id": "UC123"},
        {"user_id": "user-a", "channel_id": "", "youtube_channel_id": "UC123"},
        {"user_id": "user-a", "channel_id": "main", "youtube_channel_id": ""},
    ):
        try:
            database.register_channel(**kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError("empty registry scope was accepted")
