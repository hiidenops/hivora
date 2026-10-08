"""Compiles an app's template against its inputs, the host and the running state: the
plan every deploy and settings change is reviewed and applied from (``AppPlanner``), and
the service rows a compiled app gives (``services_from``)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hivora.apps.core import decrypt_secrets, get_app, latest_revision
from hivora.apps.models import (
    Application,
    Exposure,
    PortBinding,
    Service,
    ServiceRole,
    VolumeKind,
    VolumeMount,
)
from hivora.apps.ports import PortConflict, find_conflicts, used_ports
from hivora.core.clock import Clock
from hivora.core.config import Settings
from hivora.core.errors import ConflictError, NotFoundError, ValidationError
from hivora.crypto.cipher import SecretBox
from hivora.state import StateStore
from hivora.system.secrets import SecretSetting, SecretSettings
from hivora.templates import (
    AppContext,
    Catalog,
    CatalogEntry,
    CompiledApp,
    FormValues,
    HostInfo,
    build_context,
    compile_template,
    validate_inputs,
)
from hivora.templates.models import TemplateVersion
from hivora.templates.overrides import ExtraPort, Overrides, ServiceOverrides
from hivora.zones import Zone, get_zone, zone_network


@dataclass(frozen=True, slots=True)
class DeployPlan:
    """Everything the user reviews before deploying (radical transparency)."""

    slug: str
    name: str
    entry: CatalogEntry
    zone: Zone | None
    compiled: CompiledApp
    form: FormValues
    conflicts: list[PortConflict]
    overrides: Overrides = field(default_factory=Overrides)


@dataclass(frozen=True, slots=True)
class AppSettings:
    app: Application
    entry: CatalogEntry
    values: dict[str, Any]  # latest revision inputs (secrets excluded)
    secrets_set: list[str]  # secret keys that already have a value


def services_from(compiled: CompiledApp) -> list[Service]:
    services = []
    for plan in compiled.services:
        services.append(Service(
            name=plan.name, image=plan.image, role=ServiceRole(plan.role),
            restart_policy=plan.restart,
            ports=[
                PortBinding(host_ip=p.host_ip, host_port=p.host_port,
                            container_port=p.container_port, protocol=p.protocol,
                            purpose=p.purpose, exposure=Exposure(p.exposure))
                for p in plan.ports
            ],
            volumes=[
                VolumeMount(kind=VolumeKind.BIND, source=str(v.source), target=v.target,
                            read_only=v.read_only, backup=v.backup, owner=v.owner)
                for v in plan.volumes
            ],
        ))  # fmt: skip
    return services


# Ports published for an app on top of its revision (the sites an nginx hosts), from the
# current database: (session, app slug, the revision's advanced settings) -> ports.
SitePorts = Callable[[AsyncSession, str, Overrides], Awaitable[list[ExtraPort]]]


class AppPlanner:
    """Compiles an app's template against its inputs, the host and the running state:
    the plan every deploy and settings change is reviewed and applied from."""

    # Set by the composition root (Runtime): apps never imports the sites module.
    site_ports: SitePorts | None = None

    def __init__(
        self, *, settings: Settings, catalog: Catalog, state: StateStore, box: SecretBox,
        clock: Clock, secret_settings: SecretSettings | None = None,
        public_address: Callable[[], str | None] | None = None,
    ) -> None:  # fmt: skip
        self.settings = settings
        self.catalog = catalog
        self.state = state
        self.box = box
        self.clock = clock
        self.secret_settings = secret_settings
        self.public_address = public_address

    @property
    def host(self) -> HostInfo:
        s = self.settings
        return HostInfo(
            public_ip=self.public_address() if self.public_address else s.host_public_ip,
            lan_ip=s.host_lan_ip,
            vpn_ip=s.host_vpn_ip,
            timezone=s.timezone,
            puid=s.puid,
            pgid=s.pgid,
            arch=self.catalog.host_arch(),
        )

    async def plan(
        self,
        session: AsyncSession,
        entry: CatalogEntry,
        slug: str,
        name: str,
        zone: Zone | None,
        inputs: dict[str, Any],
        *,
        revision: int,
        overrides: Overrides | None = None,
    ) -> DeployPlan:
        inputs = await self.with_setting_fallbacks(entry, inputs)
        app_ctx = AppContext(
            slug=slug, name=name, revision=revision, zone=zone.slug if zone else None,
            zone_network=zone_network(zone),
            extra_networks=await self.vpn_networks(session, entry, inputs),
        )  # fmt: skip
        host = self.host
        defaults_ctx = build_context(app_ctx, host, FormValues(), list(entry.template.services))
        form = validate_inputs(entry.template, inputs, defaults_ctx)
        overrides = overrides or Overrides()
        # The sites' ports are compiled in but never stored in the revision's overrides:
        # every compile (update, upgrade, restore) publishes the sites as they are now.
        compiled_with = overrides
        if self.site_ports and (extra := await self.site_ports(session, slug, overrides)):
            main = entry.template.main_service
            own = overrides.of(main) or ServiceOverrides()
            with_sites = own.model_copy(update={"ports": [*own.ports, *extra]})
            compiled_with = overrides.model_copy(
                update={"services": {**overrides.services, main: with_sites}}
            )
        compiled = compile_template(entry.template, app_ctx, host, form, self.settings.volumes_root,
                                    compiled_with)  # fmt: skip
        used = await used_ports(session, self.state, exclude_app=slug)
        conflicts = find_conflicts((p for s in compiled.services for p in s.ports), used)
        return DeployPlan(slug, name, entry, zone, compiled, form, conflicts, overrides)

    async def with_setting_fallbacks(
        self, entry: CatalogEntry, inputs: dict[str, Any]
    ) -> dict[str, Any]:
        """Empty secrets declaring `from_setting` take the global setting's value."""
        if self.secret_settings is None:
            return inputs
        filled = dict(inputs)
        for f in entry.template.form.fields:
            if f.type == "secret" and f.from_setting and not filled.get(f.id):
                value = await self.secret_settings.get(SecretSetting(f.from_setting))
                if value:
                    filled[f.id] = value
        return filled

    async def current_settings(self, session: AsyncSession, app_id: int) -> AppSettings:
        app = await get_app(session, app_id)
        entry = await self.entry_of(session, app)
        revision = await latest_revision(session, app.id)
        secrets = await decrypt_secrets(session, self.box, app.id)
        known = {f.id for f in entry.template.form.fields}  # a newer template may drop fields
        values = {k: v for k, v in (revision.inputs if revision else {}).items() if k in known}
        return AppSettings(app, entry, values, sorted(secrets))

    async def vpn_networks(
        self, session: AsyncSession, entry: CatalogEntry, inputs: dict[str, Any]
    ) -> tuple[str, ...]:
        """A VPN joins the networks of the zones it reaches (only "linked together" zones
        have one) and of the apps put behind it ("@<app>": that app's default network)."""
        vpn = entry.template.vpn
        if not vpn or not vpn.zones_field:
            return ()
        names = []
        for slug in (s for s in str(inputs.get(vpn.zones_field) or "").split(",") if s):
            if slug.startswith("@"):
                app_slug = slug[1:]
                if not await session.scalar(
                    select(Application.id).where(Application.slug == app_slug)
                ):
                    raise ValidationError(
                        "no such app to reach", field=vpn.zones_field, app=app_slug
                    )
                names.append(f"{app_slug}_default")
                continue
            name = zone_network(await get_zone(session, slug))
            if name is None:
                raise ValidationError("this zone does not link its apps: no network to reach",
                                      field=vpn.zones_field, zone=slug)  # fmt: skip
            names.append(name)
        return tuple(names)

    async def entry_of(self, session: AsyncSession, app: Application) -> CatalogEntry:
        slug = await session.scalar(
            select(TemplateVersion.slug).where(TemplateVersion.id == app.template_version_id)
        )
        if slug is None:
            raise ConflictError("this app was not deployed from a template", slug=app.slug)
        return self.catalog.get(slug)

    async def vpns_reaching(self, session: AsyncSession, slug: str) -> list[str]:
        """Names of the VPN apps that joined this app's network (it is behind them)."""
        out = []
        for other in await session.scalars(select(Application)):
            try:
                entry = await self.entry_of(session, other)
            except (ConflictError, NotFoundError):
                continue
            vpn = entry.template.vpn
            if vpn and vpn.zones_field:
                values = (await self.current_settings(session, other.id)).values
                if f"@{slug}" in str(values.get(vpn.zones_field) or "").split(","):
                    out.append(other.name)
        return out

    async def template_version(self, session: AsyncSession, entry: CatalogEntry) -> TemplateVersion:
        meta = entry.template.metadata
        existing = await session.scalar(
            select(TemplateVersion).where(
                TemplateVersion.source == entry.source,
                TemplateVersion.slug == meta.slug,
                TemplateVersion.version == meta.version,
            )
        )
        if existing:
            if existing.checksum != entry.checksum:
                raise ConflictError(
                    "template changed without a version bump", slug=meta.slug, version=meta.version
                )
            return existing
        version = TemplateVersion(
            source=entry.source, slug=meta.slug, version=meta.version,
            api_version=entry.template.api_version, name=meta.name, category=meta.category,
            manifest=entry.manifest, checksum=entry.checksum, created_at=self.clock.now(),
        )  # fmt: skip
        session.add(version)
        await session.flush()
        return version
