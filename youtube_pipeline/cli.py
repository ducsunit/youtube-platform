from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Optional, Sequence

from .config import Settings, channel_data_path_from_env
from .domain.models import FlowState, ValidationError
from .infrastructure.logging import configure_logging, configure_model_call_logging
from .infrastructure.model_trace import finish_run, start_run
from .pipeline import YouTubePipeline, write_outputs
from .providers import AIContentProvider, DemoContentProvider

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="youtube-pipeline",
        description="Tao kich ban YouTube bang pipeline Gemini + DeepSeek + Gemini.",
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--input", help="Du lieu tho ve kenh/video va xu huong.")
    source.add_argument("--input-file", type=Path, help="File UTF-8 chua du lieu tho.")
    source.add_argument("--resume", type=Path, help="Tiep tuc tu pipeline_state.json.")
    parser.add_argument(
        "--output-dir", type=Path, default=Path("output"), help="Thu muc ket qua."
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        help="Vi tri checkpoint (mac dinh: OUTPUT_DIR/pipeline_state.json).",
    )
    parser.add_argument(
        "--demo", action="store_true", help="Chay mau khong goi API va khong can key."
    )
    return parser


def _load_environment() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def _read_channel_json(path: Path) -> str:
    logger.info("Đang đọc dữ liệu kênh JSON | path=%s", path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValidationError(
            "Không đọc được file dữ liệu kênh %s: %s" % (path, exc)
        ) from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(
            "File dữ liệu kênh %s không phải JSON hợp lệ: %s" % (path, exc.msg)
        ) from exc
    if not isinstance(data, (dict, list)):
        raise ValidationError("Dữ liệu kênh JSON phải là object hoặc array.")
    if not data:
        raise ValidationError("File dữ liệu kênh JSON không được để trống.")
    serialized = json.dumps(data, ensure_ascii=False, indent=2)
    logger.info("Đã đọc dữ liệu kênh JSON | path=%s", path)
    logger.debug("Channel JSON input:\n%s", serialized)
    return serialized


def _read_state(args: argparse.Namespace, parser: argparse.ArgumentParser) -> FlowState:
    if args.resume:
        logger.info("Nguồn đầu vào: checkpoint | path=%s", args.resume)
        return YouTubePipeline.load_checkpoint(args.resume)
    if args.input_file:
        logger.info("Nguồn đầu vào: input file | path=%s", args.input_file)
        try:
            raw_data = args.input_file.read_text(encoding="utf-8")
        except OSError as exc:
            parser.error("Khong doc duoc input file: %s" % exc)
    elif args.input:
        logger.info("Nguồn đầu vào: command line --input")
        raw_data = args.input
    elif args.demo:
        logger.info("Nguồn đầu vào: dữ liệu demo")
        raw_data = (
            "Kenh ke chuyen lich su. Video tot nhat co retention 68%. "
            "Khán gia quan tam den co vat moi duoc khai quat."
        )
    else:
        channel_data_path = channel_data_path_from_env()
        if channel_data_path:
            logger.info("Nguồn đầu vào: YOUTUBE_CHANNEL_DATA_FILE")
            raw_data = _read_channel_json(channel_data_path)
        else:
            parser.error(
                "Cần --input, --input-file, --resume, --demo hoặc "
                "YOUTUBE_CHANNEL_DATA_FILE trong .env."
            )
    state = FlowState(raw_youtube_data=raw_data)
    logger.debug("Raw YouTube data:\n%s", state.raw_youtube_data)
    return state


def _production_provider() -> AIContentProvider:
    return AIContentProvider(Settings.from_env())


def main(argv: Optional[Sequence[str]] = None) -> int:
    _load_environment()
    effective_argv = list(argv) if argv is not None else sys.argv[1:]
    if effective_argv and effective_argv[0] == "resource-pack":
        from .resource_pack.cli import resource_main

        return resource_main(effective_argv[1:])
    if effective_argv and effective_argv[0] == "api-server":
        from .api import main as api_main

        return api_main(effective_argv[1:])
    parser = build_parser()
    args = parser.parse_args(effective_argv)
    trace_started = False
    try:
        log_path = configure_logging()
        model_call_log_path = configure_model_call_logging()
        logger.info("Khởi động YouTube pipeline CLI | log_file=%s", log_path)
        logger.info(
            "CLI options | input_file=%s | resume=%s | output_dir=%s | "
            "state_file=%s | demo=%s | inline_input=%s",
            args.input_file,
            args.resume,
            args.output_dir,
            args.state_file,
            args.demo,
            bool(args.input),
        )
        state = _read_state(args, parser)
        checkpoint = args.state_file or args.resume or (
            args.output_dir / "pipeline_state.json"
        )
        is_complete = all(
            step in state.completed_steps
            for step in ("analysis", "writing", "review", "consistency")
        )
        provider = (
            DemoContentProvider() if args.demo or is_complete else _production_provider()
        )
        max_retries = 1 if args.demo else 3
        consistency_min_score = 90
        consistency_max_rounds = 2
        duration_tolerance = 0.25
        if not args.demo and not is_complete:
            max_retries = provider.max_retries
            consistency_min_score = provider.consistency_min_score
            consistency_max_rounds = provider.consistency_max_rounds
            duration_tolerance = provider.duration_tolerance

        run_id = uuid.uuid4().hex
        start_run(
            run_id,
            {
                "mode": "demo" if args.demo else "production",
                "checkpoint": str(checkpoint),
                "completed_steps_at_start": state.completed_steps,
                "output_dir": str(args.output_dir),
            },
        )
        trace_started = True

        print("=== YOUTUBE AI SCRIPT PIPELINE ===")
        pipeline = YouTubePipeline(
            provider=provider,
            checkpoint_path=checkpoint,
            max_retries=max_retries,
            consistency_min_score=consistency_min_score,
            consistency_max_rounds=consistency_max_rounds,
            duration_tolerance=duration_tolerance,
            progress=print,
        )
        state = pipeline.run(state)
        script_path, result_path = write_outputs(state, args.output_dir)
        latest_gate = state.consistency_audits[-1]
        print("\nHoan tat: %s" % state.gemini_proposal.suggested_title)
        print("Bao cao: %s" % state.optimization_report)
        print(
            "Consistency: PASS | vòng %s | DeepSeek %s/100 | Gemini %s/100"
            % (
                latest_gate["round"],
                latest_gate["deepseek_audit"]["overall_score"],
                latest_gate["gemini_audit"]["overall_score"],
            )
        )
        print(
            "Thời lượng: %s"
            % latest_gate["deterministic_duration_check"]["status"]
        )
        print("Kich ban: %s" % script_path)
        print("Du lieu JSON: %s" % result_path)
        print("Checkpoint: %s" % checkpoint)
        print("Log: %s" % log_path)
        print("Model call log: %s" % model_call_log_path)
        finish_run(
            "SUCCESS",
            {
                "title": state.gemini_proposal.suggested_title,
                "completed_steps": state.completed_steps,
                "consistency_gate": latest_gate,
                "script_path": str(script_path),
                "result_path": str(result_path),
            },
        )
        logger.info("CLI hoàn tất thành công")
        return 0
    except Exception as exc:
        if trace_started:
            finish_run("FAILED", {"error_type": type(exc).__name__, "error": str(exc)})
        logger.exception("CLI kết thúc do lỗi: %s", exc)
        print("Loi: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
