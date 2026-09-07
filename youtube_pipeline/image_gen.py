"""OpenAI image generation job for resource-pack runs.

The API starts this module as a detached subprocess so a slow image batch does
not block FastAPI. Prompts are read from the run's canonical prompt-pack and
outputs are written using the image IDs expected by the video build flow.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path


def log(message: str) -> None:
    print("[%s] %s" % (datetime.now(timezone.utc).isoformat(), message), flush=True)


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


def _key_from_env(user_id: str | None = None, channel_id: str | None = None) -> str:
    from .image_config import resolve_api_key

    value = resolve_api_key(Path.cwd(), user_id, channel_id)
    if not value:
        raise RuntimeError("Thiếu OPENAI_API_KEY trên API server.")
    return value


def _write_image(response, output: Path) -> None:
    item = response.data[0]
    b64 = getattr(item, "b64_json", None)
    if b64:
        output.write_bytes(base64.b64decode(b64))
        return
    url = getattr(item, "url", None)
    if url:
        import urllib.request

        output.write_bytes(urllib.request.urlopen(url, timeout=120).read())
        return
    raise RuntimeError("OpenAI image response không có b64_json hoặc url.")


def generate_batch(run_dir: Path, indices: list[str], model: str, size: str, quality: str, user_id: str | None = None, channel_id: str | None = None) -> None:
    from openai import OpenAI
    from .image_config import load

    prompts = {row["image_id"]: row["prompt"] for row in _load_prompts(run_dir)}
    output_dir = run_dir / "video-build" / "images"
    output_dir.mkdir(parents=True, exist_ok=True)
    config = load(Path.cwd(), user_id, channel_id)
    api_key = _key_from_env(user_id, channel_id)
    base_url = config.get("base_url") or None
    log("CONFIG model=%s base_url=%s api_key_configured=%s size=%s quality=%s" % (config.get("model"), base_url, bool(api_key), size, quality))
    log("PROVIDER client_init provider=openai_image model=%s base_url=%s" % (model, base_url))
    client = OpenAI(api_key=api_key, base_url=base_url)
    for image_id in indices:
        prompt = prompts.get(image_id)
        if not prompt:
            raise RuntimeError("Không tìm thấy prompt cho %s." % image_id)
        output = output_dir / (image_id + ".png")
        if output.exists():
            log("SKIP image_id=%s reason=exists" % image_id)
            continue
        log("PROVIDER_CALL start image_id=%s model=%s size=%s quality=%s prompt_chars=%d" % (image_id, model, size, quality, len(prompt)))
        try:
            response = client.images.generate(model=model, prompt=prompt, size=size, quality=quality)
            log("PROVIDER_CALL success image_id=%s response_items=%d" % (image_id, len(getattr(response, "data", []) or [])))
        except Exception as exc:
            log("PROVIDER_CALL failed image_id=%s error_type=%s error=%s" % (image_id, type(exc).__name__, exc))
            log(traceback.format_exc().rstrip())
            raise
        temporary = output.with_suffix(".tmp.png")
        try:
            _write_image(response, temporary)
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
        log("OUTPUT saved image_id=%s path=%s bytes=%d" % (image_id, output, output.stat().st_size))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id")
    parser.add_argument("--channel-id")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("model")
    parser.add_argument("size")
    parser.add_argument("quality")
    parser.add_argument("images", nargs="+")
    args = parser.parse_args()
    if bool(args.user_id) != bool(args.channel_id):
        parser.error("--user-id và --channel-id phải được truyền cùng nhau")
    generate_batch(args.run_dir, args.images, args.model, args.size, args.quality, args.user_id, args.channel_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
