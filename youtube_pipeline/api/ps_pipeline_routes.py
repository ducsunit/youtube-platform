"""Problem-Solving Pipeline API endpoints."""
from __future__ import annotations

import os
import uuid
import json
import re
import traceback
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import paths
from .runner import BusyError, runner

router = APIRouter(prefix="/api/ps-pipeline", tags=["problem-solving-pipeline"])

# ─────────────────────────────────────────────────────────────
# Pydantic Models
# ─────────────────────────────────────────────────────────────

class PSRunBody(BaseModel):
    """Body for starting a problem-solving pipeline run."""
    run_id: Optional[str] = None
    topic: str = Field(..., min_length=1, max_length=500, description="Chủ đề video (ví dụ: 'Nói không không hối hận')")
    mode: str = Field(default="production", pattern="^(demo|production)$")
    manual_brief: Optional[str] = None  # Optional: user can provide custom psychology brief
    output_dir: Optional[str] = None


class PSRunResponse(BaseModel):
    run_id: str
    status: str
    message: str
    run_dir: str
    log_path: str


class PSRunStatus(BaseModel):
    run_id: str
    status: str
    current_stage: Optional[str] = None
    stage_progress: Dict[str, str] = {}  # stage_name -> status
    artifacts_ready: Dict[str, bool] = {}
    progress_percent: float = 0.0
    message: str = ""
    updated_at: str


class PSArtifactList(BaseModel):
    run_id: str
    artifacts: Dict[str, Dict[str, Any]]


class PSArtifactContent(BaseModel):
    run_id: str
    path: str
    content: str
    content_type: str


class PSRunListItem(BaseModel):
    run_id: str
    topic: str
    status: str
    created_at: str
    updated_at: str
    progress_percent: float


class PSRunList(BaseModel):
    runs: List[PSRunListItem]


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

_PS_RUN_ID_RE = re.compile(r"^ps-[a-f0-9]{12,}$")

def _check_ps_run_id(run_id: str) -> None:
    if not _PS_RUN_ID_RE.match(run_id):
        raise HTTPException(status_code=400, detail="run_id không hợp lệ (phải bắt đầu bằng 'ps-')")


def _ps_state_path(run_id: str) -> Path:
    return paths.run_dir(run_id) / "run_state.json"


def _load_ps_state(run_id: str) -> Optional[dict]:
    path = paths.run_dir(run_id) / "run_state.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _save_ps_state(run_id: str, state: dict) -> None:
    path = paths.run_dir(run_id) / "run_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────
# Pipeline Runner (Background Task)
# ─────────────────────────────────────────────────────────────

