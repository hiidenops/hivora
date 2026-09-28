"""Read a Python project from its .zip and work out how to run it.

Nothing is executed: the archive is only listed and a few text files read
(Dockerfile, compose file, requirements, .env files, the code for os.getenv).
Each finding says where it comes from, so the user can check it.
"""

import json
import re
import shlex
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath

import yaml

SUPPORTED = ("3.11", "3.12", "3.13")
DEFAULT_PYTHON = "3.13"
MAX_FILES = 20_000
MAX_UNZIPPED = 1024**3  # 1 GB
IGNORED = re.compile(
    r"(^|/)(__MACOSX|__pycache__|\.git|\.venv|venv|\.mypy_cache|\.pytest_cache|node_modules)"
    r"(/|$)|\.pyc$|(^|/)\.DS_Store$"
)
SECRET = re.compile(r"TOKEN|KEY|SECRET|PASSWORD|PASS$|PWD|CREDENTIAL", re.I)
ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
GETENV = re.compile(
    r"""os\.(?:getenv|environ\.get)\(\s*["']([A-Za-z_][A-Za-z0-9_]*)["']"""
    r"""(?:\s*,\s*["']([^"'\n]*)["'])?|os\.environ\[\s*["']([A-Za-z_][A-Za-z0-9_]*)["']\s*\]"""
)
MAIN = re.compile(r"""if\s+__name__\s*==\s*["']__main__["']""")
PREFERRED = ("bot.py", "main.py", "app.py", "run.py", "__main__.py", "server.py")
PACKAGE = re.compile(r"^[a-z0-9][a-z0-9.+-]{0,63}$")
COMPOSE_FILES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")


class ProjectError(ValueError):
    """The archive cannot be a Python project Hivora runs."""


@dataclass
class Mount:
    source: str  # folder in the project ("" = the whole project)
    target: str  # path in the container
    data: bool  # kept when new code is sent (no Python file in it)


@dataclass
class EnvVar:
    key: str
    value: str = ""
    secret: bool = False
    source: str = ""  # where it was found


@dataclass
class Analysis:
    name: str
    python: str
    requirements: str | None  # project path: requirements.txt, or a folder with pyproject.toml
    workdir: str  # container path
    entry: list[str]  # the command, relative to workdir (e.g. ["python", "bot.py"])
    mounts: list[Mount]
    env: list[EnvVar] = field(default_factory=list)
    ports: list[int] = field(default_factory=list)
    apt: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    files: int = 0
    size: int = 0


@dataclass
class _Docker:
    python: str = ""
    workdir: str = ""
    cmd: list[str] = field(default_factory=list)
    entrypoint: list[str] = field(default_factory=list)
    expose: list[int] = field(default_factory=list)
    apt: list[str] = field(default_factory=list)
    copies: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class _Compose:
    name: str = ""
    env: dict[str, str] = field(default_factory=dict)
    env_files: list[str] = field(default_factory=list)
    volumes: list[str] = field(default_factory=list)
    ports: list[str] = field(default_factory=list)
    command: list[str] = field(default_factory=list)
    working_dir: str = ""


class _Zip:
    """The archive's useful files, relative to the project root."""

    def __init__(self, path: str) -> None:
        self.zf = zipfile.ZipFile(path)
        infos = [i for i in self.zf.infolist() if not i.is_dir() and not IGNORED.search(i.filename)]
        if not infos:
            raise ProjectError("the archive is empty")
        if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_UNZIPPED:
            raise ProjectError("the archive is too large")
        for i in infos:
            p = PurePosixPath(i.filename)
            link = (i.external_attr >> 16) & 0o170000 == 0o120000
            if p.is_absolute() or ".." in p.parts or link:
                raise ProjectError("unsafe path in the archive")
        tops = {PurePosixPath(i.filename).parts[0] for i in infos}
        single = next(iter(tops)) if len(tops) == 1 else None
        self.prefix = f"{single}/" if single and all("/" in i.filename for i in infos) else ""
        self.infos = {i.filename[len(self.prefix) :]: i for i in infos}
        self.size = sum(i.file_size for i in infos)

    def names(self) -> list[str]:
        return sorted(self.infos, key=lambda n: (n.count("/"), n))

    def text(self, name: str | None, limit: int = 512 * 1024) -> str:
        info = self.infos.get(name or "")
        if info is None or info.file_size > limit:
            return ""
        return self.zf.read(info).decode("utf-8", errors="replace")

    def find(self, *names: str) -> str | None:
        """The shallowest file with one of these names."""
        return next((n for n in self.names() if PurePosixPath(n).name in names), None)


