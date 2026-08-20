"""Standards-compliant UTF-8 SRT output."""

from pathlib import Path
from typing import Sequence

from .aligner import TimedCaption


def format_timestamp(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def render_srt(captions: Sequence[TimedCaption]) -> str:
    blocks = []
    for index, caption in enumerate(captions, start=1):
        blocks.append(
            f"{index}\n{format_timestamp(caption.start)} --> {format_timestamp(caption.end)}\n"
            f"{caption.text}"
        )
    return "\n\n".join(blocks) + "\n"


def write_srt(captions: Sequence[TimedCaption], output_path: str) -> str:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_srt(captions), encoding="utf-8-sig")
    return str(path)

