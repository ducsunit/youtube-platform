"""Sequential batch conversion with explicit upload-order pairing."""

from dataclasses import dataclass
import logging
from pathlib import Path
import re
from typing import Any, Callable, List, Optional, Sequence
import uuid
import zipfile

from .converter import convert_to_srt


logger = logging.getLogger(__name__)
BatchProgress = Callable[[int, int, str], None]
PAIRING_HEADERS = ["STT", "Script", "Audio #", "Audio", "Trạng thái"]
REPORT_HEADERS = ["STT", "Script", "Audio", "Kết quả", "Chỉ số"]


@dataclass(frozen=True)
class BatchResult:
    zip_path: str
    report_rows: List[List[Any]]
    succeeded: int
    failed: int


def build_pairing_rows(
    script_paths: Sequence[str], audio_paths: Sequence[str]
) -> List[List[Any]]:
    """Pair files by the exact order received from the browser."""
    rows: List[List[Any]] = []
    total = max(len(script_paths), len(audio_paths))
    counts_match = len(script_paths) == len(audio_paths)
    for index in range(total):
        script_name = Path(script_paths[index]).name if index < len(script_paths) else "—"
        audio_name = Path(audio_paths[index]).name if index < len(audio_paths) else "—"
        audio_number = index + 1 if index < len(audio_paths) else None
        if index >= len(script_paths):
            status = "Thiếu script"
        elif index >= len(audio_paths):
            status = "Thiếu audio"
        else:
            status = "Sẵn sàng" if counts_match else "Kiểm tra số lượng"
        rows.append([index + 1, script_name, audio_number, audio_name, status])
    return rows


def _table_rows(table: Any) -> List[List[Any]]:
    if table is None:
        return []
    if hasattr(table, "values"):
        return table.values.tolist()
    if isinstance(table, dict):
        data = table.get("data", [])
        return list(data)
    return list(table)


def parse_audio_order(table: Any, script_count: int, audio_count: int) -> List[int]:
    """Read editable 1-based Audio # cells and return zero-based indexes."""
    if script_count == 0:
        raise ValueError("Vui lòng tải lên ít nhất một script.")
    if script_count != audio_count:
        raise ValueError(
            f"Số lượng không khớp: {script_count} script và {audio_count} audio."
        )
    rows = _table_rows(table)
    if not rows:
        return list(range(audio_count))
    if len(rows) != script_count:
        raise ValueError("Bảng ghép cặp không khớp danh sách script. Hãy bấm Ghép cặp lại.")

    order: List[int] = []
    for row_number, row in enumerate(rows, start=1):
        try:
            raw_value = row[2]
            numeric = float(raw_value)
            if not numeric.is_integer():
                raise ValueError
            audio_index = int(numeric) - 1
        except (IndexError, TypeError, ValueError):
            raise ValueError(f"Audio # tại dòng {row_number} không hợp lệ.") from None
        if not 0 <= audio_index < audio_count:
            raise ValueError(
                f"Audio # tại dòng {row_number} phải từ 1 đến {audio_count}."
            )
        order.append(audio_index)
    if len(set(order)) != len(order):
        raise ValueError("Mỗi Audio # chỉ được sử dụng một lần.")
    return order


def _safe_stem(path: str) -> str:
    stem = Path(path).stem.strip() or "subtitles"
    cleaned = re.sub(r"[^\w.\-\u3040-\u30ff\u3400-\u9fff]+", "-", stem)
    return cleaned.strip("-.") or "subtitles"


def convert_batch(
    script_paths: Sequence[str],
    audio_paths: Sequence[str],
    pairing_table: Any,
    output_root: str,
    max_chars: int = 24,
    model_size: str = "large-v3",
    device: str = "cpu",
    alignment_mode: str = "accurate",
    progress: Optional[BatchProgress] = None,
) -> BatchResult:
    """Convert pairs sequentially and package successes plus a report as ZIP."""
    scripts = [str(path) for path in script_paths]
    audios = [str(path) for path in audio_paths]
    audio_order = parse_audio_order(pairing_table, len(scripts), len(audios))

    batch_id = uuid.uuid4().hex[:8]
    batch_dir = Path(output_root) / f"batch-{batch_id}"
    batch_dir.mkdir(parents=True, exist_ok=False)
    report_rows: List[List[Any]] = []
    successful_files: List[Path] = []

    for index, (script_path, audio_index) in enumerate(
        zip(scripts, audio_order), start=1
    ):
        audio_path = audios[audio_index]
        label = f"{Path(script_path).name} ↔ {Path(audio_path).name}"
        if progress:
            progress(index - 1, len(scripts), f"Đang xử lý {index}/{len(scripts)}: {label}")
        output_path = batch_dir / f"{index:03d}-{_safe_stem(script_path)}.srt"
        try:
            result = convert_to_srt(
                script_path,
                audio_path,
                str(output_path),
                max_chars,
                model_size,
                device,
                alignment_mode,
            )
            metric = f"{result.similarity:.0f}%"
            status = "Thành công" if not result.needs_review else "Thành công — cần kiểm tra"
            successful_files.append(output_path)
            logger.info("Batch item %d thành công | %s", index, label)
        except Exception as exc:
            metric = "—"
            status = f"Lỗi: {exc}"
            logger.exception("Batch item %d thất bại | %s", index, label)
        report_rows.append(
            [index, Path(script_path).name, Path(audio_path).name, status, metric]
        )

    succeeded = len(successful_files)
    failed = len(scripts) - succeeded
    report_path = batch_dir / "batch-report.txt"
    report_lines = ["JP Script to SRT — Batch report", ""]
    for row in report_rows:
        report_lines.append(
            f"{row[0]:03d} | {row[1]} | {row[2]} | {row[3]} | {row[4]}"
        )
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    zip_path = Path(output_root) / f"subtitles-batch-{batch_id}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in successful_files:
            archive.write(path, arcname=path.name)
        archive.write(report_path, arcname=report_path.name)
    if progress:
        progress(len(scripts), len(scripts), "Hoàn tất batch")
    logger.info(
        "Batch hoàn tất | total=%d | succeeded=%d | failed=%d | zip=%s",
        len(scripts),
        succeeded,
        failed,
        zip_path,
    )
    return BatchResult(str(zip_path), report_rows, succeeded, failed)