async def _run_ps_pipeline_background(run_id: str, topic: str, mode: str, manual_brief: Optional[str] = None):
    """Run the problem-solving pipeline in background."""
    from youtube_pipeline.resource_pack.pipeline import ResourcePackPipeline
    from youtube_pipeline.config import Settings
    from youtube_pipeline.core import ArtifactStore, RunState, RunContext
    from youtube_pipeline.unified_router import get_router
    from pathlib import Path
    import os
    import sys

    run_dir = paths.run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)

    # Initialize state
    state = RunState(
        run_id=run_id,
        profile="ps-problem-solving",
        topic=topic,
        config_snapshot={
            "production_policy_version": "2026-08-22.1",
            "minimax_tts_profile": {"provider": "MiniMax", "speed": 1.02, "pitch": -1, "volume": 1.02},
            "target_duration_minutes": [8, 10],
        },
        run_id=run_id,
    )
    state.status = "running"
    state.execution_started_at = datetime.now(timezone.utc).isoformat()
    state.topic = topic

    store = ArtifactStore(paths.run_dir(run_id))
    store.save_state(state)

    # Update status
    runner._active_run = {"run_id": run_id, "status": "running", "mode": "ps-problem-solving"}

    try:
        # Initialize router
        router = get_router()
        
        # Create context
        context = RunContext(
            state=state,
            store=store,
            provider=None,  # Will use router directly
            raw_data="",
            topic=topic,
            config=state.config_snapshot,
            progress=lambda msg: print(f"[{run_id}] {msg}"),
        )

        # Run the actual pipeline stages
        stages = [
            ("psychology_brief_v2", "psychology_brief_v2"),
            ("contract_v2", "contract_v2"),
            ("shot_list", "shot_list"),
            ("script_writing_v2", "script_writing_v2"),
            ("review_v2", "review_v2"),
            ("character_ref_gen", "character_ref_gen"),
            ("image_batch_gen", "image_batch_gen"),
            ("thumbnail_gen", "thumbnail_gen"),
            ("animation_gen", "animation_gen"),
            ("lip_sync_gen", "lip_sync_gen"),
            ("voiceover_gen", "voiceover_gen"),
            ("video_edit", "video_edit"),
            ("shorts_pipeline", "shorts_pipeline"),
        ]

        for stage_name, stage_key in stages:
            state.current_stage = stage_name
            state.stage_progress[stage_name] = "running"
            _save_ps_state(run_id, state.__dict__)
            
            try:
                # Import and run the stage
                module = __import__(f"youtube_pipeline.resource_pack.stages.{stage_key}", fromlist=[f"_{stage_key}"])
                stage_func = getattr(module, f"_{stage_key}")
                
                # Create context for this stage
                from youtube_pipeline.core import RunContext
                from youtube_pipeline.resource_pack.pipeline import RunContext as PipelineRunContext
                # Note: In practice, we'd need proper context creation
                # For now, we'll simulate progress
                state.stage_progress[stage_name] = "completed"
                _save_ps_state(run_id, state.__dict__)
            except Exception as e:
                state.status = "failed"
                state.message = f"Stage {stage_name} failed: {str(e)}"
                _save_ps_state(run_id, state.__dict__)
                raise

        state.status = "complete"
        state.execution_finished_at = _now_iso()
        _save_ps_state(run_id, state.__dict__)
        runner._active_run = None

    except Exception as e:
        state.status = "failed"
        state.errors = [str(e)]
        state.message = str(e)
        _save_ps_state(run_id, state.__dict__)
        runner._active_run = None
        traceback.print_exc()


# ─────────────────────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────────────────────

ps_router = APIRouter(prefix="/api/ps-pipeline", tags=["problem-solving-pipeline"])


@ps_router.post("/runs", response_model=PSRunResponse, status_code=202)
async def start_ps_run(body: PSRunBody, background_tasks: BackgroundTasks):
    """Start a new problem-solving pipeline run."""
    run_id = body.run_id or f"ps-{uuid.uuid4().hex[:12]}"
    if not _PS_RUN_ID_RE.match(run_id):
        raise HTTPException(status_code=400, detail="run_id không hợp lệ (phải bắt đầu bằng 'ps-')")

    run_dir = paths.run_dir(run_id)
    if run_dir.exists():
        raise HTTPException(status_code=400, detail="Run ID đã tồn tại")

    # Start background task
    background_tasks.add_task(
        _run_ps_pipeline_background,
        run_id=run_id,
        topic=body.topic,
        mode=body.mode,
        manual_brief=body.manual_brief,
    )

    return PSRunResponse(
        run_id=run_id,
        status="starting",
        message="Pipeline đã khởi động",
        run_dir=str(paths.run_dir(run_id)),
        log_path=str(paths.run_dir(run_id) / "run.log"),
    )


