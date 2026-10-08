"""Run a Python project sent as a .zip: analyze it, generate its template, deploy it.

The official ``python:<version>-slim`` image (pinned by digest) runs the code
from the app's folders, mounted where the project expects them (its compose
file, its Dockerfile's COPY, or /app). A virtualenv kept in its own folder
makes restarts quick; the dependencies are installed at each start (a no-op
when nothing changed). Sending new code replaces the code folders only: data
folders stay.
"""

import asyncio
import os
import re
import secrets
import shlex
import shutil
import time
import zipfile
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.apps.queries import app_id_by_slug
from hivora.apps.service import AppService, DeployRequest, slugify
from hivora.core.config import Settings
from hivora.core.errors import ConflictError, NotFoundError, ValidationError
from hivora.core.events import EventBus
from hivora.core.fs import confined, receive_upload
from hivora.jobs import Job
from hivora.pyapps.analyze import Analysis, Mount, ProjectError, _Zip, analyze, volume_name
from hivora.templates import Catalog
from hivora.templates.catalog import TemplateInvalidError

IMAGES = {
    "3.11": "3.11-slim@sha256:e41613d42d4891e4930f79523f93f81bbc7632584ec65e36ab055f41a800b41e",
    "3.12": "3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f",
    "3.13": "3.13-slim@sha256:7c61056e61ac89e852de05f3dc6fa51a6dd2181797bceed46aa725dd7cb2cd3b",
}
TAG = "python-project"
MAX_ZIP = 300 * 1024**2
UPLOAD_TTL_S = 3600
CONTAINER_PATH = re.compile(r"^/[A-Za-z0-9._/-]{0,200}$")
PROJECT_PATH = re.compile(r"^[A-Za-z0-9._/-]{0,200}$")
ARG = re.compile(r"^[^\x00\n]{1,500}$")
PACKAGE = re.compile(r"^[a-z0-9][a-z0-9.+-]{0,63}$")
ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")


class UploadNotFoundError(NotFoundError):
    code = "upload_not_found"


class InvalidProjectError(ValidationError):
    code = "invalid_project"


class NotAPythonAppError(ConflictError):
    code = "not_a_python_app"


@dataclass
class ProjectSpec:
    """What the user confirmed after the analysis."""

    name: str
    python: str
    requirements: str | None
    workdir: str
    entry: list[str]
    mounts: list[Mount]
    env: list[dict[str, Any]]  # {key, value, secret}
    ports: list[dict[str, int]]  # {container, host}
    apt: list[str]


def check(spec: ProjectSpec) -> None:
    def bad(what: str) -> InvalidProjectError:
        return InvalidProjectError(f"invalid {what}", field=what)

    if spec.python not in IMAGES:
        raise bad("python")
    if spec.requirements is not None and not (spec.requirements == "." or (PROJECT_PATH.match(
            spec.requirements) and ".." not in spec.requirements.split("/"))):  # fmt: skip
        raise bad("requirements")
    if not CONTAINER_PATH.match(spec.workdir) or ".." in spec.workdir.split("/"):
        raise bad("workdir")
    if not spec.entry or len(spec.entry) > 30 or not all(ARG.match(a) for a in spec.entry):
        raise bad("entry")
    if not spec.mounts or len(spec.mounts) > 10:
        raise bad("mounts")
    names = [volume_name(m) for m in spec.mounts]
    targets = [m.target for m in spec.mounts]
    if len(set(names)) != len(names) or len(set(targets)) != len(targets) or "venv" in names:
        raise bad("mounts")
    for m in spec.mounts:
        ok_source = PROJECT_PATH.match(m.source) and ".." not in m.source.split("/")
        if not ok_source or not CONTAINER_PATH.match(m.target) or ".." in m.target.split("/"):
            raise bad("mounts")
        if m.target in ("/", "/venv", "/usr", "/bin", "/etc", "/lib", "/proc", "/sys", "/dev"):
            raise bad("mounts")
    if not all(ENV_KEY.match(str(e.get("key", ""))) for e in spec.env):
        raise bad("env")
    if len({e["key"] for e in spec.env}) != len(spec.env):
        raise bad("env")
    for p in spec.ports:
        if not (1 <= int(p.get("container", 0)) <= 65535 and 1 <= int(p.get("host", 0)) <= 65535):
            raise bad("ports")
    if not all(PACKAGE.match(a) for a in spec.apt) or len(spec.apt) > 50:
        raise bad("apt")


