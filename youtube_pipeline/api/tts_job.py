"""Internal Web worker: regenerate VOICEVOX audio cho một run có sẵn.

Được API route POST /runs/{id}/tts spawn dưới dạng subprocess. Ghi trạng thái
vào ``audio/tts-status.json`` để UI poll, kết quả chi tiết vào
``audio/tts-summary.json`` (giống stage tts_generate).
"""
from __future__ import annotations

import argparse
import json
import os
import time
import traceback
from pathlib import Path

from ..tts_voicevox import generate_run_audio, _write_status


def _status_path(output_dir: Path) -> Path:
    return output_dir / "audio" / "tts-status.json"


def _write_status(output_dir: Path, payload: dict) -> None:
    path = _status_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _progress_cb(output_dir: Path, started_at: str):
    """Trả về callback function để ghi progress vào status file."""
    def cb(chunk_idx: int, total_chunks: int, piece_idx: int, total_pieces: int) -> None:
        payload = {
            "status": "running",
            "started_at": started_at,
            "progress": {
                "chunk": chunk_idx + 1,
                "total_chunks": total_chunks,
                "piece": piece_idx + 1,
                "total_pieces": total_pieces,
            }
        }
        _write_status(output_dir, payload)
    return cb


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="youtube-tts-worker")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--skip-existing", action="store_true", default=True, help="Bỏ qua chunk đã có file MP3")
    parser.add_argument("--force", action="store_true", help="Gen lại tất cả (ignore skip-existing)")
    parser.add_argument("--inter-chunk-delay", type=float, default=5.0, help="Delay giữa các chunk (giây) để engine hồi phục")
    parser.add_argument("--inter-piece-delay", type=float, default=2.0, help="Delay giữa các piece trong chunk (giây)")
    args = parser.parse_args(argv)

    skip_existing = args.skip_existing and not args.force

    started = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    _write_status(args.output_dir, {"status": "running", "started_at": started, "skip_existing": skip_existing})
    try:
        state_path = args.output_dir / "run_state.json"
        overrides: dict = {}
        if state_path.is_file():
            snapshot = json.loads(state_path.read_text(encoding="utf-8")).get("config_snapshot") or {}
            overrides = (snapshot.get("channel_profile") or {}).get("tts") or {}

        profile = {
            "engine_url": os.getenv("VOICEVOX_URL", "http://127.0.0.1:50021"),
            "speaker": int(overrides.get("speaker", os.getenv("VOICEVOX_SPEAKER", "21"))),
            "speed_scale": float(overrides.get("speed_scale", os.getenv("VOICEVOX_SPEED", "1.0"))),
            "pitch_scale": float(overrides.get("pitch_scale", os.getenv("VOICEVOX_PITCH", "0.0"))),
            "intonation_scale": float(overrides.get("intonation_scale", os.getenv("VOICEVOX_INTONATION", "0.85"))),
            "pre_phoneme_length": 0.4,
            "post_phoneme_length": 0.6,
        }
        settings = {
            "speedScale": profile["speed_scale"],
            "pitchScale": profile["pitch_scale"],
            "intonationScale": profile["intonation_scale"],
            "prePhonemeLength": profile["pre_phoneme_length"],
            "postPhonemeLength": profile["post_phoneme_length"],
            "outputSamplingRate": 44100,
        }
        progress_cb = _progress_cb(args.output_dir, started)
        summary = generate_run_audio(
            args.output_dir,
            profile["speaker"],
            profile["engine_url"],
            settings,
            skip_existing=skip_existing,
            progress_cb=progress_cb,
            inter_chunk_delay_sec=args.inter_chunk_delay,
            inter_piece_delay_sec=args.inter_piece_delay,
        )
        summary.update({"provider": "VOICEVOX", "speaker": profile["speaker"]})
        (args.output_dir / "audio" / "tts-summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        _write_status(args.output_dir, {"status": "done", "started_at": started,
                                        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                                        "summary": summary})
        return 0
    except Exception as exc:  # noqa: BLE001 - worker biên: ghi lỗi vào status cho UI
        traceback.print_exc()
        _write_status(args.output_dir, {
            "status": "failed",
            "started_at": started,
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "error": str(exc),
        })
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
