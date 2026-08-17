"""Import-friendly alias for the canonical build-video engine.

The executable implementation remains in ``build-video.py`` for compatibility
with the existing subprocess contract.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_PATH = Path(__file__).with_name("build-video.py")
_SPEC = importlib.util.spec_from_file_location("youtube_pipeline.video._build_video_engine", _PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Cannot load video engine: {_PATH}")
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

for _name in dir(_MODULE):
    if _name.startswith("__"):
        continue
    globals()[_name] = getattr(_MODULE, _name)
