"""A template generated for a free image, so it lives like any other app.

Each environment variable and published port becomes a form field (editable
later through "Edit settings"); secrets stay secrets; the image is pinned by
the digest read from its registry.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Literal

import yaml

ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
PATH = re.compile(r"^/[A-Za-z0-9._/-]{0,250}$")


@dataclass(frozen=True, slots=True)
class CustomPort:
    container: int
    host: int
    protocol: Literal["tcp", "udp"] = "tcp"
    exposure: Literal["lan", "public", "internal"] = "lan"
    web: bool = False  # the app's web interface: shown as its address


@dataclass(frozen=True, slots=True)
class CustomEnv:
    key: str
    value: str
    secret: bool = False


@dataclass(frozen=True, slots=True)
class CustomApp:
    slug: str
    name: str
    image: str  # compose name, e.g. grafana/grafana
    pinned: str  # tag@digest
    platforms: list[str]
    ports: list[CustomPort] = field(default_factory=list)
    volumes: list[str] = field(default_factory=list)  # container paths
    env: list[CustomEnv] = field(default_factory=list)


def check(app: CustomApp) -> None:
    if len({e.key for e in app.env}) != len(app.env) or not all(
        ENV_KEY.match(e.key) for e in app.env
    ):
        raise ValueError("invalid or duplicate environment variable names")
    if not all(PATH.match(v) and ".." not in v.split("/") for v in app.volumes):
        raise ValueError("volumes must be absolute paths inside the container")
    if any("{{" in e.value or "}}" in e.value for e in app.env):
        raise ValueError("environment values cannot contain {{ or }}")
    if len(set(app.volumes)) != len(app.volumes):
        raise ValueError("duplicate volume paths")


def manifest(app: CustomApp, version: str) -> str:
    """The hivora/v1 template (YAML) for this image; validated by the catalog."""
    check(app)
    fields: list[dict[str, Any]] = []
    env: dict[str, str] = {}
    for i, e in enumerate(app.env):
        fid = f"env_{i}"
        if e.secret:
            fields.append({"id": fid, "label": e.key, "type": "secret"})
            env[e.key] = f"{{{{ secret.{fid} }}}}"
        else:
            fields.append({"id": fid, "label": e.key, "type": "string", "default": e.value})
            env[e.key] = f"{{{{ form.{fid} }}}}"
    ports = []
    web = None
    for i, p in enumerate(app.ports):
        fid = f"port_{i}"
        label = f"{p.container}/{p.protocol}"
        text = {"fr": f"Port hôte pour {label}", "en": f"Host port for {label}"}
        fields.append({"id": fid, "label": text, "type": "port", "default": p.host})
        ports.append({"container": p.container, "host": f"{{{{ form.{fid} }}}}",
                      "protocol": p.protocol, "exposure": p.exposure,
                      "purpose": "web" if p.web else "other"})  # fmt: skip
        if p.web and web is None:
            web = f"http://{{{{ host.lan_ip }}}}:{{{{ form.{fid} }}}}"
    arch = [a for a in ("amd64", "arm64") if a in app.platforms]
    doc = {
        "apiVersion": "hivora/v1",
        "kind": "Template",
        "metadata": {
            "slug": f"custom-{app.slug}", "name": app.name, "version": version,
            "category": "services",
            "description": {"fr": f"Image Docker {app.image}", "en": f"Docker image {app.image}"},
            "source": app.image,
        },
        "requirements": {"arch": arch},
        "form": {"basic": fields},
        "services": {"app": {
            "role": "main", "image": app.image, "tag": app.pinned, "env": env, "ports": ports,
            "volumes": [{"name": f"vol{i}", "target": v, "backup": True}
                        for i, v in enumerate(app.volumes)],
        }},
        **({"access": {"web": web}} if web else {}),
    }  # fmt: skip
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