def _python(version: str | None) -> str | None:
    m = re.search(r"3\.(\d{1,2})", version or "")
    if not m:
        return None
    wanted = f"3.{m.group(1)}"
    if wanted in SUPPORTED:
        return wanted
    return SUPPORTED[-1] if int(m.group(1)) > int(SUPPORTED[-1][2:]) else SUPPORTED[0]


def _command(value: str) -> list[str]:
    value = value.strip()
    if value.startswith("["):
        try:
            return [str(x) for x in json.loads(value)]
        except ValueError:
            pass
    return shlex.split(value)


def _dockerfile(text: str) -> _Docker:
    out = _Docker()
    for line in re.sub(r"\\\s*\n", " ", text).splitlines():  # continued lines joined
        words = line.strip().split(None, 1)
        if len(words) < 2 or words[0].startswith("#"):
            continue
        op, arg = words[0].upper(), words[1]
        if op == "FROM" and "python" in arg:
            out.python = arg
        elif op == "WORKDIR":
            out.workdir = arg.strip()
        elif op == "CMD":
            out.cmd = _command(arg)
        elif op == "ENTRYPOINT":
            out.entrypoint = _command(arg)
        elif op == "EXPOSE":
            out.expose += [int(p.split("/")[0]) for p in arg.split() if p.split("/")[0].isdigit()]
        elif op == "RUN" and "apt-get" in arg and "install" in arg:
            after = arg.split("install", 1)[1].split("&&")[0].split()
            out.apt += [w for w in after if not w.startswith("-") and PACKAGE.match(w)]
        elif op == "COPY":
            parts = [p for p in arg.split() if not p.startswith("--")]
            if len(parts) == 2:
                out.copies.append((parts[0], parts[1]))
    return out


def _compose(text: str) -> _Compose:
    try:
        doc = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return _Compose()
    services = doc.get("services") if isinstance(doc, dict) else None
    if not isinstance(services, dict) or not services:
        return _Compose()
    key, svc = next(iter(services.items()))
    svc = svc or {}
    env = svc.get("environment") or {}
    if isinstance(env, list):
        env = dict(e.split("=", 1) if "=" in e else (e, "") for e in env)
    env_files = svc.get("env_file") or []
    command = svc.get("command")
    return _Compose(
        name=str(doc.get("name") or svc.get("container_name") or key),
        env={str(k): "" if v is None else str(v) for k, v in env.items()},
        env_files=[env_files] if isinstance(env_files, str) else [str(f) for f in env_files],
        volumes=[str(v) for v in svc.get("volumes") or [] if isinstance(v, str)],
        ports=[str(p) for p in svc.get("ports") or []],
        command=_command(command) if isinstance(command, str) else [str(c) for c in command or []],
        working_dir=str(svc.get("working_dir") or ""),
    )


def _dotenv(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        if ENV_KEY.match(key.strip()):
            out[key.strip()] = value.strip().strip("\"'")
    return out


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", text.lower()).strip("-_")[:40] or "project"


def volume_name(mount: Mount) -> str:
    return _slug(mount.source.replace("/", "-")) if mount.source else "project"


def _mounts(z: _Zip, docker: _Docker, compose: _Compose) -> list[Mount]:
    """Where the code goes: the compose mounts, else the Dockerfile's COPY of folders,
    else the whole project at /app."""
    names = z.names()
    mounts: list[Mount] = []
    for spec in compose.volumes:
        src, _, rest = spec.partition(":")
        target = rest.split(":")[0]
        if src.startswith(".") and target.startswith("/"):
            source = "" if src in (".", "./") else str(PurePosixPath(src)).lstrip("./")
            mounts.append(Mount(source.strip("/"), target, False))
    if not mounts:
        for src, dst in docker.copies:
            source = src.strip("./").strip("/")
            is_dir = source == "" or any(n.startswith(f"{source}/") for n in names)
            if dst.startswith("/") and is_dir:
                mounts.append(Mount(source, dst.rstrip("/") or "/", False))
    if not mounts:
        mounts.append(Mount("", "/app", False))
    for mount in mounts:
        inside = [n for n in names if mount.source == "" or n.startswith(f"{mount.source}/")]
        mount.data = bool(mount.source) and not any(n.endswith(".py") for n in inside)
    return mounts


def container_path(mounts: list[Mount], project_path: str) -> str | None:
    """Where a project file shows up in the container (None: not mounted)."""
    matching = [m for m in mounts if m.source == "" or project_path == m.source
                or project_path.startswith(f"{m.source}/")]  # fmt: skip
    if not matching:
        return None
    best = max(matching, key=lambda m: len(m.source))
    rest = project_path[len(best.source) :].lstrip("/") if best.source else project_path
    return str(PurePosixPath(best.target) / rest) if rest and rest != "." else best.target


def _environment(z: _Zip, compose: _Compose) -> list[EnvVar]:
    """Compose values, .env files, examples, then what the code reads."""
    env: dict[str, EnvVar] = {}
    dotenv: dict[str, str] = {}
    for f in [*compose.env_files, ".env"]:
        dotenv.update(_dotenv(z.text(z.find(PurePosixPath(f).name))))
    for key, value in compose.env.items():
        ref = re.fullmatch(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)(?::?-[^}]*)?\}?", value)
        env[key] = EnvVar(key, dotenv.get(ref.group(1), "") if ref else value, source="compose")
    for key, value in dotenv.items():
        env.setdefault(key, EnvVar(key, value, source=".env"))
    for example in (".env.example", ".env.sample", "env.example"):
        for key, value in _dotenv(z.text(z.find(example))).items():
            env.setdefault(key, EnvVar(key, value, source=example))
    for n in z.names():
        if n.endswith(".py"):
            for m in GETENV.finditer(z.text(n, 256 * 1024)):
                key = m.group(1) or m.group(3)
                env.setdefault(key, EnvVar(key, m.group(2) or "", source=n))
    for var in env.values():
        var.secret = bool(SECRET.search(var.key))
    env.pop("TZ", None)  # set from the host's timezone
    return sorted(env.values(), key=lambda e: e.key)


