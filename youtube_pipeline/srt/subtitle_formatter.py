"""Subtitle display formatting."""

from typing import List

from .aligner import TimedCaption


def wrap_japanese(text: str, max_chars: int, max_lines: int = 2) -> str:
    """Wrap a caption into at most two balanced lines."""
    compact = "".join(text.split())
    if len(compact) <= max_chars or max_lines <= 1:
        return compact
    # Caption creation already caps total length. The display line target is half.
    midpoint = len(compact) // 2
    candidates = [
        index + 1
        for index, char in enumerate(compact[:-1])
        if char in "、，,：:；;」』）)]】"
    ]
    split_at = min(candidates, key=lambda value: abs(value - midpoint)) if candidates else midpoint
    return compact[:split_at] + "\n" + compact[split_at:]


def format_captions(
    captions: List[TimedCaption], max_chars: int, max_lines: int = 2
) -> List[TimedCaption]:
    return [
        TimedCaption(item.start, item.end, wrap_japanese(item.text, max_chars, max_lines))
        for item in captions
    ]

