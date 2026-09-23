"""Catalog routes (/api/v1/templates)."""

from typing import Any

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import BaseModel

from hivora.core.errors import NotFoundError
from hivora.runtime import Runtime
from hivora.templates.catalog import CatalogEntry, host_arch
from hivora.templates.icons import MEDIA_TYPES
from hivora.templates.schema import Localized
from hivora.web.deps import RuntimeDep, Viewer

router = APIRouter(tags=["templates"])


class TemplateSummary(BaseModel):
    slug: str
    name: str
    version: str
    category: str
    tags: list[str]
    icon_url: str | None  # served by Hivora from its cache
    description: Localized
    compatible: bool  # supports this host's CPU architecture


class TemplateDetail(TemplateSummary):
    links: dict[str, str]
    requirements: dict[str, Any]
    form: dict[str, Any]
    services: list[str]
    manifest: str  # raw YAML, for the advanced mode


def icon_url(rt: Runtime, slug: str) -> str | None:
    return f"/api/v1/templates/{slug}/icon" if rt.icons.path(slug) else None


def summary(rt: Runtime, entry: CatalogEntry) -> TemplateSummary:
    m = entry.template.metadata
    return TemplateSummary(
        slug=m.slug,
        name=m.name,
        version=m.version,
        category=m.category,
        tags=m.tags,
        icon_url=icon_url(rt, m.slug),
        description=m.description,
        compatible=entry.supports(host_arch()),
    )


@router.get("")
async def list_templates(_: Viewer, rt: RuntimeDep) -> list[TemplateSummary]:
    return [summary(rt, e) for e in rt.catalog.entries()]


@router.get("/{slug}")
async def get_template(slug: str, _: Viewer, rt: RuntimeDep) -> TemplateDetail:
    entry = rt.catalog.get(slug)
    t = entry.template
    return TemplateDetail(
        **summary(rt, entry).model_dump(), links=t.metadata.links,
        requirements=t.requirements.model_dump(exclude_none=True),
        form=t.form.model_dump(by_alias=True, exclude_none=True),
        services=list(t.services), manifest=entry.manifest,
    )  # fmt: skip


@router.get("/{slug}/icon")
async def get_icon(slug: str, _: Viewer, rt: RuntimeDep) -> FileResponse:
    path = rt.icons.path(slug)
    if path is None:
        raise NotFoundError("no icon")
    return FileResponse(
        path,
        media_type=MEDIA_TYPES[path.suffix.lstrip(".")],
        headers={
            "Cache-Control": "private, max-age=86400",
            "X-Content-Type-Options": "nosniff",
            # Third-party SVG: never executable, even if opened directly.
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
        },
    )
