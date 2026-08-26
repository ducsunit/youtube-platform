"""Per-channel identity profiles for multi-channel production.

Historically five editorial-identity blocks were hard-coded in Python for the
single Japanese Jungian-psychology channel:

  - competitor context block (injected into topic/review/thumbnail prompts)
  - approved source catalog (the claim-safety boundary)
  - claim policy: known named frameworks + their source aliases
  - visual style locks (character bible, thumbnail composition/typography)
  - packaging rules referenced by prompts

This module lets each channel override those blocks through
``config/channels/<channel_id>/profile.json`` while every field falls back to
the built-in defaults when absent, so existing single-channel behavior is
byte-for-byte unchanged.

Resolution order for a run: explicit ``--channel`` argument > auto-detection
from the input dataset (folder name or ``youtube_channel_ids`` mapping) >
built-in defaults.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROFILE_RELATIVE_DIR = Path("config/channels")

# Populated by activate(); {} means built-in defaults everywhere.
_ACTIVE_BLOCK: dict[str, Any] = {}


class ChannelProfileError(ValueError):
    """Raised for malformed channel profiles; deterministic, never retried."""


def _project_root(path: Path) -> Path:
    """Accept a run directory (runs/<id>) or the project root itself."""
    root = Path(path)
    if root.name and root.parent.name == "runs":
        root = root.parent.parent
    return root


def profile_path(project_root: Path, channel_id: str) -> Path:
    return _project_root(project_root) / PROFILE_RELATIVE_DIR / channel_id / "profile.json"


def load_channel_profile(project_root: Path, channel_id: str) -> dict[str, Any]:
    """Load and validate one profile file. Raises ChannelProfileError khi hỏng."""
    path = profile_path(project_root, channel_id)
    if not path.is_file():
        raise ChannelProfileError("Không tìm thấy channel profile: %s" % path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ChannelProfileError("Channel profile %s không phải JSON hợp lệ: %s" % (path, exc)) from exc
    if not isinstance(data, dict) or not data:
        raise ChannelProfileError("Channel profile %s phải là JSON object khác rỗng." % path)
    unknown_top = set(data) - {
        "schema_version", "channel_id", "display_name", "language",
        "youtube_channel_ids", "competitor", "sources", "claims", "style_locks",
        "packaging",
        # TTS voice binding per channel (VOICEVOX speaker + delivery params).
        "tts",
        # Multi-user forward-compatibility: stored now, enforced later when the
        # platform grows per-user workspaces.
        "owner", "users",
    }
    if unknown_top:
        raise ChannelProfileError(
            "Channel profile %s có field không hỗ trợ: %s" % (path, ", ".join(sorted(unknown_top)))
        )
    competitor = data.get("competitor") or {}
    if not isinstance(competitor, dict):
        raise ChannelProfileError("Channel profile %s: 'competitor' phải là object." % path)
    for key, expected in (
        ("patterns", str), ("writing_dna", str),
    ):
        if key in competitor and not isinstance(competitor[key], expected):
            raise ChannelProfileError(
                "Channel profile %s: competitor.%s phải là string." % (path, key)
            )
    sources = data.get("sources") or {}
    if not isinstance(sources, dict):
        raise ChannelProfileError("Channel profile %s: 'sources' phải là object." % path)
    catalog = sources.get("approved_catalog")
    if catalog is not None:
        if not isinstance(catalog, list) or not catalog or not all(
            isinstance(row, dict) and row.get("title") and row.get("url") for row in catalog
        ):
            raise ChannelProfileError(
                "Channel profile %s: sources.approved_catalog phải là list các object "
                "có ít nhất 'title' và 'url'." % path
            )
    claims = data.get("claims") or {}
    if not isinstance(claims, dict):
        raise ChannelProfileError("Channel profile %s: 'claims' phải là object." % path)
    tts = data.get("tts")
    if tts is not None:
        allowed_tts = {"speaker", "speed_scale", "pitch_scale", "intonation_scale"}
        if not isinstance(tts, dict) or set(tts) - allowed_tts:
            bad = sorted(set(tts) - allowed_tts) if isinstance(tts, dict) else "?"
            raise ChannelProfileError(
                "Channel profile %s: tts chứa field không hỗ trợ: %s" % (path, ", ".join(map(str, bad)))
            )
    style_locks = data.get("style_locks") or {}
    allowed_locks = {
        "CHARACTER_BIBLE", "CHARACTER_STYLE_LOCK",
        "THUMBNAIL_COMPOSITION_LOCK", "THUMBNAIL_TYPOGRAPHY_LOCK",
        "text_color", "accent_color", "background_color",
    }
    if not isinstance(style_locks, dict) or set(style_locks) - allowed_locks:
        bad = sorted(set(style_locks) - allowed_locks) if isinstance(style_locks, dict) else "?"
        raise ChannelProfileError(
            "Channel profile %s: style_locks chứa field không hỗ trợ: %s" % (path, ", ".join(bad))
        )
    return data


def detect_channel_id(project_root: Path, raw_data: str | None) -> str | None:
    """Map an input dataset's channel identity onto a configured profile."""
    if not raw_data:
        return None
    try:
        payload = json.loads(raw_data)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    candidates: set[str] = set()
    for key in ("channel_id", "channel"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            candidates.add(value.strip())
    nested = payload.get("channel")
    if isinstance(nested, dict):
        for key in ("id", "channel_id"):
            value = nested.get(key)
            if isinstance(value, str) and value.strip():
                candidates.add(value.strip())
    if not candidates:
        return None
    root = _project_root(project_root)
    base = root / PROFILE_RELATIVE_DIR
    if not base.is_dir():
        return None
    for folder in sorted(base.iterdir()):
        path = folder / "profile.json"
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        mapped = set(data.get("youtube_channel_ids") or [])
        mapped.add(folder.name)
        if candidates & mapped:
            return folder.name
    return None


def resolve_channel_id(
    project_root: Path,
    explicit: str | None,
    raw_data: str | None,
) -> tuple[str | None, dict[str, Any] | None]:
    """Explicit argument > auto-detect > (None, None) meaning built-in defaults."""
    if explicit:
        try:
            profile = load_channel_profile(project_root, explicit)
        except ChannelProfileError as exc:
            logger.warning(
                "--channel=%s chưa có hoặc không đọc được profile (%s) — dùng built-in defaults.",
                explicit, exc,
            )
            return explicit, None
        return explicit, profile
    detected = detect_channel_id(project_root, raw_data)
    if detected:
        return detected, load_channel_profile(project_root, detected)
    return None, None


def build_config_block(
    channel_id: str | None,
    profile: dict[str, Any] | None,
) -> dict[str, Any]:
    """Flatten a profile into the compact block stored in RunState.config_snapshot.

    The block travels inside stage fingerprints, so switching channels must
    invalidate cached stages automatically. Override payloads (catalog rows,
    style-lock strings) are kept inside the block so a resumed run can
    re-activate without reading the profile file again.
    """
    from .competitor_context import competitor_inject_text

    block: dict[str, Any] = {
        "channel_id": channel_id or (profile or {}).get("channel_id"),
        "competitor_block": competitor_inject_text(),
    }
    if not profile:
        return block
    competitor = profile.get("competitor") or {}
    if competitor.get("patterns") or competitor.get("writing_dna"):
        patterns = str(competitor.get("patterns") or "").rstrip()
        dna = str(competitor.get("writing_dna") or "").rstrip()
        parts = [part for part in (patterns, dna) if part]
        header = "## Competitor profile (%s)" % (profile.get("display_name") or block["channel_id"] or "custom")
        updated = competitor.get("last_updated")
        if updated:
            header += " — updated %s" % updated
        block["competitor_block"] = header + "\n\n" + "\n\n".join(parts)
    claims = profile.get("claims") or {}
    if claims.get("known_named_frameworks") is not None:
        block["known_named_frameworks"] = list(claims["known_named_frameworks"])
    if claims.get("framework_source_aliases") is not None:
        block["framework_source_aliases"] = dict(claims["framework_source_aliases"])
    catalog = (profile.get("sources") or {}).get("approved_catalog")
    if catalog:
        block["_approved_catalog"] = catalog
    style_locks = profile.get("style_locks") or {}
    if style_locks:
        block["_style_locks"] = dict(style_locks)
    # TTS settings phải đi cùng snapshot: tts_job + stage tts_generate đọc từ
    # đây — thiếu là run rơi về mặc định (speed 1.0) thay vì config kênh.
    if profile.get("tts"):
        block["tts"] = dict(profile["tts"])
    return block


def activate(block: dict[str, Any] | None) -> None:
    """Apply a config block's overrides to the prompt/catalog modules.

    Called once per run (create_state for new runs, run() for resumes). Safe
    to call repeatedly; :func:`reset` restores the built-in defaults.
    """
    global _ACTIVE_BLOCK
    _ACTIVE_BLOCK = dict(block or {})
    style_locks = _ACTIVE_BLOCK.get("_style_locks") or {}
    from .resource_pack import prompts as _pack_prompts
    from .resource_pack import source_catalog as _catalog

    if style_locks:
        for attr, value in style_locks.items():
            if attr.startswith(("CHARACTER", "THUMBNAIL")) and hasattr(_pack_prompts, attr):
                setattr(_pack_prompts, attr, str(value))
        colors = {
            key: value for key, value in style_locks.items()
            if key in ("text_color", "accent_color", "background_color")
        }
        if colors:
            _ACTIVE_BLOCK["colors"] = colors
    else:
        _prompts_restore_defaults()

    catalog_rows = _ACTIVE_BLOCK.get("_approved_catalog")
    if catalog_rows is not None:
        _catalog.apply_source_catalog(catalog_rows)
    else:
        _catalog.reset_source_catalog()


def reset() -> None:
    """Restore built-in defaults; used by tests between cases."""
    activate(None)


def active_block() -> dict[str, Any]:
    return dict(_ACTIVE_BLOCK)


def active_competitor_block() -> str | None:
    return _ACTIVE_BLOCK.get("competitor_block")


def active_claim_policy() -> tuple[list[str] | None, dict[str, tuple[str, ...]] | None]:
    return _ACTIVE_BLOCK.get("known_named_frameworks"), _ACTIVE_BLOCK.get("framework_source_aliases")


def active_style_colors() -> dict[str, str]:
    """Thumbnail palette overrides applied by the active profile (may be empty)."""
    colors = _ACTIVE_BLOCK.get("colors") or {}
    return {key: str(value) for key, value in colors.items() if isinstance(value, str) and value}


# --- internal helpers -------------------------------------------------------

_ORIGINAL_PROMPT_LOCKS: dict[str, str] | None = None


def _capture_prompt_lock_defaults() -> dict[str, str]:
    global _ORIGINAL_PROMPT_LOCKS
    if _ORIGINAL_PROMPT_LOCKS is None:
        from .resource_pack import prompts as _pack_prompts
        _ORIGINAL_PROMPT_LOCKS = {
            attr: getattr(_pack_prompts, attr)
            for attr in (
                "CHARACTER_BIBLE", "CHARACTER_STYLE_LOCK",
                "THUMBNAIL_COMPOSITION_LOCK", "THUMBNAIL_TYPOGRAPHY_LOCK",
            )
        }
    return dict(_ORIGINAL_PROMPT_LOCKS)


def _prompts_restore_defaults() -> None:
    defaults = _capture_prompt_lock_defaults()
    if not defaults:
        return
    from .resource_pack import prompts as _pack_prompts
    for attr, value in defaults.items():
        setattr(_pack_prompts, attr, value)
