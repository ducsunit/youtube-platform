"""Monotonic text alignment from the original script to Whisper timestamps."""

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import List, Sequence, Tuple

from .transcriber import TranscriptSegment


@dataclass(frozen=True)
class TimedCaption:
    start: float
    end: float
    text: str


def normalize_for_alignment(text: str) -> str:
    """Keep letters/numbers/Kana/Kanji, ignoring punctuation and spacing."""
    return "".join(char.lower() for char in text if char.isalnum())


def _build_audio_timeline(
    segments: Sequence[TranscriptSegment],
) -> Tuple[str, List[float], List[float]]:
    recognized = ""
    starts: List[float] = []
    ends: List[float] = []
    for segment in segments:
        normalized = normalize_for_alignment(segment.text)
        if not normalized:
            continue
        duration = max(0.01, segment.end - segment.start)
        count = len(normalized)
        for index in range(count):
            starts.append(segment.start + duration * index / count)
            ends.append(segment.start + duration * (index + 1) / count)
        recognized += normalized
    return recognized, starts, ends


def _boundary_map(source: str, target: str) -> List[float]:
    """Map every source boundary to a monotonic target character position."""
    if not source or not target:
        return [0.0] * (len(source) + 1)

    matcher = SequenceMatcher(None, source, target, autojunk=False)
    anchors = [(0, 0)]
    for block in matcher.get_matching_blocks():
        anchors.append((block.a, block.b))
        anchors.append((block.a + block.size, block.b + block.size))
    anchors.append((len(source), len(target)))

    # One target position per source position; duplicate anchors keep the furthest
    # monotonic target position.
    merged = {}
    for source_pos, target_pos in anchors:
        merged[source_pos] = max(target_pos, merged.get(source_pos, 0))
    ordered = sorted(merged.items())
    mapped = [0.0] * (len(source) + 1)
    for pair_index in range(len(ordered) - 1):
        s0, t0 = ordered[pair_index]
        s1, t1 = ordered[pair_index + 1]
        if s1 == s0:
            continue
        for source_pos in range(s0, s1 + 1):
            ratio = (source_pos - s0) / (s1 - s0)
            mapped[source_pos] = t0 + (t1 - t0) * ratio
    mapped[-1] = float(len(target))
    for index in range(1, len(mapped)):
        mapped[index] = max(mapped[index], mapped[index - 1])
    return mapped


def _position_to_time(position: float, starts: Sequence[float], ends: Sequence[float]) -> float:
    if not starts:
        return 0.0
    if position <= 0:
        return starts[0]
    if position >= len(starts):
        return ends[-1]
    lower = int(position)
    fraction = position - lower
    if lower >= len(starts):
        return ends[-1]
    char_start = starts[lower]
    char_end = ends[lower]
    return char_start + (char_end - char_start) * fraction


def align_captions(
    captions: Sequence[str], segments: Sequence[TranscriptSegment]
) -> List[TimedCaption]:
    """Assign Whisper-derived timestamps while retaining exact script captions."""
    if not captions:
        raise ValueError("Script không có nội dung.")
    if not segments:
        raise ValueError("Không có dữ liệu timestamp từ Whisper.")

    normalized_captions = [normalize_for_alignment(caption) for caption in captions]
    script_text = "".join(normalized_captions)
    recognized, char_starts, char_ends = _build_audio_timeline(segments)
    if not script_text or not recognized:
        raise ValueError("Không đủ nội dung để căn chỉnh script và audio.")

    positions = _boundary_map(script_text, recognized)
    results: List[TimedCaption] = []
    source_cursor = 0
    previous_end = segments[0].start
    for index, (caption, normalized) in enumerate(zip(captions, normalized_captions)):
        next_cursor = source_cursor + len(normalized)
        start = _position_to_time(positions[source_cursor], char_starts, char_ends)
        end = _position_to_time(positions[next_cursor], char_starts, char_ends)
        start = max(start, previous_end)
        if index == len(captions) - 1:
            end = max(end, segments[-1].end)
        end = max(start + 0.08, end)
        results.append(TimedCaption(start=start, end=end, text=caption))
        previous_end = end
        source_cursor = next_cursor
    return results


def alignment_score(captions: Sequence[str], segments: Sequence[TranscriptSegment]) -> float:
    """Return a 0..100 similarity score for diagnostics."""
    script = normalize_for_alignment("".join(captions))
    heard = normalize_for_alignment("".join(segment.text for segment in segments))
    if not script or not heard:
        return 0.0
    try:
        from rapidfuzz.fuzz import ratio

        return float(ratio(script, heard))
    except ImportError:
        return SequenceMatcher(None, script, heard, autojunk=False).ratio() * 100
