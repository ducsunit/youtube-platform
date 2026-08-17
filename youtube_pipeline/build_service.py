"""Backward-compatible facade for :mod:`youtube_pipeline.video.service`.

New code should import from ``youtube_pipeline.video.service``. This facade keeps
legacy monkey-patching behavior used by the API/test suite while migration is in
progress.
"""
from .video import service as _service
from .video.service import *
from .video.service import _img_order_for_import


def import_images(*args, **kwargs):
    patched_order = globals().get("_img_order_for_import", _service._img_order_for_import)
    original_order = _service._img_order_for_import
    _service._img_order_for_import = patched_order
    try:
        return _service.import_images(*args, **kwargs)
    finally:
        _service._img_order_for_import = original_order


if __name__ == '__main__':
    from .video.service import main
    raise SystemExit(main())
