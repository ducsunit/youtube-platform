"""Chunked high-accuracy alignment of known Japanese text to audio."""

from dataclasses import dataclass
from functools import lru_cache
import logging
from typing import Any, List, Optional, Sequence, Tuple

from .aligner import TimedCaption, align_captions, alignment_score, normalize_for_alignment
from .transcriber import TranscriptSegment, validate_audio


logger = logging.getLogger(__name__)
SAMPLE_RATE = 16_000
TARGET_CHUNK_SECONDS = 40.0
CHUNK_PADDING_SECONDS = 2.0
MIN_SECONDS_PER_CHARACTER = 0.04
MAX_SECONDS_PER_CHARACTER = 0.8
MAX_ANCHOR_CENTER_DRIFT = 3.0
MIN_CAPTION_DURATION = 0.08


@dataclass(frozen=True)
class ForcedAlignmentResult:
    captions: List[TimedCaption]
    coverage: float


@dataclass(frozen=True)
class AlignmentChunk:
    first_caption: int
    last_caption: int
    audio_start: float
    audio_end: float


@lru_cache(maxsize=2)
def _load_alignment_model(model_size: str, device: str, compute_type: str) -> Any:
    try:
        import stable_whisper
    except ImportError as exc:
        raise RuntimeError(
            "Thiếu stable-ts. Hãy chạy: pip install -r requirements.txt"
        ) from exc

    logger.info(
        "Đang tải forced-alignment model | model=%s | device=%s | compute_type=%s",
        model_size,
        device,
        compute_type,
    )
    model = stable_whisper.load_faster_whisper(
        model_size,
        device=device,
        compute_type=compute_type,
    )
    logger.info("Đã tải forced-alignment model | model=%s", model_size)
    return model


def _transcribe_anchors(model: Any, audio_path: str) -> List[TranscriptSegment]:
    """Create reliable coarse anchors before doing local forced alignment."""
    logger.info("Đang tạo mốc neo Whisper cho forced alignment")
    raw_segments, _info = model.transcribe_original(
        audio_path,
        language="ja",
        beam_size=5,
        vad_filter=True,
        condition_on_previous_text=True,
    )
    anchors = [
        TranscriptSegment(float(item.start), float(item.end), item.text.strip())
        for item in raw_segments
        if item.text.strip() and item.end > item.start
    ]
    if not anchors:
        raise ValueError("Whisper không tạo được mốc neo từ audio.")
    logger.info("Đã tạo %d mốc neo Whisper", len(anchors))
    return anchors


def _make_chunks(
    approximate: Sequence[TimedCaption], audio_duration: float
) -> List[AlignmentChunk]:
    chunks: List[AlignmentChunk] = []
    first = 0
    for index, caption in enumerate(approximate):
        chunk_duration = caption.end - approximate[first].start
        is_last = index == len(approximate) - 1
        if chunk_duration < TARGET_CHUNK_SECONDS and not is_last:
            continue
        last = index + 1
        chunks.append(
            AlignmentChunk(
                first_caption=first,
                last_caption=last,
                audio_start=max(0.0, approximate[first].start - CHUNK_PADDING_SECONDS),
                audio_end=min(audio_duration, caption.end + CHUNK_PADDING_SECONDS),
            )
        )
        first = last
    if first < len(approximate):
        caption = approximate[-1]
        chunks.append(
            AlignmentChunk(
                first_caption=first,
                last_caption=len(approximate),
                audio_start=max(0.0, approximate[first].start - CHUNK_PADDING_SECONDS),
                audio_end=min(audio_duration, caption.end + CHUNK_PADDING_SECONDS),
            )
        )
    return chunks


