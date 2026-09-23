"""ASGI entrypoint: builds the FastAPI application."""

from fastapi import FastAPI

from hivora import __version__
from hivora.system.api import router as system_router

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    app = FastAPI(
        title="Hivora",
        version=__version__,
        docs_url=f"{API_PREFIX}/docs",
        openapi_url=f"{API_PREFIX}/openapi.json",
    )
    app.include_router(system_router, prefix=f"{API_PREFIX}/system")
    return app


app = create_app()
