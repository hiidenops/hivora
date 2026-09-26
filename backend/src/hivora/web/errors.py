"""Maps domain errors to HTTP responses with a stable, translatable ``code``."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from hivora.auth.ratelimit import TooManyAttemptsError
from hivora.auth.service import AuthError
from hivora.core.errors import (
    ConflictError,
    HivoraError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from hivora.docker_gateway import DockerUnavailableError
from hivora.games.engine import GameCommandError
from hivora.games.modpacks import ModpackSourceError

logger = logging.getLogger(__name__)

_STATUS: tuple[tuple[type[HivoraError], int], ...] = (
    (AuthError, 401),
    (PermissionDeniedError, 403),
    (NotFoundError, 404),
    (ConflictError, 409),
    (ValidationError, 422),
    (TooManyAttemptsError, 429),
    (DockerUnavailableError, 503),
    (ModpackSourceError, 502),
    (GameCommandError, 502),
)


def error_body(
    code: str, message: str, details: dict[str, object] | None = None
) -> dict[str, object]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def status_for(exc: HivoraError) -> int:
    return next((status for cls, status in _STATUS if isinstance(exc, cls)), 500)


def install(app: FastAPI) -> None:
    @app.exception_handler(HivoraError)
    async def hivora_error(_: Request, exc: HivoraError) -> JSONResponse:
        status = status_for(exc)
        if status == 500:
            logger.error("unhandled domain error", exc_info=exc)
        headers = {}
        if isinstance(exc, TooManyAttemptsError):
            headers["Retry-After"] = str(exc.details.get("retry_after", 1))
        return JSONResponse(error_body(exc.code, str(exc), exc.details), status, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def request_invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = {".".join(str(p) for p in e["loc"][1:]): e["type"] for e in exc.errors()}
        return JSONResponse(
            error_body("request_invalid", "invalid request", {"fields": fields}), 422
        )