def _align_chunk(
    model: Any,
    waveform: Any,
    captions: Sequence[str],
    fast_mode: bool,
) -> Tuple[List[Optional[TimedCaption]], float]:
    result = model.align(
        waveform,
        "\n".join(captions),
        language="ja",
        original_split=True,
        ignore_compatibility=True,
        remove_instant_words=False,
        token_step=200,
        word_dur_factor=2.0,
        max_word_dur=2.5,
        nonspeech_skip=3.0,
        fast_mode=fast_mode,
        failure_threshold=None,
        verbose=None,
        suppress_silence=True,
        min_silence_dur=0.1,
        only_voice_freq=True,
    )
    if result is None or len(result.segments) != len(captions):
        actual = 0 if result is None else len(result.segments)
        raise ValueError(f"Số đoạn alignment không khớp ({actual}/{len(captions)})")

    timed: List[Optional[TimedCaption]] = []
    word_count = 0
    valid_word_count = 0
    for caption, segment in zip(captions, result.segments):
        if normalize_for_alignment(segment.text) != normalize_for_alignment(caption):
            logger.warning("Forced alignment làm thay đổi nội dung: %s", caption)
            timed.append(None)
            continue
        start = float(segment.start)
        end = float(segment.end)
        character_count = max(1, len(normalize_for_alignment(caption)))
        seconds_per_character = (end - start) / character_count
        if (
            end <= start
            or seconds_per_character < MIN_SECONDS_PER_CHARACTER
            or seconds_per_character > MAX_SECONDS_PER_CHARACTER
        ):
            logger.warning(
                "Timestamp caption bất thường | seconds_per_char=%.3f | text=%s",
                seconds_per_character,
                caption,
            )
            timed.append(None)
        else:
            timed.append(TimedCaption(start, end, caption))
        for word in segment.words or []:
            word_count += 1
            if float(word.end) - float(word.start) >= 0.02:
                valid_word_count += 1

    word_coverage = 100.0 if not word_count else valid_word_count / word_count * 100
    return timed, word_coverage


def _offset_captions(
    captions: Sequence[Optional[TimedCaption]], offset: float
) -> List[Optional[TimedCaption]]:
    return [
        TimedCaption(item.start + offset, item.end + offset, item.text)
        if item is not None
        else None
        for item in captions
    ]


def _align_local_caption(
    model: Any,
    waveform: Any,
    all_captions: Sequence[str],
    approximate: Sequence[TimedCaption],
    caption_index: int,
) -> Optional[TimedCaption]:
    """Retry one failed caption with its neighbors in a small audio window."""
    first = max(0, caption_index - 1)
    last = min(len(all_captions), caption_index + 2)
    audio_start = max(0.0, approximate[first].start - CHUNK_PADDING_SECONDS)
    audio_end = min(
        len(waveform) / SAMPLE_RATE,
        approximate[last - 1].end + CHUNK_PADDING_SECONDS,
    )
    sample_start = round(audio_start * SAMPLE_RATE)
    sample_end = round(audio_end * SAMPLE_RATE)
    local_audio = waveform[sample_start:sample_end]
    target_local_index = caption_index - first

    for fast_mode in (False, True):
        try:
            local, _coverage = _align_chunk(
                model,
                local_audio,
                all_captions[first:last],
                fast_mode,
            )
            target = local[target_local_index]
            if target is not None:
                logger.info(
                    "Local retry caption thành công | caption=%d | context=%d-%d",
                    caption_index + 1,
                    first + 1,
                    last,
                )
                return TimedCaption(
                    target.start + audio_start,
                    target.end + audio_start,
                    target.text,
                )
        except Exception as exc:
            logger.warning(
                "Local retry caption %d thất bại | retry_fast=%s | error=%s",
                caption_index + 1,
                fast_mode,
                exc,
            )
    return None


def _align_local_range(
    model: Any,
    waveform: Any,
    all_captions: Sequence[str],
    approximate: Sequence[TimedCaption],
    first_failed: int,
    last_failed: int,
) -> Optional[List[TimedCaption]]:
    """Re-align a contiguous failed range in one shared local time system."""
    context_first = max(0, first_failed - 1)
    context_last = min(len(all_captions), last_failed + 2)
    audio_start = max(
        0.0, approximate[context_first].start - CHUNK_PADDING_SECONDS
    )
    audio_end = min(
        len(waveform) / SAMPLE_RATE,
        approximate[context_last - 1].end + CHUNK_PADDING_SECONDS,
    )
    local_audio = waveform[
        round(audio_start * SAMPLE_RATE) : round(audio_end * SAMPLE_RATE)
    ]
    slice_start = first_failed - context_first
    slice_end = last_failed - context_first + 1
    for fast_mode in (False, True):
        try:
            local, _coverage = _align_chunk(
                model,
                local_audio,
                all_captions[context_first:context_last],
                fast_mode,
            )
            targets = local[slice_start:slice_end]
            if all(item is not None for item in targets):
                logger.info(
                    "Local retry cụm thành công | captions=%d-%d | context=%d-%d",
                    first_failed + 1,
                    last_failed + 1,
                    context_first + 1,
                    context_last,
                )
                return [
                    TimedCaption(
                        item.start + audio_start,
                        item.end + audio_start,
                        item.text,
                    )
                    for item in targets
                    if item is not None
                ]
        except Exception as exc:
            logger.warning(
                "Local retry cụm %d-%d thất bại | retry_fast=%s | error=%s",
                first_failed + 1,
                last_failed + 1,
                fast_mode,
                exc,
            )
    return None


