"""Compatibility imports for the canonical resource-pack production pipeline.

Older integrations imported ``youtube_pipeline.resource_pipeline`` directly.
Keep that import path, but never keep a second implementation: all callers now
receive the same UI/API production stages from ``resource_pack.pipeline``.
"""

from .resource_pack.pipeline import MINIMAX_PROFILE, RESOURCE_PACK_REQUIRED, ResourcePackPipeline, resource_pack_stages

__all__ = [
    "MINIMAX_PROFILE",
    "RESOURCE_PACK_REQUIRED",
    "ResourcePackPipeline",
    "resource_pack_stages",
]