def start_script(spec: ProjectSpec) -> str:
    """Shell run at each start: system packages, virtualenv, dependencies, the program."""
    q = shlex.quote
    target = {m.source: m.target for m in spec.mounts}

    def container(project_path: str) -> str:
        best = max((s for s in target if s == "" or project_path == s
                    or project_path.startswith(f"{s}/")), key=len)  # fmt: skip
        rest = project_path[len(best) :].lstrip("/") if best else project_path
        return str(PurePosixPath(target[best]) / rest) if rest and rest != "." else target[best]

    lines = ["set -e"]
    if spec.apt:
        lines.append("apt-get update -qq && apt-get install -y -qq --no-install-recommends "
                     + " ".join(q(p) for p in spec.apt) + " >/dev/null")  # fmt: skip
    lines += [
        # A virtualenv made by another Python version is started again from scratch.
        f'[ "$(cat /venv/.python 2>/dev/null)" = {q(spec.python)} ] || '
        f"{{ rm -rf /venv/* /venv/.[!.]* 2>/dev/null || true; python -m venv /venv; "
        f"echo {q(spec.python)} > /venv/.python; }}",
        "export PATH=/venv/bin:$PATH PIP_DISABLE_PIP_VERSION_CHECK=1",
    ]
    if spec.requirements:
        path = container(spec.requirements)
        if spec.requirements.endswith(".txt"):
            lines.append(f"pip install -q -r {q(path)}")
        else:
            lines.append(f"pip install -q {q(path)}")
    lines += [f"cd {q(spec.workdir)}", "exec " + " ".join(q(a) for a in spec.entry)]
    return "\n".join(lines)


def manifest(slug: str, spec: ProjectSpec, version: str) -> str:
    fields: list[dict[str, Any]] = []
    env: dict[str, str] = {"PYTHONUNBUFFERED": "1", "TZ": "{{ host.timezone }}"}
    for i, e in enumerate(spec.env):
        fid = f"env_{i}"
        if e.get("secret"):
            fields.append({"id": fid, "label": e["key"], "type": "secret"})
            env[e["key"]] = f"{{{{ secret.{fid} }}}}"
        else:
            fields.append({"id": fid, "label": e["key"], "type": "string",
                           "default": str(e.get("value") or "")})  # fmt: skip
            env[e["key"]] = f"{{{{ form.{fid} }}}}"
    ports = []
    for i, p in enumerate(spec.ports):
        fid = f"port_{i}"
        label = {"fr": f"Port hôte pour {p['container']}", "en": f"Host port for {p['container']}"}
        fields.append({"id": fid, "label": label, "type": "port", "default": int(p["host"])})
        ports.append({"container": int(p["container"]), "host": f"{{{{ form.{fid} }}}}",
                      "purpose": "web", "exposure": "lan"})  # fmt: skip
    volumes = [{"name": volume_name(m), "target": m.target, "backup": True} for m in spec.mounts]
    volumes.append({"name": "venv", "target": "/venv", "backup": False})
    doc = {
        "apiVersion": "hivora/v1",
        "kind": "Template",
        "metadata": {
            "slug": f"custom-{slug}", "name": spec.name, "version": version,
            "category": "development", "tags": [TAG],
            "description": {"fr": f"Projet Python ({' '.join(spec.entry)})",
                            "en": f"Python project ({' '.join(spec.entry)})"},
            "source": "zip",
        },
        "requirements": {"arch": ["amd64", "arm64"]},
        "form": {"basic": fields},
        "services": {"app": {
            "role": "main", "image": "python", "tag": IMAGES[spec.python],
            "command": ["sh", "-c", start_script(spec)], "env": env, "ports": ports,
            "volumes": volumes,
        }},
        "defaults": {"restart": "unless-stopped"},
    }  # fmt: skip
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)


def extract(path: Path, mounts: list[Mount], base: Path, *, only_code: bool, uid: int,
            gid: int) -> int:  # fmt: skip
    """Unpack the project into the app's folders (one per mount). Returns files written.

    ``only_code``: data folders are left untouched (new code sent for a running app).
    """
    z = _Zip(str(path))
    written = 0
    for m in mounts:
        if only_code and m.data:
            continue
        dest = confined(base / volume_name(m), base)
        if only_code and dest.exists():
            for child in dest.iterdir():
                shutil.rmtree(
                    child
                ) if child.is_dir() and not child.is_symlink() else child.unlink()
        dest.mkdir(parents=True, exist_ok=True)
        prefix = f"{m.source}/" if m.source else ""
        for name, info in z.infos.items():
            if not name.startswith(prefix):
                continue
            rel = name[len(prefix) :]
            # A nested mount owns its own folder: don't copy it twice.
            if any(o is not m and o.source.startswith(prefix) and o.source != m.source
                   and name.startswith(f"{o.source}/") for o in mounts):  # fmt: skip
                continue
            target = confined(dest / rel, dest)
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.zf.open(info) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out)
            written += 1
        if os.geteuid() == 0:
            for root, dirs, files in os.walk(dest):
                for n in [*dirs, *files]:
                    os.chown(os.path.join(root, n), uid, gid, follow_symlinks=False)
            os.chown(dest, uid, gid)
    return written


