"""CallOS AI backend — FastAPI application factory.

Run with:  uvicorn app.main:create_app --factory --port 8787
"""
from __future__ import annotations

import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import database
from app.api import actions, admin, health, sessions, voice
from app.config import Settings, get_settings, set_settings
from app.utils.logging import configure_logging, correlation_id_var, get_logger

log = get_logger("callos.http")

DESCRIPTION = """
**One phone call. AI for everyone. Actions when you need them.**

Backend for the CallOS voice agent. The voice platform (Bolna) handles the call,
speech and general conversation; this service owns sessions, authorization,
pending actions, approval, execution and the audit trail.

* Tool endpoints (`/api/voice/*`, `/api/actions/*`) need `Authorization: Bearer <tool key>`.
* Admin endpoints (`/api/admin/*`) need `X-Admin-Key`.
* All workspace integrations are **mock** (simulated) — see `execution_mode` in responses.
"""

_ERROR_CODES = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed",
                422: "validation_error"}


def _error(status_code: int, code: str, message: str, details=None, headers=None) -> JSONResponse:
    return JSONResponse(status_code=status_code, headers=headers, content={
        "ok": False, "status": "error",
        "error": {"code": code, "message": message, "details": details},
        "speech": "Sorry, I ran into a technical problem. Please try again.",
        "correlation_id": correlation_id_var.get(),
    })


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is not None:
        set_settings(settings)
    settings = get_settings()
    configure_logging(settings.log_level)
    settings.validate_for_environment()

    database.init_engine(settings.sqlalchemy_url)
    database.create_all()
    if settings.seed_demo_data:
        from app.seed.demo_data import seed_if_empty

        with database.new_session() as db:
            seeded = seed_if_empty(db, settings)
        if seeded:
            log.info("demo workspace seeded", extra={"seed": seeded})

    app = FastAPI(title="CallOS AI", version="0.1.0", description=DESCRIPTION)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_methods=["GET", "POST"],
                       allow_headers=["Authorization", "Content-Type", "X-Admin-Key", "X-Correlation-ID"],
                       expose_headers=["X-Correlation-ID", "X-Response-Time-Ms"])

    @app.middleware("http")
    async def correlation_and_timing(request: Request, call_next):
        incoming = request.headers.get("x-correlation-id", "")
        cid = incoming if 0 < len(incoming) <= 64 and incoming.isascii() and incoming.isprintable() \
            else uuid.uuid4().hex[:16]
        token = correlation_id_var.set(cid)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            elapsed = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Correlation-ID"] = cid
        response.headers["X-Response-Time-Ms"] = str(elapsed)
        if request.url.path not in ("/health", "/api/health"):
            log.info("http_request", extra={"method": request.method, "path": request.url.path,
                                            "status_code": response.status_code, "duration_ms": elapsed})
        correlation_id_var.reset(token)
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_request: Request, exc: StarletteHTTPException):
        code = _ERROR_CODES.get(exc.status_code, "error")
        return _error(exc.status_code, code, str(exc.detail), headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        details = [{"field": ".".join(str(p) for p in e["loc"]), "problem": e["msg"]} for e in exc.errors()]
        return _error(422, "validation_error", "The request body is not valid", details)

    @app.exception_handler(Exception)
    async def unhandled(_request: Request, exc: Exception):
        log.exception("unhandled error")
        return _error(500, "internal_error", "Internal server error")

    app.include_router(health.router)
    app.include_router(voice.router)
    app.include_router(actions.router)
    app.include_router(sessions.router)
    app.include_router(admin.router)
    app.include_router(admin.dev_router)
    return app
