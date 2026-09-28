"""Compiles a template + validated inputs into a standard compose file.

The output is plain Compose: it runs with ``docker compose up`` without
Hivora. Secrets are ``${HV_SECRET_*}`` references resolved from ``.env``.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from hivora.core.errors import ValidationError
from hivora.templates.expressions import render, secret_env_name
from hivora.templates.forms import FormValues
from hivora.templates.schema import Exposure, PortSpec, Template

LABEL_APP = "io.hivora.app"
LABEL_ZONE = "io.hivora.zone"
LABEL_REVISION = "io.hivora.revision"


@dataclass(frozen=True, slots=True)
class HostInfo:
    public_ip: str | None = None
    lan_ip: str | None = None
    vpn_ip: str | None = None
    timezone: str = "UTC"
    puid: int = 1000
    pgid: int = 1000
    arch: str = "amd64"  # picks the service image variant


@dataclass(frozen=True, slots=True)
class AppContext:
    slug: str
    name: str
    revision: int
    zone: str | None = None
    zone_network: str | None = None  # Docker network shared by the zone's apps
    extra_networks: tuple[str, ...] = ()  # other zones' networks (a VPN reaching them)


@dataclass(frozen=True, slots=True)
class PortPlan:
    service: str
    container_port: int
    host_port: int | None  # None: not published (internal)
    protocol: str
    purpose: str
    exposure: Exposure
    host_ip: str | None


@dataclass(frozen=True, slots=True)
class VolumePlan:
    service: str
    name: str
    source: Path
    target: str
    read_only: bool
    backup: bool
    owner: str | None = None  # "uid:gid" of the host folder, None: PUID/PGID


@dataclass(frozen=True, slots=True)
class ServicePlan:
    name: str
    image: str
    role: str
    restart: str
    ports: tuple[PortPlan, ...]
    volumes: tuple[VolumePlan, ...]


@dataclass(frozen=True, slots=True)
class CompiledApp:
    compose: dict[str, Any]
    compose_yaml: str
    env: dict[str, str]  # .env content: secret values keyed by variable name
    services: tuple[ServicePlan, ...]
    access: dict[str, str] = field(default_factory=dict)


def escape_compose(value: str) -> str:
    """User values must not trigger Compose interpolation."""
    return value.replace("$", "$$")


def build_context(
    app: AppContext, host: HostInfo, form: FormValues, services: list[str]
) -> dict[str, Any]:
    return {
        "form": form.values,
        "app": {"slug": app.slug, "name": app.name, "zone": app.zone},
        "host": {
            "public_ip": host.public_ip, "lan_ip": host.lan_ip, "vpn_ip": host.vpn_ip,
            "timezone": host.timezone, "puid": host.puid, "pgid": host.pgid,
        },
        "service": {name: {"host": name} for name in services},
    }  # fmt: skip


def _render_str(value: Any, ctx: dict[str, Any]) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if not isinstance(value, str):
        return str(value)
    out = render(value, ctx, escape=escape_compose)
    if out is None:  # unset optional field: empty, never the text "None"
        return ""
    if isinstance(out, bool):
        return "true" if out else "false"
    return out if isinstance(out, str) else str(out)


def _host_ip(exposure: Exposure, host: HostInfo, where: str) -> str | None:
    if exposure == "public":
        return None  # all interfaces
    if exposure == "lan":
        return host.lan_ip  # all interfaces when unknown
    if exposure == "vpn":
        if not host.vpn_ip:
            raise ValidationError("no VPN interface configured", port=where)
        return host.vpn_ip
    return None


def _plan_port(svc: str, spec: PortSpec, ctx: dict[str, Any], host: HostInfo) -> PortPlan:
    where = f"{svc}:{spec.container}/{spec.protocol}"
    host_port: int | None = None
    if spec.exposure != "internal":
        raw = render(spec.host, ctx) if isinstance(spec.host, str) else spec.host
        try:
            host_port = int(raw) if raw is not None else spec.container
        except (TypeError, ValueError):
            raise ValidationError("invalid host port", port=where) from None
    return PortPlan(
        service=svc,
        container_port=spec.container,
        host_port=host_port,
        protocol=spec.protocol,
        purpose=spec.purpose,
        exposure=spec.exposure,
        host_ip=_host_ip(spec.exposure, host, where) if host_port else None,
    )


def compile_template(
    template: Template,
    app: AppContext,
    host: HostInfo,
    form: FormValues,
    volumes_root: Path,
) -> CompiledApp:
    ctx = build_context(app, host, form, list(template.services))
    labels = {LABEL_APP: app.slug, LABEL_REVISION: str(app.revision)}
    if app.zone:
        labels[LABEL_ZONE] = app.zone

    compose_services: dict[str, Any] = {}
    configs: dict[str, Any] = {}
    plans: list[ServicePlan] = []
    for name, spec in template.services.items():
        spec = spec.for_arch(host.arch).for_values(form.values)
        ports = tuple(_plan_port(name, p, ctx, host) for p in spec.ports)
        volumes = tuple(
            VolumePlan(name, v.name, volumes_root / app.slug / v.name, v.target, v.read_only,
                       v.backup, v.owner)
            for v in spec.volumes
        )  # fmt: skip
        svc: dict[str, Any] = {"image": spec.image_ref, "restart": template.defaults.restart}
        if spec.command is not None:
            svc["command"] = (
                _render_str(spec.command, ctx)
                if isinstance(spec.command, str)
                else [_render_str(c, ctx) for c in spec.command]
            )
        if spec.user:
            svc["user"] = _render_str(spec.user, ctx)
        # An empty value means "not set": optional fields (seed, modpack, custom
        # properties) must not reach images that reject empty variables.
        env = {k: _render_str(v, ctx) for k, v in spec.env.items()}
        if env := {k: v for k, v in env.items() if v != ""}:
            svc["environment"] = env
        published = [p for p in ports if p.host_port is not None]
        if published:
            svc["ports"] = [
                {"target": p.container_port, "published": str(p.host_port),
                 "protocol": p.protocol, **({"host_ip": p.host_ip} if p.host_ip else {})}
                for p in published
            ]  # fmt: skip
        if internal := [p for p in ports if p.host_port is None]:
            svc["expose"] = [f"{p.container_port}/{p.protocol}" for p in internal]
        if volumes:
            svc["volumes"] = [
                {"type": "bind", "source": str(v.source), "target": v.target,
                 **({"read_only": True} if v.read_only else {})}
                for v in volumes
            ]  # fmt: skip
        if spec.healthcheck:
            svc["healthcheck"] = spec.healthcheck
        if spec.depends_on:
            svc["depends_on"] = list(spec.depends_on)
        if spec.cap_add:
            svc["cap_add"] = list(spec.cap_add)
        if spec.sysctls:
            svc["sysctls"] = dict(spec.sysctls)
        if spec.shm_size:
            svc["shm_size"] = spec.shm_size
        if spec.files:
            svc["configs"] = []
            for i, f in enumerate(spec.files):
                key = f"{name}-file-{i}"
                configs[key] = {"content": _render_str(f.content, ctx)}
                svc["configs"].append({"source": key, "target": f.target})
        if app.zone_network or app.extra_networks:
            svc["networks"] = ["default", *(["zone"] if app.zone_network else []),
                               *(f"reach{i}" for i in range(len(app.extra_networks)))]  # fmt: skip
        if spec.stop_grace_period:
            svc["stop_grace_period"] = spec.stop_grace_period
        if spec.stdin_open:
            svc["stdin_open"] = True
        if spec.tty:
            svc["tty"] = True
        svc["labels"] = labels
        compose_services[name] = svc
        plans.append(
            ServicePlan(name, spec.image_ref, spec.role, template.defaults.restart, ports, volumes)
        )

    compose: dict[str, Any] = {"name": app.slug, "services": compose_services}
    if configs:
        compose["configs"] = configs
    networks = {
        f"reach{i}": {"name": n, "external": True} for i, n in enumerate(app.extra_networks)
    }
    if app.zone_network:  # created by Hivora before `up` (external to the project)
        networks["zone"] = {"name": app.zone_network, "external": True}
    if networks:
        compose["networks"] = networks
    header = (
        f"# Generated by Hivora: app {app.slug}, revision {app.revision}.\n"
        "# Plain Compose file: `docker compose up -d` works without Hivora.\n"
        "# Secret values live in .env next to this file.\n"
    )
    body = yaml.safe_dump(compose, sort_keys=False, allow_unicode=True, default_flow_style=False)
    access: dict[str, str] = {}
    if template.access:
        # Shown to the user: without a known public IP, the LAN address is the
        # best guess; with no address at all, show nothing rather than ":25565".
        display_host = {**ctx["host"], "public_ip": host.public_ip or host.lan_ip}
        display_ctx = {**ctx, "host": display_host}
        for key in ("web", "game"):
            if (value := getattr(template.access, key)) is None:
                continue
            rendered = _render_str(value, display_ctx).replace("$$", "$")
            if rendered and not rendered.startswith(":"):
                access[key] = rendered
    return CompiledApp(
        compose=compose,
        compose_yaml=header + body,
        env={secret_env_name(k): v for k, v in form.secrets.items()},
        services=tuple(plans),
        access=access,
    )
