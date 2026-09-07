"""Shared topic history used to keep production runs from repeating a topic."""
from __future__ import annotations

import difflib
import json
import re
import tempfile
from pathlib import Path
from typing import Any


HISTORY_RELATIVE_PATH = Path("data/topic-history.json")


def history_path(project_root: Path) -> Path:
    root = Path(project_root)
    # Pipeline artifacts live in <project>/runs/<run_id>. Accept either that
    # run directory or the project root so callers cannot create per-run logs.
    if root.name and root.parent.name == "runs":
        root = root.parent.parent
    return root / HISTORY_RELATIVE_PATH


def _text(value: Any) -> str:
    return re.sub(r"[^0-9a-zA-Zぁ-んァ-ン一-龯]+", "", str(value or "")).lower()


def load_history(
    project_root: Path,
    *,
    user_id: str | None = None,
    channel_id: str | None = None,
) -> list[dict[str, Any]]:
    if bool(user_id) != bool(channel_id):
        raise ValueError("user_id và channel_id phải được truyền cùng nhau")
    path = history_path(project_root)
    root = path.parent.parent
    payload = {}
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = {}
    rows = [
        {**row, "status": "published" if row.get("status") == "completed" else row.get("status", "drafted")}
        for row in (payload.get("topics", []) if isinstance(payload, dict) else [])
        if isinstance(row, dict)
    ]
    if user_id and channel_id:
        rows = [
            row for row in rows
            if row.get("user_id") == user_id and row.get("channel_id") == channel_id
        ]
    # SQLite is the platform index; the JSON catalog remains portable fallback.
    # Merge both so an existing JSON history stays effective until reindexed.
    database_path = _database_path(root)
    if database_path.is_file():
        from .platform_db import PlatformDatabase
        indexed = PlatformDatabase(database_path).completed_topics(user_id=user_id, channel_id=channel_id)
        indexed = [
            {**row, "status": "published" if row.get("status") == "completed" else row.get("status", "drafted")}
            for row in indexed
        ]
        by_run_id = {str(row.get("run_id")): row for row in rows}
        by_run_id.update({str(row.get("run_id")): row for row in indexed})
        rows = list(by_run_id.values())
        if user_id and channel_id:
            rows = [row for row in rows if row.get("user_id", user_id) == user_id and row.get("channel_id", channel_id) == channel_id]
        else:
            rows = list(rows)
    known = {str(row.get("run_id")) for row in rows}
    # One-time-compatible migration: old completed runs predate the shared
    # catalog, so discover their selected-topic artifacts lazily.
    runs_dir = root / "runs"
    if runs_dir.is_dir():
        for run_dir in runs_dir.iterdir():
            state_path = run_dir / "run_state.json"
            selection_path = run_dir / "research/topic-selection.json"
            if not run_dir.is_dir() or not state_path.is_file() or not selection_path.is_file() or run_dir.name in known:
                continue
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
                selected = json.loads(selection_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if state.get("status") != "complete" or not isinstance(selected, dict):
                continue
            if user_id and channel_id and (
                state.get("user_id") != user_id or state.get("channel_id") != channel_id
            ):
                continue
            contract_path = run_dir / "script/contract.json"
            contract = {}
            try:
                if contract_path.is_file():
                    contract = json.loads(contract_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
            rows.append({**selected, "run_id": run_dir.name, "status": "drafted", "chosen_title": contract.get("chosen_title", "")})
    return rows


def _identity(value: dict[str, Any]) -> str:
    return "|".join(_text(value.get(key)) for key in (
        "topic", "selected_topic", "behavior", "audience_moment", "core_pain", "angle",
        "promise", "source_concept",
    ))


def duplicate_reason(candidate: dict[str, Any], history: list[dict[str, Any]]) -> str | None:
    candidate_id = _identity(candidate)
    if not candidate_id:
        return None
    for previous in history:
        previous_id = _identity(previous)
        if not previous_id:
            continue
        if candidate_id == previous_id:
            return "same_topic_fingerprint"
        topic = _text(candidate.get("topic") or candidate.get("selected_topic"))
        old_topic = _text(previous.get("topic") or previous.get("selected_topic"))
        if topic and old_topic and (topic in old_topic or old_topic in topic):
            return "topic_name_overlap"
        similarity = difflib.SequenceMatcher(None, candidate_id, previous_id).ratio()
        concepts_match = _text(candidate.get("source_concept")) == _text(previous.get("source_concept"))
        moments_match = _text(candidate.get("audience_moment")) == _text(previous.get("audience_moment"))
        if similarity >= 0.86 or (concepts_match and moments_match and similarity >= 0.62):
            return "near_duplicate_topic"
    return None


def annotate_candidates(payload: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    """Attach non-authoritative history metadata for the selector prompt."""
    result = dict(payload)
    rows = []
    for row in payload.get("candidates", []):
        item = dict(row)
        reason = duplicate_reason(item, history)
        if reason:
            previous = next((entry for entry in history if duplicate_reason(item, [entry])), {})
            item["history_status"] = previous.get("status", "drafted")
            item["history_reason"] = reason
        rows.append(item)
    result["candidates"] = rows
    result["topic_history"] = [
        {key: row.get(key) for key in ("run_id", "topic", "selected_topic", "source_concept", "angle", "status")}
        for row in history[-30:]
    ]
    result["topic_history_count"] = len(history)
    return result


def record_drafted(
    project_root: Path,
    run_id: str,
    selected: dict[str, Any],
    brief: dict[str, Any] | None = None,
    *,
    user_id: str | None = None,
    channel_id: str | None = None,
) -> None:
    rows = load_history(project_root, user_id=user_id, channel_id=channel_id)
    if user_id and channel_id:
        selected = {**selected, "user_id": user_id, "channel_id": channel_id}
    path = history_path(project_root)
    entry = {
        "run_id": run_id,
        "user_id": user_id,
        "channel_id": channel_id,
        "status": "drafted",
        "topic": selected.get("selected_topic", ""),
        "selected_topic": selected.get("selected_topic", ""),
        "title": selected.get("chosen_title", ""),
        "source_concept": selected.get("source_concept", ""),
        "source_work": selected.get("source_work", ""),
        "audience_moment": selected.get("audience_moment", ""),
        "promise": selected.get("promise", ""),
        "angle": selected.get("angle", ""),
        "mechanisms": [item.get("name", item) if isinstance(item, dict) else item for item in (brief or {}).get("selected_mechanisms", [])],
    }
    rows = [row for row in rows if row.get("run_id") != run_id]
    rows.append(entry)
    from .platform_db import PlatformDatabase
    run_root = history_path(project_root).parent.parent / "runs" / run_id
    database_path = PlatformDatabase.path_for_run_root(run_root)
    # Legacy callers may record a portable topic before a run has been indexed.
    # Preserve the JSON catalog; the reindex endpoint later restores its DB row.
    if database_path.is_file():
        database = PlatformDatabase(database_path)
        if database.has_run(run_id, user_id=user_id, channel_id=channel_id):
            database.record_completed_topic(run_id, entry, user_id=user_id, channel_id=channel_id)
    path = history_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (json.dumps({"schema_version": 1, "topics": rows}, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.replace(path)


def record_completed(
    project_root: Path,
    run_id: str,
    selected: dict[str, Any],
    brief: dict[str, Any] | None = None,
    *,
    user_id: str | None = None,
    channel_id: str | None = None,
) -> None:
    """Backward-compatible name; a generated resource pack is a draft, not published."""
    record_drafted(
        project_root,
        run_id,
        selected,
        brief,
        user_id=user_id,
        channel_id=channel_id,
    )


def set_topic_status(
    project_root: Path,
    run_id: str,
    status: str,
    *,
    user_id: str | None = None,
    channel_id: str | None = None,
) -> None:
    if bool(user_id) != bool(channel_id):
        raise ValueError("user_id và channel_id phải được truyền cùng nhau")
    if status not in {"drafted", "published", "archived"}:
        raise ValueError("Topic status không hợp lệ.")
    path = history_path(project_root)
    rows = load_history(project_root, user_id=user_id, channel_id=channel_id)
    found = False
    for row in rows:
        if str(row.get("run_id")) == run_id:
            row["status"] = status
            found = True
    if not found:
        raise ValueError("Không tìm thấy topic history cho run này.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 2, "topics": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    database_path = _database_path(path.parent.parent)
    if database_path.is_file():
        from .platform_db import PlatformDatabase
        PlatformDatabase(database_path).set_topic_status(
            run_id, status, user_id=user_id, channel_id=channel_id
        )


def _database_path(project_root: Path) -> Path:
    from .platform_db import PlatformDatabase
    return PlatformDatabase.path_for_run_root(project_root / "runs" / "topic-history")
