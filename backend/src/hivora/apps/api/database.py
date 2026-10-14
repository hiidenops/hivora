"""An app's database card: how to reach it, the tools linked to it, the ones to install."""

from typing import Any

from pydantic import BaseModel

from hivora.apps import links
from hivora.apps.models import Application
from hivora.core.errors import NotFoundError
from hivora.web.deps import RuntimeDep


class DbToolOut(BaseModel):
    id: int
    name: str
    web: str | None  # its address, when published


class DbToolTemplateOut(BaseModel):
    slug: str
    name: str


class DatabaseOut(BaseModel):
    host: str  # from its zone and from linked tools
    port: int  # the container's (the host's, when opened: see the app's ports)
    database: str | None
    user: str | None
    tools: list[DbToolOut]  # apps linked to it (phpMyAdmin...)
    installable: list[DbToolTemplateOut]  # templates that may link to it


async def database_of(rt: RuntimeDep, session: Any, app: Application,
                      template: str | None) -> DatabaseOut | None:  # fmt: skip
    """None: not an app other apps link to (its template has no ``connection``)."""
    try:
        t = rt.catalog.get(template).template if template else None
    except NotFoundError:
        return None
    target = await links.target_of(session, t, app) if t else None
    if target is None or template is None:
        return None
    tools = [DbToolOut(id=a.id, name=a.name, web=(await rt.apps.access_of(session, a)).get("web"))
             for a in await links.linked_by(session, rt.catalog, app.slug)]  # fmt: skip
    metas = [x.metadata for x in links.tool_templates(rt.catalog, template)]
    installable = [DbToolTemplateOut(slug=m.slug, name=m.name) for m in metas]
    return DatabaseOut(host=target.host, port=target.port, database=target.database,
                       user=target.user, tools=tools, installable=installable)  # fmt: skip
