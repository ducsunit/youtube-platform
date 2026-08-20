from pathlib import Path


def test_realtime_sse_contract_present():
    routes = Path(__file__).parents[1] / "youtube_pipeline" / "api" / "routes.py"
    text = routes.read_text(encoding="utf-8")
    assert '@router.get("/runs/{run_id}/events")' in text
    assert 'media_type="text/event-stream"' in text
    assert 'execution_elapsed_seconds' in text


def test_run_state_has_execution_clock():
    state = Path(__file__).parents[1] / "youtube_pipeline" / "core" / "state.py"
    text = state.read_text(encoding="utf-8")
    for name in ("execution_started_at", "execution_finished_at", "execution_elapsed_seconds", "total_elapsed_seconds"):
        assert name in text
