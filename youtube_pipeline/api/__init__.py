"""API server cho resource pack pipeline (chạy: python -m youtube_pipeline).

App FastAPI + CORS cho Vite dev. Tuỳ chọn serve luôn bản build frontend từ
`YT_SERVE_FRONTEND=<đường dẫn thư mục dist>` (mount StaticFiles tại / sau router).
"""
from __future__ import annotations

import argparse
import os
from typing import Optional, Sequence

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from .build_routes import router as build_router
from .data_routes import router as data_router
from .job_routes import router as job_router
from .routes import router
from .veo_routes import router as veo_router
from .image_routes import router as image_router
from .srt_routes import router as srt_router


class _SpaStaticFiles(StaticFiles):
    """StaticFiles + SPA fallback: đường dẫn không phải file → index.html.

    Để deep-link (refresh /runs/<id> khi serve bản build tĩnh) không bị 404.
    """

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code == 404 and self.html:
                return await super().get_response("index.html", scope)
            raise


def create_app() -> FastAPI:
    app = FastAPI(title="YouTube Platform API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    app.include_router(data_router)
    app.include_router(job_router)
    app.include_router(build_router)
    app.include_router(veo_router)
    app.include_router(image_router)
    app.include_router(srt_router)
    dist = os.environ.get("YT_SERVE_FRONTEND")
    if dist:
        app.mount("/", _SpaStaticFiles(directory=dist, html=True), name="frontend")
    return app


app = create_app()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="youtube-pipeline-ui",
        description="Web API cho resource pack pipeline.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Địa chỉ bind (mặc định 127.0.0.1).")
    parser.add_argument("--port", type=int, default=8787, help="Cổng (mặc định 8787).")
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Reload khi sửa code — KHÔNG dùng khi có pipeline đang chạy.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    import uvicorn

    if args.reload:
        # Import-string để uvicorn reload module lại được; reload giết tracker
        # proc trong bộ nhớ nhưng orphan path (pid file) vẫn hoạt động.
        uvicorn.run("youtube_pipeline.api:app", host=args.host, port=args.port, reload=True)
    else:
        uvicorn.run(app, host=args.host, port=args.port)
    return 0
