"""Catalog routes (/api/v1/templates)."""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from hivora.templates.catalog import CatalogEntry, host_arch
from hivora.templates.schema import Localized
from hivora.web.deps import RuntimeDep, Viewer

router = APIRouter(tags=["templates"])


class TemplateSummary(BaseModel):
    slug: str
    name: str
    version: str
    category: str
    tags: list[str]
    icon: str | None
    description: Localized
    compatible: bool  # supports this host's CPU architecture


class TemplateDetail(TemplateSummary):
    links: dict[str, str]
    requirements: dict[str, Any]
    form: dict[str, Any]
    services: list[str]
    manifest: str  # raw YAML, for the advanced mode


def summary(entry: CatalogEntry) -> TemplateSummary:
    m = entry.template.metadata
    return TemplateSummary(
        slug=m.slug,
        name=m.name,
        version=m.version,
        category=m.category,
        tags=m.tags,
        icon=m.icon,
        description=m.description,
        compatible=entry.supports(host_arch()),
    )


@router.get("")
async def list_templates(_: Viewer, rt: RuntimeDep) -> list[TemplateSummary]:
    return [summary(e) for e in rt.catalog.entries()]


@router.get("/{slug}")
async def get_template(slug: str, _: Viewer, rt: RuntimeDep) -> TemplateDetail:
    entry = rt.catalog.get(slug)
    t = entry.template
    return TemplateDetail(
        **summary(entry).model_dump(), links=t.metadata.links,
        requirements=t.requirements.model_dump(exclude_none=True),
        form=t.form.model_dump(by_alias=True, exclude_none=True),
        services=list(t.services), manifest=entry.manifest,
    )  # fmt: skip
