"""Psychology-first resource production domain.

Canonical modules for the research -> psychology brief -> script -> QA ->
visual/resource pack pipeline. Legacy root imports remain as compatibility shims.
"""
from .pipeline import ResourcePackPipeline
from .providers import AIResourceProvider, DemoResourceProvider

__all__ = ["ResourcePackPipeline", "AIResourceProvider", "DemoResourceProvider"]
