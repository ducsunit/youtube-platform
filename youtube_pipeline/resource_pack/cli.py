from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Optional, Sequence

from ..config import Settings, channel_data_path_from_env
from ..infrastructure.logging import configure_logging, configure_model_call_logging
from ..infrastructure.model_trace import finish_run, start_run
from .pipeline import ResourcePackPipeline
from .providers import AIResourceProvider, DemoResourceProvider
from ..core.timing import format_duration

logger = logging.getLogger(__name__)


def build_resource_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="youtube-pipeline resource-pack",
        description="Tạo bộ tài nguyên video tiếng Nhật để gen audio/ảnh và dựng thủ công.",
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--input", help="Dữ liệu kênh dạng text/JSON.")
    source.add_argument("--input-file", type=Path, help="File JSON UTF-8, thường là youtube_data.json.")
    source.add_argument("--resume", type=Path, help="run_state.json của resource pack đang dở.")
    source.add_argument("--resume-legacy", type=Path, help="Checkpoint legacy; chỉ tái sử dụng raw_youtube_data.")
    parser.add_argument("--output-dir", type=Path, help="Thư mục run; mặc định runs/<run-id>.")
    parser.add_argument("--run-id", help="Run ID ổn định; mặc định sinh UUID.")
    parser.add_argument("--demo", action="store_true", help="Dùng provider deterministic, không gọi API.")
    return parser


def _read_input_file(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError("Không đọc được input file %s: %s" % (path, exc)) from exc
    except json.JSONDecodeError as exc:
        raise ValueError("Input file không phải JSON hợp lệ: %s" % exc.msg) from exc
    if not isinstance(data, (dict, list)) or not data:
        raise ValueError("Input JSON phải là object/array không rỗng.")
    return json.dumps(data, ensure_ascii=False, indent=2)


def _new_input(args: argparse.Namespace, parser: argparse.ArgumentParser) -> str:
    if args.input_file:
        raw_data = _read_input_file(args.input_file)
    elif args.input:
        raw_data = args.input
    elif args.resume_legacy:
        try:
            legacy = json.loads(args.resume_legacy.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ValueError("Không đọc được legacy checkpoint: %s" % exc) from exc
        except json.JSONDecodeError as exc:
            raise ValueError("Legacy checkpoint không phải JSON hợp lệ: %s" % exc.msg) from exc
        raw_data = legacy.get("raw_youtube_data") if isinstance(legacy, dict) else None
        if not isinstance(raw_data, str) or not raw_data.strip():
            raise ValueError("Legacy checkpoint thiếu raw_youtube_data.")
    elif args.demo:
        raw_data = json.dumps(
            {
                "schema_version": 2,
                "generated_at": "demo",
                "videos": {},
            },
            ensure_ascii=False,
        )
    else:
        env_path = channel_data_path_from_env()
        if env_path:
            raw_data = _read_input_file(env_path)
        else:
            parser.error("Cần --input, --input-file, --resume, --resume-legacy, --demo hoặc YOUTUBE_CHANNEL_DATA_FILE.")
    return raw_data


def resource_main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_resource_parser()
    args = parser.parse_args(argv)
    trace_started = False
    try:
        log_path = configure_logging()
        model_log_path = configure_model_call_logging()
        if args.resume:
            state_path = args.resume
            if state_path.name != "run_state.json":
                raise ValueError("--resume phải trỏ tới run_state.json.")
            output_dir = args.output_dir or state_path.parent
            if output_dir.resolve() != state_path.parent.resolve():
                raise ValueError("--output-dir phải trùng thư mục chứa checkpoint khi resume.")
            bootstrap = ResourcePackPipeline(DemoResourceProvider(), output_dir, max_retries=1)
            state = bootstrap.load_state()
            complete = state.status == "complete"
            provider = (
                DemoResourceProvider()
                if args.demo or complete
                else AIResourceProvider(
                    Settings.from_env(require_keys=False),
                    routing_snapshot=state.config_snapshot.get("model_routing"),
                )
            )
            pipeline = ResourcePackPipeline(
                provider,
                output_dir,
                max_retries=1 if args.demo or complete else provider.max_retries,
                retry_delay=0 if args.demo or complete else 1,
                progress=print,
            )
        else:
            raw_data = _new_input(args, parser)
            run_id = args.run_id or uuid.uuid4().hex
            output_dir = args.output_dir or Path("runs") / run_id
            provider = DemoResourceProvider() if args.demo else AIResourceProvider(Settings.from_env(require_keys=False))
            pipeline = ResourcePackPipeline(
                provider,
                output_dir,
                max_retries=1 if args.demo else provider.max_retries,
                retry_delay=0 if args.demo else 1,
                progress=print,
            )
            state = pipeline.create_state(raw_data, run_id=run_id)
            if args.resume_legacy:
                legacy_payload = json.loads(args.resume_legacy.read_text(encoding="utf-8"))
                migration = {
                    "source_checkpoint": str(args.resume_legacy),
                    "legacy_completed_steps": legacy_payload.get("completed_steps", []),
                    "reused": ["raw_youtube_data"],
                "not_reused": ["legacy_proposal", "legacy_draft", "final_script"],
                    "reason": "Resource-pack source/language/character gates phải chạy lại.",
                }
                ref = pipeline.store.put_json(
                    "legacy_migration",
                    "research/legacy-migration.json",
                    migration,
                    "input",
                )
                state.artifact_index["legacy_migration"] = ref
                pipeline.store.save_state(state)

        start_run(
            state.run_id,
            {
                "profile": "resource_pack",
                "mode": "demo" if args.demo else "production",
                "output_dir": str(output_dir),
                "topic": state.topic or "PENDING_MODEL_SELECTION",
            },
        )
        trace_started = True
        print("=== YOUTUBE JP RESOURCE PACK — PHASE 1 ===")
        state = pipeline.run(state)
        manifest = output_dir / "resource_manifest.json"
        print("\nHoàn tất resource pack: %s" % output_dir)
        print("Topic do configured analysis role chọn: %s" % state.topic)
        print("Manifest: %s" % manifest)
        print("Checkpoint: %s" % (output_dir / "run_state.json"))
        print("Thời gian chạy: %s" % format_duration(state.execution_elapsed_seconds))
        if state.total_elapsed_seconds is not None and state.total_elapsed_seconds != state.execution_elapsed_seconds:
            print("Tổng thời gian tính từ lần chạy đầu: %s" % format_duration(state.total_elapsed_seconds))
        print("MiniMax: speed=1.02 | pitch=-1 | volume=1.02")
        print("Log: %s" % log_path)
        print("Model log: %s" % model_log_path)
        finish_run(
            "SUCCESS",
            {
                "profile": "resource_pack",
                "status": state.status,
                "resource_manifest": str(manifest),
                "artifact_count": len(state.artifact_index),
                "execution_elapsed_seconds": state.execution_elapsed_seconds,
                "total_elapsed_seconds": state.total_elapsed_seconds,
            },
        )
        return 0
    except Exception as exc:
        if trace_started:
            finish_run("FAILED", {"error_type": type(exc).__name__, "error": str(exc), "execution_elapsed_seconds": getattr(locals().get("state"), "execution_elapsed_seconds", None), "total_elapsed_seconds": getattr(locals().get("state"), "total_elapsed_seconds", None)})
        logger.exception("Resource-pack CLI thất bại: %s", exc)
        print("Lỗi: %s" % exc, file=sys.stderr)
        return 1
