"""Links between apps: a tool's "app" field chooses an app of given templates (e.g. a database
for phpMyAdmin). The tool joins that app's network (``<slug>_default``, whatever their
zones) and reads it through ``link.<field>.*``, as the app's template describes it in its
``connection`` section. The app's password reaches the tool only for an auto-login the user
asked for (the field's ``password_if``): it is then one of the tool's secrets, sealed and
written to its ``.env`` only, and gone from it as soon as the box is unchecked.
"""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hivora.apps.core import decrypt_secrets, latest_revision
from hivora.apps.models import Application
from hivora.apps.queries import apps_with_template, template_slug
from hivora.core.errors import ConflictError, NotFoundError, ValidationError
from hivora.crypto.cipher import SecretBox
from hivora.templates import Catalog, LinkTarget, Template
from hivora.templates.expressions import link_secret, render


class LinkInvalidError(ValidationError):
    code = "link_invalid"


class LinkedAppError(ConflictError):
    code = "app_linked"


@dataclass(frozen=True, slots=True)
class Links:
    targets: dict[str, LinkTarget] = field(default_factory=dict)  # field -> the app it reads
    networks: tuple[str, ...] = ()  # the linked apps' networks, joined by the tool
    secrets: dict[str, str] = field(default_factory=dict)  # asked auto-logins' passwords


async def resolve(session: AsyncSession, catalog: Catalog, box: SecretBox, template: Template,
                  values: dict[str, Any]) -> Links:  # fmt: skip
    """The apps the link fields of ``template`` chose in ``values`` (checked: they exist and
    come from an allowed template that says how to reach it)."""
    targets: dict[str, LinkTarget] = {}
    networks: list[str] = []
    secrets: dict[str, str] = {}
    for f in template.form.fields:
        slug = values.get(f.id)
        if f.type != "app" or not slug or f.link is None:
            continue
        app = await session.scalar(select(Application).where(Application.slug == slug))
        if app is None:
            raise LinkInvalidError("no such app", field=f.id, app=slug)
        source = await template_slug(session, app)
        if source not in f.link.templates:
            raise LinkInvalidError("this app cannot be linked here", field=f.id, app=slug)
        target = await target_of(session, catalog.get(source).template, app)
        if target is None:
            raise LinkInvalidError("this app does not say how to reach it", field=f.id, app=slug)
        targets[f.id] = target
        networks.append(f"{app.slug}_default")
        conn = catalog.get(source).template.connection
        if f.link.password_if and values.get(f.link.password_if) is True and conn and conn.password:
            password = (await decrypt_secrets(session, box, app.id)).get(conn.password)
            if password:
                secrets[link_secret(f.id)] = password
    return Links(targets, tuple(networks), secrets)


async def target_of(session: AsyncSession, template: Template,
                    app: Application) -> LinkTarget | None:  # fmt: skip
    """How a tool reaches ``app`` (its template's ``connection`` on its latest form; None:
    the template does not say)."""
    conn = template.connection
    if conn is None:
        return None
    revision = await latest_revision(session, app.id)
    ctx = {"form": revision.inputs if revision else {},
           "app": {"slug": app.slug, "name": app.name}}  # fmt: skip
    service = conn.service or template.main_service
    return LinkTarget(host=f"{app.slug}-{service}-1", port=conn.port,
                      database=_text(conn.database, ctx), user=_text(conn.user, ctx))  # fmt: skip


def tool_templates(catalog: Catalog, source: str) -> list[Template]:
    """The catalog's templates with a link field that may choose an app of ``source``."""
    return sorted((e.template for e in catalog.entries()
                  if any(f.link and source in f.link.templates
                         for f in e.template.form.fields)),
                  key=lambda t: t.metadata.slug)  # fmt: skip


async def linked_by(session: AsyncSession, catalog: Catalog, slug: str) -> list[Application]:
    """The apps whose link fields chose this app (they reach its network)."""
    out = []
    for app, source in await apps_with_template(session):
        try:
            template = catalog.get(source).template if source else None
        except NotFoundError:
            continue
        links = [f.id for f in template.form.fields if f.type == "app"] if template else []
        if not links:
            continue
        revision = await latest_revision(session, app.id)
        inputs = revision.inputs if revision else {}
        if any(inputs.get(f) == slug for f in links):
            out.append(app)
    return out


def _text(expr: str | None, ctx: dict[str, Any]) -> str | None:
    """A ``connection`` expression on the linked app's own form (None: not given)."""
    value = render(expr, ctx) if expr is not None else None
    return str(value) if value not in (None, "") else None
