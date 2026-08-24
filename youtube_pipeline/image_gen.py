"""OpenAI image generation job for resource-pack runs.

The API starts this module as a detached subprocess so a slow image batch does
not block FastAPI. Prompts are read from the run's canonical prompt-pack and
outputs are written using the image IDs expected by the video build flow.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import threading
import time
import traceback
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


# Proxy hhtech 503 "thử lại sau ~25s" khi upstream hết nguồn.
IMAGE_MAX_ATTEMPTS = 3
IMAGE_RETRY_WAIT_SEC = 25
# Timeout/Connection: request hợp lệ (ảnh 2K qua proxy) có thể cần > 3 phút —
# cho 5 lần thử, chờ ngắn 8s×lần thay vì chặt 180s + backoff dài như rate-limit.
IMAGE_TIMEOUT_SEC = 300
TIMEOUT_MAX_ATTEMPTS = 5
TIMEOUT_RETRY_WAIT_SEC = 8
# Sweep: sau vòng chính tự quét ảnh thiếu gen tiếp tới khi đủ 100% (trần thời gian cứng).
SWEEP_ROUNDS = 3
SWEEP_MAX_MINUTES = 180


def log(message: str) -> None:
    print("[%s] %s" % (datetime.now(timezone.utc).isoformat(), message), flush=True)


class ImageCallLogger:
    """Structured JSONL logger for image generation calls."""

    _lock = threading.Lock()  # concurrency > 1: nhiều thread ghi chung file

    def __init__(self, run_dir: Path, job_id: str) -> None:
        self.path = run_dir / "logs" / "image-calls.jsonl"
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.path = None
        self.job_id = job_id

    def write(self, event: str, **kwargs: Any) -> None:
        if self.path is None:
            return
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "job_id": self.job_id,
            "event": event,
            **kwargs
        }
        try:
            with ImageCallLogger._lock:
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass


def _load_prompts(run_dir: Path) -> list[dict[str, str]]:
    path = run_dir / "visuals" / "prompt-pack.json"
    if not path.is_file():
        raise RuntimeError("Không tìm thấy visuals/prompt-pack.json.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("images") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("prompt-pack.json không có danh sách images.")
    result = []
    for row in rows:
        image_id = str(row.get("image_id", "")).strip()
        prompt = str(row.get("prompt", "")).strip()
        if image_id and prompt:
            result.append({"image_id": image_id, "prompt": prompt})
    log("PROMPTS loaded path=%s count=%d" % (path, len(result)))
    return result


def _key_from_env() -> str:
    from .image_config import resolve_api_key

    value = resolve_api_key(Path.cwd())
    if not value:
        raise RuntimeError("Thiếu OPENAI_API_KEY trên API server.")
    return value


def _write_image(response, output: Path) -> None:
    # Proxy có lúc trả HTTP 200 nhưng data=null (biến thể "hết nguồn") —
    # bắt rõ thay vì crash TypeError ở UI.
    if not getattr(response, "data", None):
        raise RuntimeError(
            "Provider trả data rỗng (thường do hết nguồn upstream cho model này). Thử lại sau ít phút."
        )
    item = response.data[0]
    b64 = getattr(item, "b64_json", None)
    if b64:
        payload = base64.b64decode(b64)
        if not payload:
            raise RuntimeError("Provider trả ảnh rỗng.")
        output.write_bytes(payload)
        if not is_valid_image_file(output):
            raise RuntimeError("Provider trả dữ liệu không phải ảnh hợp lệ.")
        return
    url = getattr(item, "url", None)
    if url:
        import urllib.request
        import urllib.error

        try:
            with urllib.request.urlopen(url, timeout=120) as resp:
                payload = resp.read()
        except TimeoutError as exc:
            # Chuẩn hoá về TimeoutError để _retry_policy xếp vào nhóm timeout
            raise TimeoutError("Tải ảnh từ URL vượt 120s: %s" % exc) from None
        except urllib.error.URLError as exc:
            if isinstance(getattr(exc, "reason", None), TimeoutError):
                raise TimeoutError("Tải ảnh từ URL vượt 120s") from None
            raise
        if not payload:
            raise RuntimeError("Provider trả URL ảnh rỗng.")
        output.write_bytes(payload)
        if not is_valid_image_file(output):
            raise RuntimeError("URL provider trả dữ liệu không phải ảnh hợp lệ.")
        return
    raise RuntimeError("OpenAI image response không có b64_json hoặc url.")


def is_valid_image_file(path: Path) -> bool:
    """Reject empty/corrupt-looking outputs before they are treated as complete."""
    try:
        if path.stat().st_size < 32:
            return False
        with path.open("rb") as handle:
            header = handle.read(12)
    except OSError:
        return False
    return (
        header.startswith(b"\x89PNG\r\n\x1a\n")
        or header.startswith(b"\xff\xd8\xff")
        or (header.startswith(b"RIFF") and header[8:12] == b"WEBP")
    )


def _prompt_sha256(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _response_metadata(response: Any) -> dict[str, Any]:
    data = getattr(response, "data", None)
    items = data if isinstance(data, list) else []
    first = items[0] if items else None
    return {
        "response_type": type(response).__name__,
        "response_id": getattr(response, "id", None),
        "response_model": getattr(response, "model", None),
        "response_created": getattr(response, "created", None),
        "response_items": len(items),
        "has_b64": bool(first and getattr(first, "b64_json", None)),
        "has_url": bool(first and getattr(first, "url", None)),
        "item_type": type(first).__name__ if first else None,
    }


def _log_request_response(call_log: Optional[ImageCallLogger], image_id: str, attempt: int,
                          model: str, size: str, quality: str, prompt: str,
                          request_start: float, response: Any = None, error: Exception | None = None,
                          traceback_text: str = "") -> None:
    """Log request/response details for debugging."""
    elapsed = time.monotonic() - request_start
    
    # Standard log
    if error:
        log("PROVIDER_CALL failed image_id=%s attempt=%d error_type=%s error=%s elapsed=%.2fs" % (
            image_id, attempt, type(error).__name__, str(error)[:500], elapsed))
    else:
        data_count = len(getattr(response, "data", []) or [])
        log("PROVIDER_CALL success image_id=%s attempt=%d response_items=%d elapsed=%.2fs" % (
            image_id, attempt, data_count, elapsed))
    
    # Structured JSONL log
    if call_log:
        record = {
            "image_id": image_id,
            "attempt": attempt,
            "model": model,
            "size": size,
            "quality": quality,
            "prompt_chars": len(prompt),
            "prompt_sha256": _prompt_sha256(prompt),
            "elapsed_s": round(elapsed, 2),
        }
        if error:
            record.update({
                "event": "call_failed",
                "error_type": type(error).__name__,
                "error_message": str(error)[:1000],
                "traceback": traceback_text[-12000:] if traceback_text else None,
            })
        else:
            record.update({
                "event": "call_success",
                **_response_metadata(response),
            })
        call_log.write(**record)


def _retry_policy(exc: Exception) -> tuple[int, float]:
    """(số attempt tối đa, giây chờ cơ bản) theo LOẠI lỗi — không phải một policy chung.

    - Timeout/Connection: lỗi mạng hoặc ảnh nặng → retry nhanh (8s), cho 5 lần
      vì request hợp lệ có thể chỉ cần thêm thời gian.
    - RateLimit (429): backoff 25s×lần thử, tôn trọng header Retry-After nếu có.
    - TypeError: proxy trả body sai schema (thường hết nguồn 503) → coi như rate-limit.
    - Lỗi khác (request sai, auth...): fail fast, retry vô ích.
    """
    import openai

    # TimeoutError builtin: URL download / socket timeout — cùng nhóm với
    # APITimeoutError (retry nhanh, 5 lần) thay vì fail fast.
    if isinstance(exc, (openai.APITimeoutError, openai.APIConnectionError, TimeoutError)):
        return TIMEOUT_MAX_ATTEMPTS, TIMEOUT_RETRY_WAIT_SEC
    if isinstance(exc, openai.RateLimitError):
        retry_after: float | None = None
        try:
            raw = exc.response.headers.get("retry-after") if exc.response is not None else None
            retry_after = float(raw) if raw else None
        except Exception:
            retry_after = None
        return IMAGE_MAX_ATTEMPTS, retry_after or IMAGE_RETRY_WAIT_SEC
    if isinstance(exc, TypeError):
        return IMAGE_MAX_ATTEMPTS, IMAGE_RETRY_WAIT_SEC
    return 1, 0.0


def _generate_one(client, image_id: str, prompt: str, output: Path,
                  model: str, size: str, quality: str, call_log) -> tuple[str, str] | None:
    """Gen 1 ảnh với retry phân loại. Trả None khi thành công, (id, error) khi hụt."""
    prompt_sha256 = _prompt_sha256(prompt)
    image_start = time.monotonic()
    log("PROVIDER_CALL start image_id=%s model=%s size=%s quality=%s prompt_chars=%d" % (image_id, model, size, quality, len(prompt)))
    if call_log:
        call_log.write("image_start", image_id=image_id, output_path=str(output), model=model, size=size, quality=quality, prompt_chars=len(prompt), prompt_sha256=prompt_sha256)

    attempt = 0
    last_error: Exception | None = None
    last_traceback = ""
    while True:
        attempt += 1
        request_start = time.monotonic()
        temporary = output.with_suffix(".tmp.png")
        last_error = None
        last_traceback = ""
        if call_log:
            call_log.write("attempt_start", image_id=image_id, attempt=attempt, model=model, size=size, quality=quality, prompt_sha256=prompt_sha256)
        try:
            response = client.images.generate(model=model, prompt=prompt, size=size, quality=quality)
            _log_request_response(call_log, image_id, attempt, model, size, quality, prompt, request_start, response=response)
            if call_log:
                call_log.write("write_start", image_id=image_id, attempt=attempt, temporary_path=str(temporary), **_response_metadata(response))
            _write_image(response, temporary)
            if call_log:
                call_log.write("write_validated", image_id=image_id, attempt=attempt, temporary_path=str(temporary), bytes=temporary.stat().st_size, valid=is_valid_image_file(temporary))
            temporary.replace(output)
            if call_log:
                call_log.write("attempt_success", image_id=image_id, attempt=attempt, elapsed_s=round(time.monotonic() - request_start, 2), output_path=str(output), bytes=output.stat().st_size)
            file_size = output.stat().st_size
            log("OUTPUT saved image_id=%s path=%s bytes=%d" % (image_id, output, file_size))
            if call_log:
                call_log.write("image_saved", image_id=image_id, path=str(output), bytes=file_size, elapsed_s=round(time.monotonic() - image_start, 2), attempts_used=attempt)
            return None
        except TypeError as exc:
            last_error = RuntimeError(
                "Provider trả response lỗi (thường là hết nguồn 503). Chi tiết gốc: %s" % exc
            )
            last_traceback = traceback.format_exc()
            _log_request_response(call_log, image_id, attempt, model, size, quality, prompt, request_start, error=last_error, traceback_text=last_traceback)
        except Exception as exc:
            last_error = exc
            last_traceback = traceback.format_exc()
            _log_request_response(call_log, image_id, attempt, model, size, quality, prompt, request_start, error=exc, traceback_text=last_traceback)
        finally:
            if call_log and last_error is not None:
                call_log.write("attempt_failed", image_id=image_id, attempt=attempt, elapsed_s=round(time.monotonic() - request_start, 2), error_type=type(last_error).__name__, error_message=str(last_error)[:2000], traceback=last_traceback[-12000:])
            temporary.unlink(missing_ok=True)

        max_attempts, wait_base = _retry_policy(last_error)
        if attempt >= max_attempts:
            break
        wait_s = wait_base * attempt
        log("RETRY image_id=%s attempt=%d/%d sleep=%ds (%s)" % (
            image_id, attempt, max_attempts, wait_s, type(last_error).__name__))
        if call_log:
            call_log.write("retry", image_id=image_id, attempt=attempt, wait_s=wait_s, next_attempt=attempt + 1, error_type=type(last_error).__name__, error_message=str(last_error)[:2000])
        time.sleep(wait_s)

    log(last_traceback.rstrip() or repr(last_error))
    if call_log:
        call_log.write("image_failed_final", image_id=image_id, attempts=attempt, elapsed_s=round(time.monotonic() - image_start, 2), error_type=type(last_error).__name__, error=str(last_error)[:4000], traceback=last_traceback[-12000:], output_exists=output.exists(), output_valid=is_valid_image_file(output))
    log("SKIP-FAILED image_id=%s after=%d attempts last_error=%s" % (image_id, attempt, str(last_error)[:200]))
    return (image_id, str(last_error))


def generate_batch(run_dir: Path, indices: list[str], model: str, size: str, quality: str,
                   job_id: str = "", concurrency: int = 1, sweep_rounds: int = SWEEP_ROUNDS,
                   max_minutes: float = SWEEP_MAX_MINUTES) -> None:
    from openai import OpenAI
    from .image_config import load

    prompts = {row["image_id"]: row["prompt"] for row in _load_prompts(run_dir)}
    output_dir = run_dir / "video-build" / "images"
    output_dir.mkdir(parents=True, exist_ok=True)
    config = load(Path.cwd())
    api_key = _key_from_env()
    base_url = config.get("base_url") or None
    log("CONFIG model=%s base_url=%s api_key_configured=%s size=%s quality=%s concurrency=%d" % (config.get("model"), base_url, bool(api_key), size, quality, concurrency))
    log("PROVIDER client_init provider=openai_image model=%s base_url=%s" % (model, base_url))
    # SDK retry tắt — retry tự quản theo loại lỗi (timeout vs rate-limit).
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=IMAGE_TIMEOUT_SEC, max_retries=0)

    call_log = ImageCallLogger(run_dir, job_id)
    if call_log.path:
        log("Image call log: %s" % call_log.path)
        call_log.write(
            "batch_start",
            run_dir=str(run_dir),
            requested_images=indices,
            requested_count=len(indices),
            model=model,
            size=size,
            quality=quality,
            base_url=base_url,
            timeout_sec=IMAGE_TIMEOUT_SEC,
            concurrency=concurrency,
            sweep_rounds=sweep_rounds,
            sdk_max_retries=0,
        )

    # Health check fail-fast: chỉ chặn khi AUTH sai (401/403) — lỗi đó đốt cả batch.
    # Proxy thiếu endpoint /models (404/501) KHÔNG chặn: images.generate vẫn chạy tốt.
    try:
        next(iter(client.models.list()), None)
        log("HEALTH OK — provider reachable")
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        message = str(exc)
        if status in (401, 403) or "api key" in message.lower() or "unauthorized" in message.lower():
            if call_log:
                call_log.write("health_failed", error=message[:500])
            raise RuntimeError("Provider từ chối API key (401/403): %s" % message[:300]) from exc
        log("HEALTH WARNING — không kiểm tra được /models (%s); vẫn tiếp tục gen." % message[:150])

    deadline = time.monotonic() + max_minutes * 60

    def run_round(pending: list[str]) -> list[tuple[str, str]]:
        failed: list[tuple[str, str]] = []
        # Re-check trước khi gen: ảnh có thể đã có (round trước / job cũ) —
        # log SKIP giữ marker cho progress % phía UI.
        todo: list[tuple[str, Path, str]] = []
        for image_id in pending:
            output = output_dir / (image_id + ".png")
            if is_valid_image_file(output):
                log("SKIP image_id=%s reason=exists" % image_id)
                if call_log:
                    call_log.write("skip", image_id=image_id, reason="exists")
                continue
            prompt = prompts.get(image_id)
            if not prompt:
                raise RuntimeError("Không tìm thấy prompt cho %s." % image_id)
            todo.append((image_id, output, prompt))

        def _run(image_id: str, output: Path, prompt: str):
            return _generate_one(client, image_id, prompt, output, model, size, quality, call_log)

        if concurrency > 1 and len(todo) > 1:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            with ThreadPoolExecutor(max_workers=min(concurrency, len(todo))) as pool:
                futures = [pool.submit(_run, *item) for item in todo]
                # as_completed: log marker "OUTPUT saved" theo thứ tự HOÀN THÀNH
                # thật → progress % phía UI cập nhật realtime, không trễ theo ảnh chậm.
                for fut in as_completed(futures):
                    result = fut.result()
                    if result is not None:
                        failed.append(result)
        else:
            for image_id, output, prompt in todo:
                result = _run(image_id, output, prompt)
                if result is not None:
                    failed.append(result)
        return failed

    # Sweep loop: vòng 1 xử lý tất cả (skip ảnh đã có); các vòng sau chỉ gen
    # phần thiếu — đảm bảo 100% mà không cần bấm lại tay. Trần thời gian cứng.
    still_missing: list[tuple[str, str]] = []
    for round_no in range(1, sweep_rounds + 1):
        pending = [i for i in indices if not is_valid_image_file(output_dir / (i + ".png"))]
        if not pending:
            break
        if round_no > 1 and time.monotonic() > deadline:
            log("SWEEP dừng — vượt trần %.0f phút, còn %d ảnh thiếu." % (max_minutes, len(pending)))
            break
        if round_no > 1:
            log("SWEEP round %d/%d: gen tiếp %d ảnh thiếu" % (round_no, sweep_rounds, len(pending)))
        still_missing = run_round(pending)

    missing_now = [i for i in indices if not is_valid_image_file(output_dir / (i + ".png"))]
    if missing_now:
        ids = ", ".join(missing_now)
        log("BATCH SUMMARY failed_count=%d failed_ids=%s (sau %d vòng sweep)" % (len(missing_now), ids, sweep_rounds))
        if call_log:
            call_log.write("batch_failed", failed_count=len(missing_now), failed_ids=missing_now, requested_count=len(indices))
        raise RuntimeError("Một số ảnh không gen được: %s — các ảnh khác đã lưu thành công." % ids)
    log("BATCH COMPLETE %d/%d ảnh — đủ 100%%" % (len(indices), len(indices)))
    if call_log:
        call_log.write("batch_complete", requested_count=len(indices), failed_count=0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("model")
    parser.add_argument("size")
    parser.add_argument("quality")
    parser.add_argument("images", nargs="+")
    parser.add_argument("--job-id", default="", help="Job ID for structured logging")
    parser.add_argument("--concurrency", type=int, default=1, help="Số ảnh gen song song (1 = tuần tự).")
    parser.add_argument("--max-minutes", type=float, default=SWEEP_MAX_MINUTES,
                        help="Trần thời gian tổng cho toàn bộ sweep (phút).")
    args = parser.parse_args()
    generate_batch(args.run_dir, args.images, args.model, args.size, args.quality, args.job_id,
                   concurrency=max(1, args.concurrency), max_minutes=args.max_minutes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