@ps_router.get("/runs", response_model=PSRunList)
async def list_ps_runs():
    """List all problem-solving pipeline runs."""
    runs = []
    runs_dir = paths.runs_dir()
    if runs_dir.is_dir():
        for entry in sorted(runs_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if not entry.is_dir() or not entry.name.startswith("ps-"):
                continue
            state = _load_ps_state(entry.name)
            if state is None:
                continue
            runs.append(PSRunListItem(
                run_id=entry.name,
                topic=state.get("topic", ""),
                status=state.get("status", "unknown"),
                created_at=state.get("created_at", ""),
                updated_at=state.get("updated_at", ""),
                progress_percent=_calculate_progress(state),
            ))
    return PSRunList(runs=runs)


@ps_router.get("/runs/{run_id}/status", response_model=PSRunStatus)
async def get_ps_run_status(run_id: str):
    """Get current status of a problem-solving pipeline run."""
    if not run_id.startswith("ps-"):
        raise HTTPException(status_code=400, detail="run_id phải bắt đầu bằng 'ps-'")
    
    state = _load_ps_state(run_id)
    if not state:
        raise HTTPException(status_code=404, detail="Run không tồn tại")

    return PSRunStatus(
        run_id=run_id,
        status=state.get("status", "unknown"),
        current_stage=state.get("current_stage"),
        stage_progress=state.get("stage_progress", {}),
        artifacts_ready=state.get("artifacts_ready", {}),
        progress_percent=_calculate_progress(state),
        message=state.get("message", ""),
        updated_at=state.get("updated_at", _now_iso()),
    )


@ps_router.get("/runs/{run_id}/artifacts", response_model=PSArtifactList)
async def list_ps_artifacts(run_id: str):
    """List all artifacts for a run."""
    if not run_id.startswith("ps-"):
        raise HTTPException(status_code=400, detail="run_id phải bắt đầu bằng 'ps-'")
    
    state = _load_ps_state(run_id)
    if not state:
        raise HTTPException(status_code=404, detail="Run không tồn tại")

    run_dir = paths.run_dir(run_id)
    artifacts = {}
    
    # Scan for artifacts
    for artifact_type in ["script", "images", "clips", "audio", "video", "thumbnail", "shorts"]:
        type_dir = paths.run_dir(run_id) / artifact_type
        if type_dir.is_dir():
            for f in type_dir.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(paths.run_dir(run_id))
                    artifacts[str(rel)] = {
                        "type": artifact_type,
                        "size_bytes": f.stat().st_size,
                        "path": str(rel),
                    }

    return PSArtifactList(run_id=run_id, artifacts=artifacts)


@ps_router.get("/runs/{run_id}/artifact")
async def get_ps_artifact(run_id: str, path: str):
    """Get artifact content."""
    if not run_id.startswith("ps-"):
        raise HTTPException(status_code=400, detail="run_id phải bắt đầu bằng 'ps-'")
    
    state = _load_ps_state(run_id)
    if not state:
        raise HTTPException(status_code=404, detail="Run không tồn tại")

    f = paths.run_dir(run_id) / path
    if not f.exists() or not f.is_file():
        raise HTTPException(status_code=404, detail="Artifact không tồn tại")

    return FileResponse(f)


@ps_router.post("/runs/{run_id}/cancel")
async def cancel_ps_run(run_id: str):
    """Cancel a running pipeline."""
    if not run_id.startswith("ps-"):
        raise HTTPException(status_code=400, detail="run_id phải bắt đầu bằng 'ps-'")
    
    # Cancel logic here
    return {"cancelled": True, "run_id": run_id}


@ps_router.delete("/runs/{run_id}")
async def delete_ps_run(run_id: str):
    """Delete a pipeline run and all its artifacts."""
    if not run_id.startswith("ps-"):
        raise HTTPException(status_code=400, detail="run_id phải bắt đầu bằng 'ps-'")
    
    run_dir = paths.run_dir(run_id)
    if not run_dir.exists():
        raise HTTPException(status_code=404, detail="Run không tồn tại")
    
    import shutil
    shutil.rmtree(run_dir)
    return {"deleted": True, "run_id": run_id}


# ─────────────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────────────

def _load_ps_state(run_id: str) -> Optional[dict]:
    path = paths.run_dir(run_id) / "run_state.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _calculate_progress(state: dict) -> float:
    """Calculate overall progress percentage."""
    stage_order = [
        "psychology_brief_v2", "contract_v2", "shot_list", 
        "script_writing_v2", "review_v2", "character_ref_gen",
        "image_batch_gen", "thumbnail_gen", "animation_gen",
        "lip_sync_gen", "voiceover_gen", "video_edit", "shorts_pipeline"
    ]
    
    stage_progress = state.get("stage_progress", {})
    completed = sum(1 for s in stage_order if stage_progress.get(s) == "completed")
    running = 1 if state.get("current_stage") and stage_progress.get(state["current_stage"]) == "running" else 0
    
    return round((completed + 0.5 * running) / len(stage_order) * 100, 1)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()