"""Gen clip Veo image-to-video — chạy như subprocess bởi veo_runner.

Usage:
    python -m youtube_pipeline.veo_gen \\
        --run-dir runs/video-07 \\
        --images 01,03,07 \\
        --model veo-3.1-generate-preview

Mỗi ảnh IMG-xx được đọc từ video-build/images/IMG-xx.{png,jpg,jpeg,webp},
prompt + motion hint lấy từ visuals/prompts/prompts-video.txt, output ghi
vào video-build/clips/IMG-xx.mp4.

Exit 0 = tất cả ảnh được chọn thành công (hoặc đã có clip sẵn và --skip-existing).
Exit 1 = ít nhất một ảnh thất bại.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Lỗi tạm — thử lại có ý nghĩa (429 quota/rate, 500/503 server, 504 timeout).
_RETRYABLE = frozenset({429, 500, 503, 504})

# Giải thích lỗi theo status code — để log nói được "phải làm gì", không chỉ echo API.
_CODE_HINT = {
    400: "Request sai (prompt bị chặn hoặc ảnh sai định dạng) — xem details bên dưới.",
    401: "API key không hợp lệ.",
    403: "Key không có quyền gọi Veo (project chưa bật billing / chưa được cấp Veo).",
    404: "Model không tồn tại ở API version này — chạy 'veo_gen --list-models' để xem model khả dụng.",
    429: "Hết quota Veo. Video gen tính quota riêng và rất chặt: free tier thường "
         "KHÔNG gọi được Veo. Kiểm tra https://ai.dev/rate-limit; thử model "
         "-fast-/-lite-, hoặc bật billing.",
    500: "Lỗi nội bộ Google — thử lại sau.",
    503: "Model đang quá tải — thử lại sau.",
}

# ------------------------------------------------------------------ parse


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Gen clip Veo image-to-video")
    p.add_argument("--run-dir", required=True, type=Path, help="Thư mục run, e.g. runs/video-07")
    p.add_argument(
        "--images",
        required=True,
        help="Danh sách số thứ tự IMG, phân cách bằng dấu phẩy (e.g. 01,03,07)",
    )
    p.add_argument(
        "--model",
        default="veo-3.1-generate-preview",
        help="Model Veo (mặc định veo-3.1-generate-preview)",
    )
    p.add_argument(
        "--skip-existing",
        action="store_true",
        help="Bỏ qua ảnh đã có clip trong video-build/clips/",
    )
    p.add_argument(
        "--retries",
        type=int,
        default=2,
        help="Số lần thử lại khi lỗi tạm 429/5xx (mặc định 2, backoff 30/60s)",
    )
    p.add_argument(
        "--poll-timeout",
        type=int,
        default=600,
        help="Trần thời gian chờ 1 clip, giây (mặc định 600)",
    )
    p.add_argument(
        "--list-models",
        action="store_true",
        help="Chỉ in các model hỗ trợ video gen trên key hiện tại rồi thoát",
    )
    return p.parse_args(argv)


# ------------------------------------------------------------------ helpers


def _log(msg: str) -> None:
    """In ra stdout với flush ngay (subprocess fd inherit, không pipe)."""
    print(msg, flush=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _CallLog:
    """Ghi log JSONL từng lần gọi Veo API vào run_dir/logs/veo-calls.jsonl.

    Mỗi dòng là 1 event độc lập → grep/jq được, không bị trộn với stdout job.
    Lỗi ghi file KHÔNG được làm chết job (log là phụ trợ).
    """

    def __init__(self, run_dir: Path) -> None:
        self.path = run_dir / "logs" / "veo-calls.jsonl"
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.path = None  # type: ignore[assignment]

    def write(self, event: dict[str, Any]) -> None:
        if self.path is None:
            return
        record = {"ts": _now(), **event}
        try:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass


def _err_info(exc: BaseException) -> dict[str, Any]:
    """Bóc status code + details từ google.genai APIError (nếu là APIError).

    Trả dict luôn có 'error_type' và 'message'; có 'code'/'status'/'details' khi
    là lỗi HTTP từ API. Không bao giờ raise.
    """
    info: dict[str, Any] = {
        "error_type": type(exc).__name__,
        "message": str(exc)[:2000],
    }
    for attr in ("code", "status", "message"):
        value = getattr(exc, attr, None)
        if value is not None:
            info["api_%s" % attr if attr == "message" else attr] = value
    details = getattr(exc, "details", None)
    if details is not None:
        try:
            info["details"] = json.loads(json.dumps(details, ensure_ascii=False, default=str))
        except (TypeError, ValueError):
            info["details"] = str(details)[:2000]
    code = info.get("code")
    if isinstance(code, int) and code in _CODE_HINT:
        info["hint"] = _CODE_HINT[code]
    return info


def _find_image(images_dir: Path, idx: str) -> Optional[Path]:
    """Tìm IMG-xx với đuôi png/jpg/jpeg/webp."""
    for ext in ("png", "jpg", "jpeg", "webp"):
        p = images_dir / ("IMG-%s.%s" % (idx, ext))
        if p.is_file():
            return p
    return None


def _parse_prompts_video(prompts_file: Path) -> dict[str, dict]:
    """Đọc prompts-video.txt → {idx: {motion, prompt}}.

    Định dạng mỗi dòng: IMG-xx | <motion gợi ý> — <prompt tiếng Anh>
    Bỏ qua dòng comment (#) và dòng rỗng.
    """
    result: dict[str, dict] = {}
    if not prompts_file.is_file():
        return result
    for raw in prompts_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # IMG-xx | motion — prompt
        if "|" not in line:
            continue
        img_part, rest = line.split("|", 1)
        img_key = img_part.strip()  # e.g. "IMG-01"
        if not img_key.startswith("IMG-"):
            continue
        idx = img_key[4:]  # "01"
        motion = ""
        prompt = rest.strip()
        if " — " in rest:
            motion, prompt = rest.split(" — ", 1)
            motion = motion.strip()
            prompt = prompt.strip()
        elif " - " in rest:
            motion, prompt = rest.split(" - ", 1)
            motion = motion.strip()
            prompt = prompt.strip()
        result[idx] = {"motion": motion, "prompt": prompt}
    return result


def _build_veo_prompt(motion: str, prompt: str) -> str:
    """Kết hợp motion hint + prompt thành câu lệnh cho Veo."""
    parts = []
    if motion:
        parts.append(motion.rstrip(".") + ".")
    if prompt:
        parts.append(prompt)
    return " ".join(parts)


# ------------------------------------------------------------------ Veo call


def _generate_clip(
    client,
    model: str,
    image_path: Path,
    veo_prompt: str,
    out_path: Path,
    tag: str = "",
    calls: "_CallLog | None" = None,
    retries: int = 2,
    poll_timeout: int = 600,
) -> None:
    """Gọi Veo API cho một ảnh; lưu mp4 vào out_path. Raise nếu lỗi.

    Log mọi lần submit (kèm status code khi lỗi) vào calls. Lỗi tạm (429/5xx)
    được thử lại tối đa `retries` lần với backoff 30s/60s/120s.
    """
    from google.genai import types as genai_types

    mime_map = {".png": "image/png", ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg", ".webp": "image/webp"}
    mime = mime_map.get(image_path.suffix.lower(), "image/png")
    image_bytes = image_path.read_bytes()
    base = {
        "img": tag,
        "model": model,
        "image_file": image_path.name,
        "image_bytes": len(image_bytes),
        "image_mime": mime,
        "prompt_chars": len(veo_prompt),
    }

    operation = None
    for attempt in range(1, retries + 2):
        started = time.monotonic()
        _log("    Gọi Veo API model=%s (lần %d/%d) ..." % (model, attempt, retries + 1))
        try:
            operation = client.models.generate_videos(
                model=model,
                prompt=veo_prompt,
                image=genai_types.Image(image_bytes=image_bytes, mime_type=mime),
                config=genai_types.GenerateVideosConfig(
                    aspect_ratio="16:9",
                    number_of_videos=1,
                ),
            )
        except Exception as exc:  # noqa: BLE001 — cần log rồi mới quyết định retry
            info = _err_info(exc)
            elapsed = round(time.monotonic() - started, 2)
            if calls:
                calls.write({"event": "submit_failed", "attempt": attempt,
                             "elapsed_s": elapsed, **base, **info})
            code = info.get("code")
            hint = info.get("hint")
            _log("    ✗ submit lỗi sau %.1fs: code=%s status=%s" % (
                elapsed, code, info.get("status")))
            if info.get("api_message"):
                _log("      message: %s" % str(info["api_message"])[:300])
            if hint:
                _log("      → %s" % hint)
            if isinstance(code, int) and code in _RETRYABLE and attempt <= retries:
                backoff = 30 * (2 ** (attempt - 1))
                _log("      lỗi tạm → thử lại sau %ds" % backoff)
                time.sleep(backoff)
                continue
            raise
        if calls:
            calls.write({"event": "submitted", "attempt": attempt,
                         "elapsed_s": round(time.monotonic() - started, 2),
                         "operation": getattr(operation, "name", None), **base})
        break

    if operation is None:
        raise RuntimeError("Không submit được job Veo")

    # Poll cho đến khi xong — có trần thời gian để job không treo vô hạn.
    poll_started = time.monotonic()
    wait = 10
    while not operation.done:
        elapsed = int(time.monotonic() - poll_started)
        if elapsed > poll_timeout:
            if calls:
                calls.write({"event": "poll_timeout", "elapsed_s": elapsed,
                             "operation": getattr(operation, "name", None), **base})
            raise RuntimeError(
                "Veo chưa xong sau %ds (operation=%s) — bỏ chờ"
                % (elapsed, getattr(operation, "name", "?"))
            )
        time.sleep(wait)
        _log("    Đang chờ... (%ds)" % int(time.monotonic() - poll_started))
        try:
            operation = client.operations.get(operation)
        except Exception as exc:  # noqa: BLE001 — poll lỗi cũng phải log
            info = _err_info(exc)
            if calls:
                calls.write({"event": "poll_failed", **base, **info})
            _log("    ✗ poll lỗi: code=%s %s" % (info.get("code"), info.get("status")))
            raise

    poll_s = round(time.monotonic() - poll_started, 2)

    # operation.error được set khi Veo từ chối/thất bại phía server.
    op_error = getattr(operation, "error", None)
    if op_error:
        if calls:
            calls.write({"event": "operation_error", "poll_s": poll_s,
                         "operation_error": str(op_error)[:2000], **base})
        raise RuntimeError("Veo trả lỗi trong operation: %s" % str(op_error)[:500])

    videos = getattr(operation.response, "generated_videos", None) or []
    if not videos:
        # Hay xảy ra khi prompt/ảnh bị safety filter chặn — response rỗng, không error.
        rai = getattr(operation.response, "rai_media_filtered_reasons", None)
        count = getattr(operation.response, "rai_media_filtered_count", None)
        if calls:
            calls.write({"event": "empty_response", "poll_s": poll_s,
                         "rai_filtered_count": count,
                         "rai_filtered_reasons": [str(r)[:500] for r in (rai or [])],
                         **base})
        detail = ""
        if rai:
            detail = " — bị filter: %s" % "; ".join(str(r)[:200] for r in rai)
        elif count:
            detail = " — %s video bị filter (safety)" % count
        raise RuntimeError("Veo không trả về video nào (response trống)%s" % detail)

    video_ref = videos[0].video
    _log("    Tải về clip...")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    dl_started = time.monotonic()
    client.files.download(file=video_ref)
    video_ref.save(str(out_path))
    size = out_path.stat().st_size
    if calls:
        calls.write({"event": "saved", "poll_s": poll_s,
                     "download_s": round(time.monotonic() - dl_started, 2),
                     "out_file": out_path.name, "out_bytes": size, **base})
    _log("    Đã lưu: %s (%d bytes)" % (out_path.name, size))


# ------------------------------------------------------------------ main


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    # .env trước, rồi mới đọc key — cwd là backend root khi spawn từ API server.
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        _log("LỖI: Thiếu GEMINI_API_KEY hoặc GOOGLE_API_KEY (env hoặc .env)")
        return 1

    run_dir = args.run_dir.resolve()
    if not run_dir.is_dir():
        _log("LỖI: run_dir không tồn tại: %s" % run_dir)
        return 1

    images_dir = run_dir / "video-build" / "images"
    clips_dir = run_dir / "video-build" / "clips"
    prompts_file = run_dir / "visuals" / "prompts" / "prompts-video.txt"

    indices = [s.strip() for s in args.images.split(",") if s.strip()]
    if not indices:
        _log("LỖI: Danh sách --images rỗng")
        return 1

    prompts_map = _parse_prompts_video(prompts_file)
    _log("=== Veo Gen | run=%s | %d ảnh | model=%s ===" % (run_dir.name, len(indices), args.model))

    # Import client ở đây — fail sớm trước khi xử lý ảnh
    try:
        from google import genai  # type: ignore
    except ImportError:
        _log("LỖI: Thư viện google-genai chưa cài. Chạy: pip install google-genai")
        return 1

    client = genai.Client(api_key=api_key)

    # --list-models: in các model khả dụng rồi thoát
    if args.list_models:
        _log("=== Model khả dụng cho video gen trên key này ===")
        try:
            usable = [
                m.name.split("/")[-1] for m in client.models.list()
                if "predictLongRunning" in (getattr(m, "supported_actions", None) or [])
            ]
            for model_name in usable:
                _log("  - %s" % model_name)
            if not usable:
                _log("  (không có model nào)")
            return 0
        except Exception as exc:
            _log("LỖI khi list models: %s" % exc)
            return 1

    calls = _CallLog(run_dir)
    if calls.path is not None:
        _log("Log chi tiết: %s" % calls.path)
    calls.write({"event": "job_start", "run": run_dir.name, "model": args.model,
                 "images": indices, "retries": args.retries})

    # Model không khả dụng -> 404 cho từng ảnh. Check 1 lần, báo ngay.
    try:
        usable = [
            m.name.split("/")[-1] for m in client.models.list()
            if "predictLongRunning" in (getattr(m, "supported_actions", None) or [])
        ]
        if usable and args.model not in usable:
            _log("LỖI: model '%s' không khả dụng trên key này." % args.model)
            _log("Model dùng được: %s" % ", ".join(usable))
            calls.write({"event": "model_unavailable", "model": args.model,
                         "available": usable})
            return 1
    except Exception as exc:  # noqa: BLE001 — check phụ trợ, không chặn job
        calls.write({"event": "model_list_failed", **_err_info(exc)})

    failed: list[str] = []
    for idx in indices:
        tag = "IMG-%s" % idx
        out_path = clips_dir / ("%s.mp4" % tag)

        if args.skip_existing and out_path.is_file():
            _log("[%s] Đã có clip → bỏ qua" % tag)
            continue

        img_path = _find_image(images_dir, idx)
        if img_path is None:
            _log("[%s] LỖI: Không tìm thấy ảnh trong %s" % (tag, images_dir))
            failed.append(idx)
            continue

        prompt_info = prompts_map.get(idx, {})
        motion = prompt_info.get("motion", "")
        prompt = prompt_info.get("prompt", "Image to video clip, smooth cinematic motion, 16:9.")
        veo_prompt = _build_veo_prompt(motion, prompt)

        _log("[%s] Ảnh: %s" % (tag, img_path.name))
        _log("[%s] Prompt: %s" % (tag, veo_prompt[:120] + ("..." if len(veo_prompt) > 120 else "")))

        try:
            _generate_clip(
                client, args.model, img_path, veo_prompt, out_path,
                tag=tag, calls=calls, retries=args.retries, poll_timeout=args.poll_timeout
            )
            _log("[%s] ✓ OK" % tag)
        except Exception as exc:
            _log("[%s] LỖI: %s" % (tag, exc))
            failed.append(idx)

    _log("=== Hoàn tất: %d/%d thành công ===" % (len(indices) - len(failed), len(indices)))
    calls.write({"event": "job_end", "total": len(indices), "failed": len(failed),
                 "failed_indices": failed})
    if failed:
        _log("Thất bại: " + ", ".join("IMG-%s" % i for i in failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
