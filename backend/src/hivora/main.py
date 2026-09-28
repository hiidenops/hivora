"""ASGI entrypoint: builds the FastAPI application."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from hivora import __version__
from hivora.apps.api import router as apps_router
from hivora.audit.api import router as audit_router
from hivora.auth.api import router as auth_router
from hivora.auth.users_api import router as users_router
from hivora.backups.api import router as backups_router
from hivora.core.config import Settings
from hivora.core.logging import configure_logging
from hivora.games.api import game_router, options_router
from hivora.games.api import router as modpacks_router
from hivora.jobs.api import router as jobs_router
from hivora.metrics.api import router as metrics_router
from hivora.realtime.logs import router as logs_router
from hivora.realtime.ws import router as ws_router
from hivora.runtime import Runtime
from hivora.system.api import router as system_router
from hivora.templates.api import router as templates_router
from hivora.vpn.api import router as vpn_router
from hivora.web import errors
from hivora.zones.api import router as zones_router

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None, runtime: Runtime | None = None) -> FastAPI:
    """``runtime`` is injected by tests (fake Docker); otherwise built from settings."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        rt = runtime or Runtime.build(settings or Settings())
        configure_logging(rt.settings.log_level, rt.settings.log_format)
        app.state.runtime = rt
        await rt.start()
        if rt.settings.frontend_dir.is_dir():
            app.mount("/", StaticFiles(directory=rt.settings.frontend_dir, html=True), "ui")
        try:
            yield
        finally:
            await rt.stop()

    app = FastAPI(
        title="Hivora",
        version=__version__,
        lifespan=lifespan,
        docs_url=f"{API_PREFIX}/docs",
        openapi_url=f"{API_PREFIX}/openapi.json",
    )
    errors.install(app)
    for prefix, router in (
        ("/system", system_router), ("/auth", auth_router), ("/users", users_router),
        ("/templates", templates_router), ("/apps", apps_router), ("/zones", zones_router),
        ("/jobs", jobs_router), ("/audit", audit_router), ("/metrics", metrics_router),
        ("/modpacks", modpacks_router),
    ):  # fmt: skip
        app.include_router(router, prefix=f"{API_PREFIX}{prefix}")
    app.include_router(game_router, prefix=f"{API_PREFIX}/apps")
    app.include_router(vpn_router, prefix=f"{API_PREFIX}/apps")
    app.include_router(logs_router, prefix=f"{API_PREFIX}/apps")
    app.include_router(backups_router, prefix=f"{API_PREFIX}/apps")
    app.include_router(options_router, prefix=f"{API_PREFIX}/options")
    app.include_router(ws_router)
    return app


def app() -> FastAPI:
    """Factory for ``uvicorn --factory hivora.main:app``."""
    return create_app()
