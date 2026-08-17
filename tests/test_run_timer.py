from youtube_pipeline.core.state import RunState
from youtube_pipeline.core.timing import format_duration, elapsed_seconds


def test_format_duration():
    assert format_duration(0) == "00:00:00"
    assert format_duration(65) == "00:01:05"
    assert format_duration(3661) == "01:01:01"


def test_elapsed_seconds():
    started = "2026-08-17T10:00:00+00:00"
    finished = "2026-08-17T10:01:07+00:00"
    assert elapsed_seconds(started, finished) == 67.0


def test_run_state_roundtrip_with_timer_fields():
    state = RunState(run_id="r1", profile="resource_pack", topic="demo")
    state.execution_started_at = "2026-08-17T10:00:00+00:00"
    state.execution_finished_at = "2026-08-17T10:01:00+00:00"
    state.execution_elapsed_seconds = 60.0
    state.total_started_at = state.execution_started_at
    state.total_finished_at = state.execution_finished_at
    state.total_elapsed_seconds = 60.0

    restored = RunState.from_dict(state.to_dict())
    assert restored.execution_elapsed_seconds == 60.0
    assert restored.total_elapsed_seconds == 60.0
