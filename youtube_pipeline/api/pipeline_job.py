"""Internal Web worker for one resource-pack run.

This module deliberately bypasses the public CLI parser. The API owns input
selection; the worker only receives a resolved snapshot or a resume state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from pathlib import Path

from ..config import Settings
from ..core.timing import format_duration
from ..infrastructure.logging import configure_logging, configure_model_call_logging
from ..infrastructure.model_trace import finish_run, start_run
from ..resource_pack.pipeline import ResourcePackPipeline
from ..resource_pack.providers import AIResourceProvider, DemoResourceProvider

logger = logging.getLogger(__name__)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="youtube-pipeline-web-worker")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input-file", type=Path)
    source.add_argument("--resume", type=Path)
    source.add_argument("--demo", action="store_true")
    source.add_argument("--manual-topic")
    source.add_argument("--no-channel-data", action="store_true")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--channel", help="Channel profile trong config/channels/<id>/profile.json")
    return parser


def _read_snapshot(path: Path) -> tuple[str, dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError("Không đọc được dataset: %s" % exc) from exc
    except json.JSONDecodeError as exc:
        raise ValueError("Dataset không phải JSON hợp lệ: %s" % exc.msg) from exc
    if not isinstance(data, dict) or not data:
        raise ValueError("Dataset phải là JSON object không rỗng.")
    return json.dumps(data, ensure_ascii=False, indent=2), data


def _run_new(args: argparse.Namespace) -> tuple[ResourcePackPipeline, object, str]:
    if args.demo:
        raw_data = json.dumps({"schema_version": 2, "generated_at": "demo", "videos": {}}, ensure_ascii=False)
        provider = DemoResourceProvider()
        provenance = {"mode": "demo"}
    elif args.manual_topic or args.no_channel_data:
        candidate_topic = str(args.manual_topic or "").strip()
        manual_topic = "" if candidate_topic.casefold() in {"", "none", "null", "undefined", "n/a"} else candidate_topic
        raw_data = json.dumps(
            {"schema_version": 2, "generated_at": None, "videos": {}},
            ensure_ascii=False,
        )
        provider = AIResourceProvider(Settings.from_env(require_keys=False))
        provenance = (
            {"mode": "manual_topic_no_channel_data", "manual_topic": manual_topic, "channel_data_used": False}
            if manual_topic
            else {"mode": "competitor_topic_no_channel_data", "channel_data_used": False}
        )
    else:
        raw_data, source = _read_snapshot(args.input_file)
        provider = AIResourceProvider(Settings.from_env(require_keys=False))
        provenance = {
            "mode": "selected_snapshot",
            "source_file": str(args.input_file.resolve()),
            "source_sha256": hashlib.sha256(raw_data.encode("utf-8")).hexdigest(),
            "generated_at": source.get("generated_at"),
            "analytics_window": source.get("analytics_window"),
        }
    pipeline = ResourcePackPipeline(
        provider, args.output_dir, max_retries=1 if args.demo else provider.max_retries,
        retry_delay=0 if args.demo else 1, progress=print,
        channel_id=args.channel,
    )
    state = pipeline.create_state(raw_data, run_id=args.run_id)
    state.config_snapshot["input_provenance"] = provenance
    if args.manual_topic:
        state.config_snapshot["manual_topic"] = str(args.manual_topic).strip()
    pipeline.store.save_state(state)
    return pipeline, state, "demo" if args.demo else "production"


def _run_resume(args: argparse.Namespace) -> tuple[ResourcePackPipeline, object, str]:
    if args.resume.name != "run_state.json" or args.resume.parent.resolve() != args.output_dir.resolve():
        raise ValueError("resume phải dùng run_state.json trong đúng output_dir.")
    bootstrap = ResourcePackPipeline(DemoResourceProvider(), args.output_dir, max_retries=1)
    state = bootstrap.load_state()
    # A completed run can still have stale stages after a production policy or
    # prompt version changes. It must use the model routing frozen in its
    # snapshot, not DemoResourceProvider, otherwise resume silently replaces
    # real assets with demo output.
    provider = AIResourceProvider(
        Settings.from_env(require_keys=False), routing_snapshot=state.config_snapshot.get("model_routing")
    )
    pipeline = ResourcePackPipeline(
        provider, args.output_dir, max_retries=provider.max_retries,
        retry_delay=1, progress=print,
        channel_id=getattr(args, "channel", None) or (state.config_snapshot.get("channel_profile") or {}).get("channel_id"),
    )
    return pipeline, state, "resume"


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    traced = False
    state = None
    try:
        log_path = configure_logging()
        model_log_path = configure_model_call_logging()
        pipeline, state, mode = _run_resume(args) if args.resume else _run_new(args)
        start_run(state.run_id, {"profile": "resource_pack", "mode": mode, "output_dir": str(args.output_dir)})
        traced = True
        print("=== YOUTUBE JP RESOURCE PACK — WEB RUN ===")
        state = pipeline.run(state)
        print("Hoàn tất resource pack: %s" % args.output_dir)
        print("Thời gian chạy: %s" % format_duration(state.execution_elapsed_seconds))
        print("Log: %s" % log_path)
        print("Model log: %s" % model_log_path)
        finish_run("SUCCESS", {"status": state.status, "execution_elapsed_seconds": state.execution_elapsed_seconds})
        return 0
    except Exception as exc:
        if traced:
            finish_run("FAILED", {"error_type": type(exc).__name__, "error": str(exc)})
        logger.exception("Web pipeline worker thất bại: %s", exc)
        print("Lỗi: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
