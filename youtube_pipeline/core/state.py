from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ArtifactRef:
    artifact_id: str
    artifact_type: str
    path: str
    sha256: str
    producer_stage: str
    schema_version: int = 1
    content_type: str = "application/json"
    size_bytes: int = 0
    qa_status: str = "passed"
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ArtifactRef":
        return cls(
            artifact_id=str(data["artifact_id"]),
            artifact_type=str(data["artifact_type"]),
            path=str(data["path"]),
            sha256=str(data["sha256"]),
            producer_stage=str(data["producer_stage"]),
            schema_version=int(data.get("schema_version", 1)),
            content_type=str(data.get("content_type", "application/json")),
            size_bytes=int(data.get("size_bytes", 0)),
            qa_status=str(data.get("qa_status", "passed")),
            metadata=dict(data.get("metadata", {})),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class StageRecord:
    stage_name: str
    stage_version: str
    status: str = "pending"
    attempts: int = 0
    input_fingerprint: str = ""
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    artifacts: list = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    error: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StageRecord":
        return cls(
            stage_name=str(data["stage_name"]),
            stage_version=str(data.get("stage_version", "1")),
            status=str(data.get("status", "pending")),
            attempts=int(data.get("attempts", 0)),
            input_fingerprint=str(data.get("input_fingerprint", "")),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            artifacts=list(data.get("artifacts", [])),
            metrics=dict(data.get("metrics", {})),
            warnings=list(data.get("warnings", [])),
            error=data.get("error"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RunState:
    run_id: str
    profile: str
    topic: str
    schema_version: int = 2
    status: str = "pending"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    execution_started_at: Optional[str] = None
    execution_finished_at: Optional[str] = None
    execution_elapsed_seconds: Optional[float] = None
    total_started_at: Optional[str] = None
    total_finished_at: Optional[str] = None
    total_elapsed_seconds: Optional[float] = None
    config_snapshot: Dict[str, Any] = field(default_factory=dict)
    input_artifacts: Dict[str, str] = field(default_factory=dict)
    stage_records: Dict[str, StageRecord] = field(default_factory=dict)
    artifact_index: Dict[str, ArtifactRef] = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    def artifact(self, artifact_type: str) -> ArtifactRef:
        try:
            return self.artifact_index[artifact_type]
        except KeyError as exc:
            raise KeyError("Missing artifact: %s" % artifact_type) from exc

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "profile": self.profile,
            "topic": self.topic,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "execution_started_at": self.execution_started_at,
            "execution_finished_at": self.execution_finished_at,
            "execution_elapsed_seconds": self.execution_elapsed_seconds,
            "total_started_at": self.total_started_at,
            "total_finished_at": self.total_finished_at,
            "total_elapsed_seconds": self.total_elapsed_seconds,
            "config_snapshot": dict(self.config_snapshot),
            "input_artifacts": dict(self.input_artifacts),
            "stage_records": {
                name: record.to_dict() for name, record in self.stage_records.items()
            },
            "artifact_index": {
                name: artifact.to_dict()
                for name, artifact in self.artifact_index.items()
            },
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RunState":
        if int(data.get("schema_version", 0)) != 2:
            raise ValueError("Unsupported resource-pack state schema version.")
        return cls(
            schema_version=2,
            run_id=str(data["run_id"]),
            profile=str(data["profile"]),
            topic=str(data["topic"]),
            status=str(data.get("status", "pending")),
            created_at=str(data.get("created_at", utc_now())),
            updated_at=str(data.get("updated_at", utc_now())),
            execution_started_at=data.get("execution_started_at"),
            execution_finished_at=data.get("execution_finished_at"),
            execution_elapsed_seconds=(float(data["execution_elapsed_seconds"]) if data.get("execution_elapsed_seconds") is not None else None),
            total_started_at=data.get("total_started_at") or data.get("created_at"),
            total_finished_at=data.get("total_finished_at"),
            total_elapsed_seconds=(float(data["total_elapsed_seconds"]) if data.get("total_elapsed_seconds") is not None else None),
            config_snapshot=dict(data.get("config_snapshot", {})),
            input_artifacts=dict(data.get("input_artifacts", {})),
            stage_records={
                name: StageRecord.from_dict(value)
                for name, value in dict(data.get("stage_records", {})).items()
            },
            artifact_index={
                name: ArtifactRef.from_dict(value)
                for name, value in dict(data.get("artifact_index", {})).items()
            },
            warnings=list(data.get("warnings", [])),
            errors=list(data.get("errors", [])),
        )