class PythonProjects:
    def __init__(
        self, *, settings: Settings, sessions: async_sessionmaker[AsyncSession], catalog: Catalog,
        apps: AppService, bus: EventBus,
    ) -> None:  # fmt: skip
        self.settings = settings
        self.sessions = sessions
        self.catalog = catalog
        self.apps = apps
        self.bus = bus

    @property
    def uploads(self) -> Path:
        return self.settings.data_dir / "uploads"

    def _upload(self, token: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", token):
            raise UploadNotFoundError("unknown upload")
        path = self.uploads / f"py-{token}.zip"
        if not path.exists():
            raise UploadNotFoundError("upload expired, send the archive again")
        return path

    async def receive(self, chunks: AsyncIterator[bytes]) -> tuple[str, Path]:
        self.uploads.mkdir(parents=True, exist_ok=True)
        for old in self.uploads.glob("py-*.zip"):  # ponytail: swept at each upload
            if time.time() - old.stat().st_mtime > UPLOAD_TTL_S:
                old.unlink(missing_ok=True)
        token = secrets.token_hex(16)
        path = self.uploads / f"py-{token}.zip"
        await receive_upload(_capped(chunks, MAX_ZIP), path)
        return token, path

    async def analyze(self, chunks: AsyncIterator[bytes], filename: str) -> tuple[str, Analysis]:
        token, path = await self.receive(chunks)
        try:
            result = await asyncio.to_thread(analyze, str(path), Path(filename).stem)
        except (ProjectError, zipfile.BadZipFile) as exc:
            path.unlink(missing_ok=True)
            raise InvalidProjectError(str(exc) or "not a zip archive") from exc
        return token, result

    async def deploy(self, token: str, spec: ProjectSpec, zone: str | None) -> tuple[Any, Job]:
        check(spec)
        path = self._upload(token)
        apps = self.apps
        slug = slugify(spec.name)
        async with self.sessions() as session:
            if await app_id_by_slug(session, slug):
                raise ConflictError("an app already uses this name", slug=slug)
        text = manifest(slug, spec, version=f"1.0.{int(time.time())}")
        try:
            entry = self.catalog.add_custom(text)
        except TemplateInvalidError as exc:
            raise InvalidProjectError(str(exc)[:300]) from exc
        s = self.settings
        await asyncio.to_thread(extract, path, spec.mounts, apps.volumes_dir(slug),
                                only_code=False, uid=s.puid, gid=s.pgid)  # fmt: skip
        path.unlink(missing_ok=True)
        inputs: dict[str, Any] = {f"env_{i}": e.get("value") or "" for i, e in enumerate(spec.env)}
        inputs |= {f"port_{i}": int(p["host"]) for i, p in enumerate(spec.ports)}
        request = DeployRequest(entry.slug, spec.name, inputs, slug=slug, zone=zone)
        app, job = await apps.deployer.deploy(request)
        self.bus.publish("app.python_deployed", app=slug, files=spec.entry)
        return app, job

    async def update_code(self, app_id: int, chunks: AsyncIterator[bytes]) -> Job:
        """New code for a Python app: its code folders are replaced, data kept, restart."""
        async with self.sessions() as session:
            app, entry, _ = await self.apps.main_container(session, app_id)
        if entry is None or TAG not in entry.template.metadata.tags:
            raise NotAPythonAppError("this app is not a Python project", slug=app.slug)
        mounted = {v.name: v.target for v in entry.template.services["app"].volumes}
        _, path = await self.receive(chunks)
        try:
            found = await asyncio.to_thread(analyze, str(path), app.name)
        except (ProjectError, zipfile.BadZipFile) as exc:
            path.unlink(missing_ok=True)
            raise InvalidProjectError(str(exc) or "not a zip archive") from exc
        # Keep the app's own layout: only folders it already mounts are refreshed.
        mounts = [m for m in found.mounts if mounted.get(volume_name(m)) == m.target]
        if not mounts:
            path.unlink(missing_ok=True)
            raise InvalidProjectError("the new archive does not match this app's folders")
        s = self.settings
        await asyncio.to_thread(extract, path, mounts, self.apps.volumes_dir(app.slug),
                                only_code=True, uid=s.puid, gid=s.pgid)  # fmt: skip
        path.unlink(missing_ok=True)
        self.bus.publish("app.python_code_updated", app=app.slug)
        return await self.apps.lifecycle.restart(app_id)


async def _capped(chunks: AsyncIterator[bytes], limit: int) -> AsyncIterator[bytes]:
    total = 0
    async for chunk in chunks:
        total += len(chunk)
        if total > limit:
            raise InvalidProjectError("archive too large", limit=limit)
        yield chunk
