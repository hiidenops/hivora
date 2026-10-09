"""Free images: any registry image, read from its registry, pinned by digest and turned
into a generated template, so it lives like any other app."""

import asyncio
import hashlib
import logging
from contextlib import suppress
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.apps.core import DeployRequest, UnsupportedArchitectureError, slugify
from hivora.core.clock import Clock
from hivora.core.errors import ValidationError
from hivora.images.registry import ImageInfo, Registry
from hivora.templates import Catalog, CatalogEntry
from hivora.templates.catalog import CUSTOM_SOURCE, TemplateInvalidError, parse_template
from hivora.templates.custom import CustomApp, CustomEnv, CustomPort
from hivora.templates.custom import manifest as custom_manifest
from hivora.templates.models import TemplateVersion


class CustomImages:
    def __init__(self, *, sessions: async_sessionmaker[AsyncSession], catalog: Catalog,
                 clock: Clock, registry: Registry | None = None) -> None:  # fmt: skip
        self.sessions = sessions
        self.catalog = catalog
        self.clock = clock
        self.registry = registry or Registry()
        self.inspected: dict[str, tuple[float, ImageInfo]] = {}

    async def request(
        self, name: str, image: str, zone: str | None, ports: list[CustomPort],
        volumes: list[str], env: list[CustomEnv],
    ) -> DeployRequest:  # fmt: skip
        """Read the image from its registry, pin it, generate its template."""
        arch = self.catalog.host_arch()
        info = await self.registry.inspect(image, arch)
        if arch not in info.platforms:
            raise UnsupportedArchitectureError(
                f"{info.ref.name}:{info.ref.tag} has no {arch} build", arch=arch,
                platforms=info.platforms,
            )  # fmt: skip
        spec = CustomApp(slugify(name), name, info.ref.name, f"{info.ref.tag}@{info.digest}",
                         info.platforms, ports, volumes, env)  # fmt: skip
        try:
            text = custom_manifest(spec, version=f"1.0.{int(self.clock.now().timestamp())}")
            entry = self.catalog.add_custom(text)
        except (ValueError, TemplateInvalidError) as exc:
            raise ValidationError(str(exc)[:300]) from exc
        inputs: dict[str, Any] = {f"env_{i}": e.value for i, e in enumerate(env)}
        inputs |= {f"port_{i}": p.host for i, p in enumerate(ports)}
        return DeployRequest(entry.slug, name, inputs, zone=zone)

    async def load_templates(self) -> None:
        """Templates generated for free images live in the database: register them."""
        async with self.sessions() as session:
            rows = await session.scalars(
                select(TemplateVersion.manifest).where(TemplateVersion.source == CUSTOM_SOURCE)
                .order_by(TemplateVersion.created_at)
            )  # fmt: skip
            for text in rows:
                try:
                    self.catalog.add_custom(text)
                except TemplateInvalidError:  # pragma: no cover - written by us
                    continue

    async def inspect_cached(self, ref: str) -> ImageInfo:
        # ponytail: in-memory 10 min cache per image, enough for a page refreshed often
        now = self.clock.now().timestamp()
        hit = self.inspected.get(ref)
        if hit and now - hit[0] < 600:
            return hit[1]
        info = await self.registry.inspect(ref, self.catalog.host_arch())
        self.inspected[ref] = (now, info)
        return info

    def known_status(self, entry: CatalogEntry) -> tuple[str, str, bool] | None:
        """What the registry last said for this free image (no request); None: never asked."""
        svc = entry.template.services[entry.template.main_service]
        tag, _, digest = svc.tag.partition("@")
        hit = self.inspected.get(f"{svc.image}:{tag}")
        if hit is None:
            return None
        return f"{tag}@{digest[:19]}", f"{tag}@{hit[1].digest[:19]}", hit[1].digest != digest

    async def check_all(self) -> None:
        """Ask the registry about every free image, one after the other (the dashboard's
        update marks read the answers: known_status)."""
        for entry in self.catalog.custom_entries():
            with suppress(Exception):  # a registry down: the next round asks again
                await self.image_status(entry)

    async def image_status(self, entry: CatalogEntry) -> tuple[str, str, bool]:
        """(current, latest, newer available) for the main service's pinned tag."""
        svc = entry.template.services[entry.template.main_service]
        tag, _, digest = svc.tag.partition("@")
        info = await self.inspect_cached(f"{svc.image}:{tag}")
        return f"{tag}@{digest[:19]}", f"{tag}@{info.digest[:19]}", info.digest != digest

    async def repin(self, entry: CatalogEntry) -> CatalogEntry:
        """The free image's template pinned on its tag's current digest (a new version)."""
        doc = yaml.safe_load(entry.manifest)
        svc = doc["services"][entry.template.main_service]
        tag = str(svc["tag"]).partition("@")[0]
        self.inspected.pop(f"{svc['image']}:{tag}", None)  # applying: ask the registry again
        info = await self.inspect_cached(f"{svc['image']}:{tag}")
        svc["tag"] = f"{tag}@{info.digest}"
        previous = int(str(doc["metadata"]["version"]).rsplit(".", 1)[-1])
        now = int(self.clock.now().timestamp())
        doc["metadata"]["version"] = f"1.0.{max(now, previous + 1)}"  # always a new version
        text = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
        return CatalogEntry(parse_template(text, require_pinned=True), text,
                            hashlib.sha256(text.encode()).hexdigest(), CUSTOM_SOURCE)  # fmt: skip


CHECK_EVERY_S = 6 * 3600


async def check_images(custom: CustomImages, *, first_after: float = 60,
                       every: float = CHECK_EVERY_S) -> None:  # fmt: skip
    """In the background: the free images' registries asked every 6 h (the first time a
    minute after startup), so the dashboard can mark their updates without asking."""
    await asyncio.sleep(first_after)
    while True:
        try:
            await custom.check_all()
        except Exception:
            logging.getLogger(__name__).exception("free image update check failed")
        await asyncio.sleep(every)