def _remove_boundary_overlaps(captions: Sequence[TimedCaption]) -> List[TimedCaption]:
    result = list(captions)
    for index in range(1, len(result)):
        previous = result[index - 1]
        current = result[index]
        if current.start >= previous.end:
            continue
        boundary = (previous.end + current.start) / 2
        result[index - 1] = TimedCaption(previous.start, boundary, previous.text)
        result[index] = TimedCaption(boundary, current.end, current.text)
    return result


def _stitch_with_anchors(
    captions: Sequence[TimedCaption],
    approximate: Sequence[TimedCaption],
    forced_flags: Sequence[bool],
) -> Tuple[List[TimedCaption], List[bool]]:
    """Reject implausible local results and guarantee positive monotonic SRT times."""
    result = list(captions)
    flags = list(forced_flags)
    for index, (item, anchor) in enumerate(zip(result, approximate)):
        item_center = (item.start + item.end) / 2
        anchor_center = (anchor.start + anchor.end) / 2
        if (
            item.end - item.start < MIN_CAPTION_DURATION
            or abs(item_center - anchor_center) > MAX_ANCHOR_CENTER_DRIFT
        ):
            logger.warning(
                "Loại timestamp lệch mốc neo | caption=%d | forced=%.3f-%.3f | "
                "anchor=%.3f-%.3f | text=%s",
                index + 1,
                item.start,
                item.end,
                anchor.start,
                anchor.end,
                item.text,
            )
            result[index] = anchor
            flags[index] = False

    for index in range(1, len(result)):
        previous = result[index - 1]
        current = result[index]
        if current.start >= previous.end:
            continue
        boundary = (previous.end + current.start) / 2
        if (
            boundary - previous.start >= MIN_CAPTION_DURATION
            and current.end - boundary >= MIN_CAPTION_DURATION
        ):
            result[index - 1] = TimedCaption(previous.start, boundary, previous.text)
            result[index] = TimedCaption(boundary, current.end, current.text)
            continue

        logger.warning(
            "Overlap không thể ghép an toàn; dùng mốc neo | captions=%d-%d",
            index,
            index + 1,
        )
        result[index - 1] = approximate[index - 1]
        result[index] = approximate[index]
        flags[index - 1] = False
        flags[index] = False

    # Anchors are monotonic; this final guard makes invalid SRT impossible.
    for index, item in enumerate(result):
        if item.end - item.start < MIN_CAPTION_DURATION:
            result[index] = approximate[index]
            flags[index] = False
        if index and result[index].start < result[index - 1].end:
            result[index - 1] = approximate[index - 1]
            result[index] = approximate[index]
            flags[index - 1] = False
            flags[index] = False
    return result, flags


