"""Configurable API authentication and request scope enforcement."""
from __future__ import annotations

import hmac
import json
import os
from dataclasses import dataclass
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


@dataclass(frozen=True)
class AuthSettings:
    required: bool
    tokens: dict[str, str]
    trusted_header: str | None
    allow_query_token: bool

    @classmethod
    def from_env(cls) -> "AuthSettings":
        required = _truthy(os.getenv("YT_API_REQUIRE_AUTH")) or os.getenv("YT_API_ENV", "").lower() == "production"
        tokens: dict[str, str] = {}
        for item in os.getenv("YT_API_TOKENS", "").split(","):
            if "=" in item:
                token, user = item.split("=", 1)
                if token.strip() and user.strip():
                    tokens[token.strip()] = user.strip()
        token = os.getenv("YT_API_AUTH_TOKEN", "").strip()
        user = os.getenv("YT_API_AUTH_USER", "").strip()
        if token and user:
            tokens[token] = user
        trusted_header = os.getenv("YT_API_TRUSTED_USER_HEADER", "").strip() or None
        return cls(required=required, tokens=tokens, trusted_header=trusted_header,
                   allow_query_token=_truthy(os.getenv("YT_API_ALLOW_QUERY_TOKEN")))


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _json_error(status: int, detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status)


def _body_user(payload: Any) -> str | None:
    return payload.get("user_id") if isinstance(payload, dict) and isinstance(payload.get("user_id"), str) else None


def requires_channel_scope(path: str) -> bool:
    """Return whether a production request must select a channel namespace."""
    if path in {"/api/config", "/api/runs", "/api/channels"}:
        return path != "/api/channels"
    return path.startswith(("/api/data", "/api/build", "/api/images", "/api/veo", "/api/srt", "/api/runs/"))


class ApiAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: AuthSettings | None = None):
        super().__init__(app)
        self.settings = settings or AuthSettings.from_env()

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if not self.settings.required or request.method == "OPTIONS" or path == "/api/health":
            return await call_next(request)
        if not path.startswith("/api"):
            return await call_next(request)
        if path == "/api/platform/reindex":
            return _json_error(403, "Unscoped platform reindex is disabled when authentication is enabled")

        principal: str | None = None
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            supplied = auth[7:].strip()
            for configured, mapped_user in self.settings.tokens.items():
                if hmac.compare_digest(supplied, configured):
                    principal = mapped_user
                    break
        if principal is None and self.settings.trusted_header:
            principal = request.headers.get(self.settings.trusted_header) or None
        if principal is None and self.settings.allow_query_token:
            supplied = request.query_params.get("api_token", "")
            for configured, mapped_user in self.settings.tokens.items():
                if hmac.compare_digest(supplied, configured):
                    principal = mapped_user
                    break
        if not principal:
            return _json_error(401, "Authentication required")
        if not self.settings.tokens and not self.settings.trusted_header:
            return _json_error(503, "Authentication is enabled but no credential mapping is configured")

        body_payload: Any = None
        raw = b""
        if request.method in {"POST", "PUT", "PATCH"}:
            raw = await request.body()
            if raw:
                try:
                    body_payload = json.loads(raw)
                except (TypeError, ValueError):
                    body_payload = None

        requested_user = request.query_params.get("user_id") or _body_user(body_payload)
        if requested_user is not None and requested_user != principal:
            return _json_error(403, "Authenticated user does not own the requested namespace")

        # Preserve compatibility with handlers while making identity server-derived.
        if requested_user is None:
            from starlette.datastructures import QueryParams
            params = list(request.query_params.multi_items())
            params.append(("user_id", principal))
            request._query_params = QueryParams(params)
            if isinstance(body_payload, dict):
                body_payload["user_id"] = principal
                raw = json.dumps(body_payload).encode("utf-8")

        if request.method in {"POST", "PUT", "PATCH"}:
            async def receive():
                return {"type": "http.request", "body": raw, "more_body": False}
            request._receive = receive

        if requires_channel_scope(path):
            channel_id = request.query_params.get("channel_id") or (body_payload.get("channel_id") if isinstance(body_payload, dict) else None)
            if not isinstance(channel_id, str) or not channel_id:
                return _json_error(400, "user_id and channel_id are required in production")
        request.state.authenticated_user = principal
        return await call_next(request)
