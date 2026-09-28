"""Catalog routes (/api/v1/templates)."""

import re
from typing import Any

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import BaseModel

from hivora.core.errors import NotFoundError
from hivora.runtime import Runtime
from hivora.templates.catalog import CatalogEntry, host_arch
from hivora.templates.compiler import AppContext, build_context
from hivora.templates.expressions import render
from hivora.templates.forms import FormValues
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
    arch: list[str]  # architectures the template runs on


class TemplateDetail(TemplateSummary):
    links: dict[str, str]
    requirements: dict[str, Any]
    form: dict[str, Any]
    services: list[str]
    manifest: str  # raw YAML, for the advanced mode
    default_zone: str | None  # zone slug the template suggests (pre-selected if it exists)


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
        arch=list(entry.template.requirements.arch),
    )


@router.get("")
async def list_templates(_: Viewer, rt: RuntimeDep) -> list[TemplateSummary]:
    return [summary(rt, e) for e in rt.catalog.entries()]


@router.get("/{slug}")
async def get_template(slug: str, _: Viewer, rt: RuntimeDep) -> TemplateDetail:
    entry = rt.catalog.get(slug)
    t = entry.template
    form = t.form.model_dump(by_alias=True, exclude_none=True)
    host = {"host": build_context(AppContext("", "", 0), rt.apps.host, FormValues(), [])["host"]}
    for f in (f for part in form.values() if isinstance(part, list) for f in part):
        d = f.get("default")
        # Host facts are known now: show them in the form (app.* stays for the backend).
        if isinstance(d, str) and set(re.findall(r"\{\{\s*(\w+)", d)) == {"host"}:
            f["default"] = render(d, host) or d
    return TemplateDetail(
        **summary(rt, entry).model_dump(), links=t.metadata.links,
        requirements=t.requirements.model_dump(exclude_none=True),
        form=form,
        services=list(t.services), manifest=entry.manifest, default_zone=t.defaults.zone,
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