def force_align_captions(
    audio_path: str,
    captions: Sequence[str],
    model_size: str = "large-v3",
    device: str = "cpu",
) -> ForcedAlignmentResult:
    """Align captions in anchored chunks and fall back locally on failures."""
    validate_audio(audio_path)
    if not captions:
        raise ValueError("Không có caption để căn chỉnh.")

    compute_type = "int8" if device in {"cpu", "auto"} else "float16"
    anchor_model_size = "small" if model_size in {"medium", "large-v3"} else model_size
    anchor_model = _load_alignment_model(anchor_model_size, device, compute_type)
    anchors = _transcribe_anchors(anchor_model, audio_path)
    approximate = align_captions(captions, anchors)
    anchor_similarity = alignment_score(captions, anchors)
    model = _load_alignment_model(model_size, device, compute_type)

    try:
        from faster_whisper.audio import decode_audio
    except ImportError as exc:
        raise RuntimeError("Thiếu faster-whisper để đọc audio.") from exc
    waveform = decode_audio(audio_path, sampling_rate=SAMPLE_RATE)
    audio_duration = len(waveform) / SAMPLE_RATE
    chunks = _make_chunks(approximate, audio_duration)
    logger.info(
        "Bắt đầu forced alignment theo khối | captions=%d | chunks=%d | "
        "anchor_model=%s | alignment_model=%s | anchor_similarity=%.1f%%",
        len(captions),
        len(chunks),
        anchor_model_size,
        model_size,
        anchor_similarity,
    )

    aligned: List[TimedCaption] = []
    forced_flags: List[bool] = []
    word_coverages: List[float] = []
    for chunk_index, chunk in enumerate(chunks, start=1):
        chunk_captions = captions[chunk.first_caption : chunk.last_caption]
        sample_start = round(chunk.audio_start * SAMPLE_RATE)
        sample_end = round(chunk.audio_end * SAMPLE_RATE)
        audio_clip = waveform[sample_start:sample_end]
        chunk_result: List[Optional[TimedCaption]] = [None] * len(chunk_captions)
        for fast_mode in (False, True):
            if all(item is not None for item in chunk_result):
                break
            try:
                local, word_coverage = _align_chunk(
                    model, audio_clip, chunk_captions, fast_mode
                )
                candidate = _offset_captions(local, chunk.audio_start)
                for local_index, item in enumerate(candidate):
                    if chunk_result[local_index] is None and item is not None:
                        chunk_result[local_index] = item
                word_coverages.append(word_coverage)
                failed_count = sum(item is None for item in chunk_result)
                if failed_count:
                    logger.warning(
                        "Forced alignment khối %d/%d còn %d caption lỗi | retry_fast=%s",
                        chunk_index,
                        len(chunks),
                        failed_count,
                        fast_mode,
                    )
            except Exception as exc:
                logger.warning(
                    "Forced alignment khối %d/%d thất bại | retry_fast=%s | error=%s",
                    chunk_index,
                    len(chunks),
                    fast_mode,
                    exc,
                )

        resolved_chunk: List[TimedCaption] = []
        resolved_flags: List[bool] = []
        for local_index, item in enumerate(chunk_result):
            global_index = chunk.first_caption + local_index
            if item is None:
                item = _align_local_caption(
                    model,
                    waveform,
                    captions,
                    approximate,
                    global_index,
                )
            if item is None:
                item = approximate[global_index]
                logger.warning(
                    "Dùng timestamp mốc neo cho caption %d | start=%.3f | end=%.3f | "
                    "text=%s",
                    global_index + 1,
                    item.start,
                    item.end,
                    item.text,
                )
                resolved_flags.append(False)
            else:
                resolved_flags.append(True)
            resolved_chunk.append(item)
        aligned.extend(resolved_chunk)
        forced_flags.extend(resolved_flags)

    aligned, forced_flags = _stitch_with_anchors(aligned, approximate, forced_flags)
    failed_ranges: List[Tuple[int, int]] = []
    range_start: Optional[int] = None
    for index, is_forced in enumerate(forced_flags + [True]):
        if not is_forced and range_start is None:
            range_start = index
        elif is_forced and range_start is not None:
            failed_ranges.append((range_start, index - 1))
            range_start = None

    for first_failed, last_failed in failed_ranges:
        repaired = _align_local_range(
            model,
            waveform,
            captions,
            approximate,
            first_failed,
            last_failed,
        )
        if repaired is None:
            continue
        aligned[first_failed : last_failed + 1] = repaired
        forced_flags[first_failed : last_failed + 1] = [True] * len(repaired)

    aligned, forced_flags = _stitch_with_anchors(aligned, approximate, forced_flags)
    forced_caption_count = sum(forced_flags)
    forced_coverage = forced_caption_count / len(captions) * 100
    mean_word_coverage = (
        sum(word_coverages) / len(word_coverages) if word_coverages else 0.0
    )
    logger.info(
        "Forced alignment hoàn tất | captions=%d | forced_coverage=%.1f%% | "
        "word_coverage=%.1f%% | duration=%.2fs",
        len(aligned),
        forced_coverage,
        mean_word_coverage,
        aligned[-1].end,
    )
    return ForcedAlignmentResult(aligned, forced_coverage)
