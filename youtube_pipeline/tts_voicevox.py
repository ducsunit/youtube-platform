"""VOICEVOX TTS provider — local, free, unlimited-length synthesis.

Replaces the MiniMax manual-TTS flow: the worker synthesizes every chunk in
``script/audio-chunks/`` through a local VOICEVOX engine (default
http://127.0.0.1:50021), converts to MP3 via ffmpeg, and concatenates all
chunks into ``audio/narration-merged.mp3``.

Engine must be running (VOICEVOX.app or voicevox_engine CLI). Every function
is network-failure safe: callers decide whether offline means skip or error.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

DEFAULT_ENGINE_URL = "http://127.0.0.1:50021"

# Engine treo/500 khi audio_query nhận text quá dài (~4800 ký tự). Cắt theo câu
# thành các mảnh nhỏ trước khi synth — an toàn và nhanh hơn hẳn.
MAX_PIECE_LEN = 600


def _write_status(output_dir: Path, payload: dict) -> None:
    """Ghi progress vào tts-status.json để UI poll được progress realtime."""
    status_path = output_dir / "audio" / "tts-status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def split_for_synthesis(text: str, max_len: int = MAX_PIECE_LEN) -> list[str]:
    """Cắt text theo ranh giới câu thành các đoạn <= max_len."""
    sentences = [s for s in re.split(r"(?<=[。！？\n])", text) if s.strip()]
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) > max_len:
            pieces.append(current)
            current = sentence
        else:
            current += sentence
        while len(current) > max_len * 2:  # câu đơn lẻ bất thường dài hơn 2x limit
            pieces.append(current[:max_len])
            current = current[max_len:]
    if current.strip():
        pieces.append(current)
    return pieces


def engine_available(base_url: str = DEFAULT_ENGINE_URL, timeout: float = 2.0) -> bool:
    try:
        req = urllib.request.Request(base_url.rstrip("/") + "/version")
        urllib.request.urlopen(req, timeout=timeout)
        return True
    except Exception:
        return False


def audio_query_url(base_url: str, speaker: int, text: str) -> tuple[str, bytes]:
    """Build the audio_query request: POST, text nằm ở QUERY STRING (API spec)."""
    params = urllib.parse.urlencode({"speaker": speaker, "text": text})
    return base_url.rstrip("/") + "/audio_query?" + params, b""


def synthesize_wav(
    text: str,
    speaker: int,
    base_url: str = DEFAULT_ENGINE_URL,
    settings: dict[str, Any] | None = None,
    timeout: float = 300.0,
    retries: int = 2,
) -> bytes:
    """Synthesize một mảnh text (<= MAX_PIECE_LEN) -> WAV bytes. Retry 1 lần."""
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            url, body = audio_query_url(base_url, speaker, text)
            req = urllib.request.Request(
                url, data=body, 
                headers={"Content-Type": "application/json", "Connection": "close"}, 
                method="POST"
            )
            query = json.loads(urllib.request.urlopen(req, timeout=timeout).read())

            settings = settings or {}
            for key in (
                "speedScale", "pitchScale", "intonationScale", "volumeScale",
                "prePhonemeLength", "postPhonemeLength", "outputSamplingRate",
            ):
                camel = key
                snake = "".join("_" + c.lower() if c.isupper() else c for c in key)
                if camel in settings:
                    query[camel] = settings[camel]
                elif snake.lstrip("_") in settings:
                    query[camel] = settings[snake.lstrip("_")]

            s_req = urllib.request.Request(
                base_url.rstrip("/") + f"/synthesis?{urllib.parse.urlencode({'speaker': speaker})}",
                data=json.dumps(query).encode(),
                headers={"Content-Type": "application/json", "Accept": "audio/wav", "Connection": "close"},
            )
            return urllib.request.urlopen(s_req, timeout=timeout).read()
        except Exception as exc:  # noqa: BLE001 - retry rồi để stage xử lý
            last_exc = exc
            if attempt < retries:
                logger.warning("VOICEVOX synth lỗi (lần %d/%d): %s — thử lại...", attempt + 1, retries + 1, exc)
                time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"VOICEVOX synth thất bại sau {retries + 1} lần: {last_exc}") from last_exc


def _run_ffmpeg(args: list[str]) -> None:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg thất bại: {' '.join(cmd)}\n{proc.stderr[-400:]}")


def wav_to_mp3(wav_path: Path, mp3_path: Path) -> bool:
    """Convert WAV -> MP3 (128k mono). Trả False nếu máy không có ffmpeg."""
    try:
        _run_ffmpeg(["-i", str(wav_path), "-codec:a", "libmp3lame", "-b:a", "128k", str(mp3_path)])
        return True
    except FileNotFoundError:
        return False


def make_silence_mp3(out_path: Path, seconds: float) -> bool:
    try:
        _run_ffmpeg([
            "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=mono",
            "-t", f"{seconds}", "-codec:a", "libmp3lame", "-b:a", "128k", str(out_path),
        ])
        return True
    except FileNotFoundError:
        return False


def concat_audio(inputs: list[Path], out_path: Path) -> None:
    """Nối nhiều file audio bằng filter_complex concat (re-encode sạch).

    Encoder chọn theo đuôi output: .wav -> PCM, còn lại -> libmp3lame.
    """
    args: list[str] = []
    filters: list[str] = []
    for index, path in enumerate(inputs):
        args += ["-i", str(path)]
        filters.append(f"[{index}:a]")
    n = len(inputs)
    if out_path.suffix.lower() == ".wav":
        encode = ["-codec:a", "pcm_s16le"]
    else:
        encode = ["-codec:a", "libmp3lame", "-b:a", "128k"]
    args += [
        "-filter_complex", "".join(filters) + f"concat=n={n}:v=0:a=1[out]",
        "-map", "[out]", *encode, str(out_path),
    ]
    _run_ffmpeg(args)


def generate_run_audio(
    run_dir: Path,
    speaker: int,
    base_url: str = DEFAULT_ENGINE_URL,
    settings: dict[str, Any] | None = None,
    inter_chunk_gap_sec: float = 0.8,
    inter_chunk_delay_sec: float = 5.0,
    inter_piece_delay_sec: float = 2.0,
    skip_existing: bool = True,
    progress_cb: Optional[Callable[[int, int, int, int], None]] = None,
) -> dict[str, Any]:
    """Gen toàn bộ audio cho 1 run từ script/audio-chunks/manifest.json.

    Mỗi chunk được cắt theo câu (split_for_synthesis) rồi synth từng mảnh —
    tránh treo engine khi text quá dài. Trả về summary dict.
    Raise RuntimeError nếu engine lỗi giữa chừng (stage retry xử lý).

    Args:
        skip_existing: Nếu True, bỏ qua chunk đã có file MP3 sẵn.
        progress_cb: Callback(chunk_idx, total_chunks, piece_idx, total_pieces) để report progress.
        inter_chunk_delay_sec: Delay giữa các chunk để VOICEVOX engine hồi phục (mặc định 5s).
        inter_piece_delay_sec: Delay giữa các piece trong chunk (mặc định 2s).
    """
    import shutil

    run_dir = Path(run_dir)
    manifest = json.loads((run_dir / "script/audio-chunks/manifest.json").read_text(encoding="utf-8"))
    audio_dir = run_dir / "audio" / "chunks"
    audio_dir.mkdir(parents=True, exist_ok=True)
    piece_dir = audio_dir / "_pieces"
    shutil.rmtree(piece_dir, ignore_errors=True)
    piece_dir.mkdir(parents=True, exist_ok=True)

    settings = settings or {}
    files: list[str] = []
    inputs: list[Path] = []
    total_chars = 0
    gap = audio_dir / "_gap.mp3"

    chunks = manifest["chunks"]
    total_chunks = len(chunks)

    for chunk_idx, row in enumerate(chunks):
        chunk_num = row["index"]
        text_path = run_dir / row["path"]
        text = text_path.read_text(encoding="utf-8").strip()
        if not text:
            continue
        total_chars += len(text)

        chunk_mp3 = audio_dir / ("%03d.mp3" % chunk_num)
        if skip_existing and chunk_mp3.is_file():
            logger.info("SKIP chunk %d (file exists: %s)", chunk_num, chunk_mp3.name)
            files.append(str(chunk_mp3.relative_to(run_dir)))
            inputs.append(chunk_mp3)
            # vẫn thêm gap nếu không phải chunk cuối
            if chunk_idx < total_chunks - 1:
                if not gap.exists():
                    make_silence_mp3(gap, inter_chunk_gap_sec)
                if gap.exists():
                    inputs.append(gap)
            continue

        pieces = split_for_synthesis(text)
        total_pieces = len(pieces)

        # synth từng mảnh câu -> wav
        piece_paths: list[Path] = []
        for piece_index, piece in enumerate(pieces):
            if progress_cb:
                progress_cb(chunk_idx, total_chunks, piece_index, total_pieces)
            wav_bytes = synthesize_wav(piece, speaker, base_url, settings)
            piece_path = piece_dir / ("%03d_%04d.wav" % (chunk_num, piece_index))
            piece_path.write_bytes(wav_bytes)
            piece_paths.append(piece_path)
            # Delay giữa các piece để VOICEVOX engine không bị quá tải
            if piece_index < total_pieces - 1 and inter_piece_delay_sec > 0:
                time.sleep(inter_piece_delay_sec)

        # gộp mảnh -> chunk wav -> mp3 theo manifest
        chunk_wav = audio_dir / ("%03d.wav" % chunk_num)
        if len(piece_paths) == 1:
            chunk_wav.write_bytes(piece_paths[0].read_bytes())
        else:
            concat_audio(piece_paths, chunk_wav)
        if wav_to_mp3(chunk_wav, chunk_mp3):
            chunk_wav.unlink(missing_ok=True)
            files.append(str(chunk_mp3.relative_to(run_dir)))
            inputs.append(chunk_mp3)
        else:
            files.append(str(chunk_wav.relative_to(run_dir)))
            inputs.append(chunk_wav)
        # khoảng lặng giữa các chunk (không thêm sau chunk cuối)
        if chunk_idx < total_chunks - 1:
            if not gap.exists():
                make_silence_mp3(gap, inter_chunk_gap_sec)
            if gap.exists():
                inputs.append(gap)
            # Delay để VOICEVOX engine hồi phục tránh treo sau nhiều request dài
            if inter_chunk_delay_sec > 0:
                logger.info("Delay %.1fs before next chunk...", inter_chunk_delay_sec)
                time.sleep(inter_chunk_delay_sec)

    merged = run_dir / "audio" / "narration-merged.mp3"
    if inputs:
        concat_audio(inputs, merged)
    shutil.rmtree(piece_dir, ignore_errors=True)
    gap.unlink(missing_ok=True)

    return {"files": files, "merged": str(merged.relative_to(run_dir)), "total_chars": total_chars}
