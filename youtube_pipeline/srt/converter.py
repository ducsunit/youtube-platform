"""Application-level conversion pipeline shared by web and desktop UIs."""

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Callable, Optional

from .aligner import align_captions, alignment_score
from .forced_aligner import force_align_captions
from .script_parser import make_captions, read_script
from .srt_writer import write_srt
from .subtitle_formatter import format_captions
from .transcriber import transcribe_audio


ProgressCallback = Callable[[str], None]
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConversionResult:
    output_path: str
    caption_count: int
    similarity: float
    alignment_mode: str = "fast"

    @property
    def needs_review(self) -> bool:
        threshold = 95 if self.alignment_mode == "accurate" else 45
        return self.similarity < threshold

    @property
    def metric_label(self) -> str:
        return "độ phủ alignment" if self.alignment_mode == "accurate" else "độ tương đồng"


def convert_to_srt(
    script_path: str,
    audio_path: str,
    output_path: str,
    max_chars: int = 24,
    model_size: str = "small",
    device: str = "auto",
    alignment_mode: str = "fast",
    progress: Optional[ProgressCallback] = None,
) -> ConversionResult:
    """Run the complete conversion and return useful UI diagnostics."""
    def notify(message: str) -> None:
        logger.info(message)
        if progress:
            progress(message)

    if not script_path or not Path(script_path).is_file():
        raise ValueError("Không tìm thấy file script.")
    if not audio_path or not Path(audio_path).is_file():
        raise ValueError("Không tìm thấy file audio.")

    logger.info(
        "Bắt đầu chuyển đổi | script=%s | audio=%s | model=%s | device=%s | "
        "max_chars=%s | mode=%s",
        script_path,
        audio_path,
        model_size,
        device,
        max_chars,
        alignment_mode,
    )
    notify("Đang đọc và chia kịch bản…")
    script = read_script(script_path)
    captions = make_captions(script, int(max_chars))
    if not captions:
        raise ValueError("Script không có nội dung tiếng Nhật.")

    if alignment_mode == "accurate":
        notify(f"Đang forced-align script bằng Whisper {model_size}…")
        forced = force_align_captions(audio_path, captions, model_size, device)
        timed = forced.captions
        score = forced.coverage
    elif alignment_mode == "fast":
        notify(f"Đang nhận diện audio bằng Whisper {model_size}…")
        segments = transcribe_audio(audio_path, model_size=model_size, device=device)
        notify("Đang căn chỉnh timestamp với kịch bản gốc…")
        timed = align_captions(captions, segments)
        score = alignment_score(captions, segments)
    else:
        raise ValueError(f"Chế độ căn chỉnh không hợp lệ: {alignment_mode}")

    formatted = format_captions(timed, int(max_chars), max_lines=2)

    notify("Đang ghi file SRT…")
    saved_path = write_srt(formatted, output_path)
    result = ConversionResult(saved_path, len(formatted), score, alignment_mode)
    logger.info(
        "Hoàn tất chuyển đổi | output=%s | captions=%d | similarity=%.1f%%",
        saved_path,
        result.caption_count,
        result.similarity,
    )
    if result.needs_review:
        logger.warning("%s thấp; nên kiểm tra lại script và audio", result.metric_label)
    return result