def analyze(path: str, fallback_name: str = "") -> Analysis:
    z = _Zip(path)
    names = z.names()
    notes: list[str] = []
    dockerfile = z.find("Dockerfile")
    docker = _dockerfile(z.text(dockerfile)) if dockerfile else _Docker()
    compose_file = z.find(*COMPOSE_FILES)
    compose = _compose(z.text(compose_file)) if compose_file else _Compose()
    if dockerfile:
        notes.append("Dockerfile")
    if compose.name:
        notes.append(str(compose_file))

    python = _python(docker.python)
    for candidate in (".python-version", "runtime.txt"):
        python = python or _python(z.text(z.find(candidate)))
    if python is None and (pyproject := z.find("pyproject.toml")):
        m = re.search(r"requires-python\s*=\s*[\"']([^\"']+)", z.text(pyproject))
        python = _python(m.group(1) if m else None)
    python = python or DEFAULT_PYTHON

    mounts = _mounts(z, docker, compose)

    requirements = z.find("requirements.txt")
    if requirements is None and (pyproject := z.find("pyproject.toml")):
        folder = str(PurePosixPath(pyproject).parent)
        requirements = "." if folder in ("", ".") else folder
    if requirements is None and z.find("Pipfile"):
        notes.append("Pipfile: not supported, add a requirements.txt")

    workdir = compose.working_dir or docker.workdir
    entry = compose.command or [*docker.entrypoint, *docker.cmd]
    if not entry and (procfile := z.find("Procfile")):
        for line in z.text(procfile).splitlines():
            if ":" in line:
                entry = shlex.split(line.split(":", 1)[1])
                notes.append("Procfile")
                break
    if not entry:
        scripts = [n for n in names if n.endswith(".py") and MAIN.search(z.text(n, 256 * 1024))]
        scripts.sort(key=lambda n: (n.count("/"), PurePosixPath(n).name not in PREFERRED, n))
        if scripts:
            where = container_path(mounts, scripts[0]) or f"/app/{scripts[0]}"
            workdir = workdir or str(PurePosixPath(where).parent)
            entry = ["python", PurePosixPath(where).name]
            notes.append(f"{scripts[0]} (if __name__ == '__main__')")
    if not entry:
        raise ProjectError("no script to run found (no Dockerfile CMD, compose command, Procfile "
                           "or file with if __name__ == '__main__')")  # fmt: skip
    workdir = workdir or mounts[0].target
    if requirements and requirements != "." and container_path(mounts, requirements) is None:
        mounts.append(Mount("", "/project", False))  # dependencies outside the mounted code

    ports = list(docker.expose)
    for spec in compose.ports:
        tail = spec.rsplit(":", 1)[-1].split("/")[0]
        if tail.isdigit():
            ports.append(int(tail))
    if "--port" in entry[:-1] and entry[entry.index("--port") + 1].isdigit():
        ports.append(int(entry[entry.index("--port") + 1]))

    name = compose.name or fallback_name or "Python"
    return Analysis(
        name=re.sub(r"[_-](stack|compose)$", "", name), python=python, requirements=requirements,
        workdir=workdir, entry=entry, mounts=mounts, env=_environment(z, compose),
        ports=sorted(set(ports)), apt=sorted(set(docker.apt)), notes=notes, files=len(names),
        size=z.size,
    )  # fmt: skip
