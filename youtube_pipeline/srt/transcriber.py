"""Lazy faster-whisper integration."""

from dataclasses import dataclass
from functools import lru_cache
import logging
from pathlib import Path
import shutil
from typing import Any, List, Optional


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str


def validate_audio(path: str) -> None:
    if not path or not Path(path).is_file():
        raise ValueError("Không tìm thấy file audio.")
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("Chưa cài FFmpeg hoặc FFmpeg chưa có trong PATH.")


@lru_cache(maxsize=2)
def _load_model(model_size: str, device: str, compute_type: str) -> Any:
    """Load and retain recent models so consecutive jobs start faster."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "Thiếu faster-whisper. Hãy chạy: pip install -r requirements.txt"
        ) from exc
    logger.info(
        "Đang tải Whisper model | model=%s | device=%s | compute_type=%s",
        model_size,
        device,
        compute_type,
    )
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    logger.info("Đã tải Whisper model | model=%s", model_size)
    return model


def transcribe_audio(
    audio_path: str,
    model_size: str = "small",
    device: str = "auto",
    compute_type: Optional[str] = None,
) -> List[TranscriptSegment]:
    """Transcribe Japanese audio. The model is imported only when requested."""
    validate_audio(audio_path)
    if compute_type is None:
        compute_type = "int8" if device == "cpu" else "default"
    logger.info(
        "Bắt đầu nhận diện | audio=%s | model=%s | device=%s | compute_type=%s",
        audio_path,
        model_size,
        device,
        compute_type,
    )
    model = _load_model(model_size, device, compute_type)
    segments, _ = model.transcribe(
        audio_path,
        language="ja",
        beam_size=5,
        vad_filter=True,
        condition_on_previous_text=True,
    )
    result = [
        TranscriptSegment(float(segment.start), float(segment.end), segment.text.strip())
        for segment in segments
        if segment.text.strip() and segment.end > segment.start
    ]
    if not result:
        raise ValueError("Whisper không nhận diện được lời nói trong audio.")
    logger.info(
        "Nhận diện hoàn tất | segments=%d | duration=%.2fs",
        len(result),
        result[-1].end,
    )
    return result
