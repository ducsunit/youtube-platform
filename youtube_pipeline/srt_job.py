"""Run the integrated Japanese script-to-SRT converter as a background job."""
from __future__ import annotations

import argparse
from pathlib import Path

from .srt.converter import convert_to_srt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("script", type=Path)
    parser.add_argument("audio", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("model")
    parser.add_argument("device")
    parser.add_argument("mode", choices=("fast", "accurate"))
    parser.add_argument("max_chars", type=int)
    args = parser.parse_args()

    def progress(message: str) -> None:
        print(message, flush=True)

    result = convert_to_srt(
        str(args.script), str(args.audio), str(args.output), args.max_chars,
        args.model, args.device, args.mode, progress,
    )
    print("SRT_DONE %s captions=%d similarity=%.1f mode=%s" % (result.output_path, result.caption_count, result.similarity, result.alignment_mode), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
