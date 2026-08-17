from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


CACHE_SCHEMA_VERSION = "2"


class LLMResponseCache:
    """Small persistent cache for deterministic LLM calls.

    The key includes model, system prompt, user prompt, temperature and
    reasoning tier, so changing any material input naturally invalidates the
    cached response. Cache files are intentionally stored outside run
    artifacts and should be git-ignored.
    """

    def __init__(self, root: Path, enabled: bool = True, schema_version: str = CACHE_SCHEMA_VERSION) -> None:
        self.root = root
        self.enabled = enabled
        self.schema_version = str(schema_version or CACHE_SCHEMA_VERSION)
        self._hits = 0
        self._misses = 0

    @staticmethod
    def build_key(
        *,
        provider: str,
        model: str,
        system: str,
        prompt: str,
        temperature: float,
        thinking_level: str = "",
        schema_version: str = CACHE_SCHEMA_VERSION,
    ) -> str:
        payload = {
            "provider": provider,
            "model": model,
            "system": system,
            "prompt": prompt,
            "temperature": temperature,
            "thinking_level": thinking_level,
            "cache_schema_version": str(schema_version or CACHE_SCHEMA_VERSION),
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> str | None:
        if not self.enabled:
            return None
        path = self._path(key)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            value = data.get("response")
            if isinstance(value, str) and value.strip():
                self._hits += 1
                return value
            self._misses += 1
            return None
        except (OSError, ValueError, TypeError):
            self._misses += 1
            return None

    def put(self, key: str, response: str) -> None:
        if not self.enabled or not response.strip():
            return
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {"response": response}
        fd, temporary_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def delete(self, key: str) -> None:
        """Delete one cache entry, used when a persisted response is malformed."""
        if not self.enabled:
            return
        path = self._path(key)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    def stats(self) -> dict[str, int | bool]:
        total = self._hits + self._misses
        return {
            "enabled": self.enabled,
            "hits": self._hits,
            "misses": self._misses,
            "requests": total,
            "hit_rate": round(self._hits / total, 4) if total else 0.0,
            "schema_version": self.schema_version,
        }

    def clear_stats(self) -> None:
        self._hits = 0
        self._misses = 0

    def clear(self) -> None:
        if self.root.exists():
            for path in sorted(self.root.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
