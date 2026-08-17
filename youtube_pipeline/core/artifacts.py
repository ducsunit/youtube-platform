from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .state import ArtifactRef, RunState, utc_now


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _ref(
        self,
        artifact_type: str,
        relative_path: str,
        producer_stage: str,
        content: bytes,
        content_type: str,
        metadata: dict | None = None,
    ) -> ArtifactRef:
        return ArtifactRef(
            artifact_id="%s:%s" % (producer_stage, artifact_type),
            artifact_type=artifact_type,
            path=relative_path,
            sha256=hashlib.sha256(content).hexdigest(),
            producer_stage=producer_stage,
            content_type=content_type,
            size_bytes=len(content),
            metadata=metadata or {},
        )

    def put_json(
        self,
        artifact_type: str,
        relative_path: str,
        value: Any,
        producer_stage: str,
        metadata: dict | None = None,
    ) -> ArtifactRef:
        content = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        _atomic_write(self.root / relative_path, content)
        return self._ref(
            artifact_type,
            relative_path,
            producer_stage,
            content,
            "application/json",
            metadata,
        )

    def put_text(
        self,
        artifact_type: str,
        relative_path: str,
        value: str,
        producer_stage: str,
        metadata: dict | None = None,
    ) -> ArtifactRef:
        content = value.encode("utf-8")
        _atomic_write(self.root / relative_path, content)
        return self._ref(
            artifact_type,
            relative_path,
            producer_stage,
            content,
            "text/plain; charset=utf-8",
            metadata,
        )

    def read_json(self, ref_or_type: ArtifactRef | str, state: RunState | None = None) -> Any:
        ref = self._resolve(ref_or_type, state)
        return json.loads((self.root / ref.path).read_text(encoding="utf-8"))

    def read_text(self, ref_or_type: ArtifactRef | str, state: RunState | None = None) -> str:
        ref = self._resolve(ref_or_type, state)
        return (self.root / ref.path).read_text(encoding="utf-8")

    @staticmethod
    def _resolve(ref_or_type: ArtifactRef | str, state: RunState | None) -> ArtifactRef:
        if isinstance(ref_or_type, ArtifactRef):
            return ref_or_type
        if state is None:
            raise ValueError("state is required when resolving by artifact type")
        return state.artifact(ref_or_type)

    def verify(self, ref: ArtifactRef) -> bool:
        path = self.root / ref.path
        if not path.exists():
            return False
        return hashlib.sha256(path.read_bytes()).hexdigest() == ref.sha256

    def save_state(self, state: RunState) -> None:
        state.updated_at = utc_now()
        content = (json.dumps(state.to_dict(), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        _atomic_write(self.root / "run_state.json", content)

    def load_state(self) -> RunState:
        data = json.loads((self.root / "run_state.json").read_text(encoding="utf-8"))
        return RunState.from_dict(data)
