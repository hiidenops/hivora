"""Pydantic model of the ``hivora/v1`` template format (docs section 8).

Unknown keys are rejected so that typos fail loudly at load time, and every
``{{ }}`` expression is checked against the declared form and services.
"""

import re
from collections.abc import Iterator
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from hivora.templates.expressions import find_expressions

SLUG = r"^[a-z0-9][a-z0-9-]{0,62}$"
FIELD_ID = r"^[a-z][a-z0-9_]{0,62}$"
SEMVER = r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$"
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")

FieldType = Literal[
    "string", "text", "integer", "number", "boolean", "select", "secret",
    "port", "path", "email", "url", "domain",
]  # fmt: skip
Exposure = Literal["public", "lan", "vpn", "internal"]
Language = Literal["fr", "en"]
# User-facing text: a plain string, or one per language (the UI falls back to "en").
Localized = str | dict[Language, str]


def iter_strings(value: Any) -> Iterator[str]:
    """Every string nested in dicts/lists (keys excluded)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from iter_strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from iter_strings(v)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class IconSource(_Strict):
    """Where Hivora downloads the icon from (once, then served from its cache)."""

    url: Annotated[str, Field(pattern=r"^https://")] | None = None
    steam_appid: Annotated[int, Field(gt=0)] | None = None

    @model_validator(mode="after")
    def _one_source(self) -> "IconSource":
        if (self.url is None) == (self.steam_appid is None):
            raise ValueError("icon needs exactly one of url or steam_appid")
        return self

    @property
    def download_url(self) -> str:
        if self.steam_appid is not None:
            return (
                f"https://cdn.cloudflare.steamstatic.com/steam/apps/{self.steam_appid}/header.jpg"
            )
        assert self.url is not None
        return self.url


class Metadata(_Strict):
    slug: Annotated[str, Field(pattern=SLUG)]
    name: str
    version: Annotated[str, Field(pattern=SEMVER)]
    category: Literal["games", "media", "productivity", "services", "network", "development"]
    tags: list[str] = []
    icon: IconSource | None = None
    description: Localized = ""
    links: dict[str, str] = {}
    maintainer: str | None = None
    license: str | None = None
    source: str | None = None


class ResourceReq(_Strict):
    min: str | None = None
    recommended: str | None = None


class Requirements(_Strict):
    arch: list[Literal["amd64", "arm64"]]  # where the template runs (images checked at deploy)
    memory: ResourceReq | None = None
    cpu: ResourceReq | None = None
    disk: ResourceReq | None = None


class SelectOption(_Strict):
    value: str | int
    label: Localized


class Generate(_Strict):
    length: Annotated[int, Field(ge=12, le=128)] = 24


class Suggestion(_Strict):
    value: str
    description: Localized


class FormField(_Strict):
    id: Annotated[str, Field(pattern=FIELD_ID)]
    label: Localized
    type: FieldType
    required: bool = False  # for booleans: the box must be checked (e.g. EULA)
    default: Any = None
    pattern: str | None = None
    help: Localized | None = None
    group: Localized | None = None  # section title; consecutive fields share it
    show_if: dict[str, Any] | None = Field(default=None, alias="showIf")
    range: tuple[float, float] | None = None
    options: list[SelectOption] | None = None
    generate: Generate | None = None
    # Secret left empty -> value of this global secret setting (declarative).
    from_setting: Literal["curseforge_api_key"] | None = None
    # Choices fetched by Hivora from a known source (rendered as a list).
    options_from: Literal["minecraft_versions", "steam_branches"] | None = None
    options_param: Annotated[str, Field(pattern=r"^\d{1,10}$")] | None = None  # e.g. Steam app id
    # Text fields: insertable lines shown next to the field (e.g. properties).
    suggestions: list["Suggestion"] = []
    # Changing this value on an existing app wipes its volumes (e.g. a game
    # version whose saves cannot be read by another one). Always confirmed.
    reset_data_on_change: bool = False

    @model_validator(mode="after")
    def _check(self) -> "FormField":
        if self.type == "select" and not self.options:
            raise ValueError(f"select field {self.id!r} needs options")
        if (self.options_from == "steam_branches") != bool(self.options_param):
            raise ValueError(f"field {self.id!r}: steam_branches needs options_param (app id)")
        if (self.generate or self.from_setting) and self.type != "secret":
            raise ValueError(
                f"only secret fields can be generated or taken from a setting ({self.id!r})"
            )
        if self.type == "secret" and self.default is not None:
            raise ValueError(f"secret field {self.id!r} cannot have a default")
        return self


class Form(_Strict):
    basic: list[FormField] = []
    advanced: list[FormField] = []

    @property
    def fields(self) -> list[FormField]:
        return [*self.basic, *self.advanced]


class PortSpec(_Strict):
    container: Annotated[int, Field(ge=1, le=65535)]
    host: int | str | None = None  # None: same as container; may be an expression
    protocol: Literal["tcp", "udp"] = "tcp"
    purpose: Literal["web", "game", "rcon", "query", "other"] = "other"
    exposure: Exposure = "lan"


class VolumeSpec(_Strict):
    name: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")]
    target: str
    backup: bool = False
    read_only: bool = False
    reset_keep: list[Annotated[str, Field(pattern=r"^[A-Za-z0-9._*-]+$")]] = []  # top-level globs
    # Fixed UID:GID of an image that cannot follow PUID/PGID (default: PUID/PGID).
    owner: Annotated[str, Field(pattern=r"^\d{1,10}:\d{1,10}$")] | None = None


Arch = Literal["amd64", "arm64"]


class ArchVariant(_Strict):
    """Another image for one CPU architecture (e.g. no ARM build of the default one)."""

    image: str
    tag: str
    env: dict[str, str | int | bool] = {}  # merged over the service env


def version_tuple(value: str) -> tuple[int, ...] | None:
    """ "1.20.4" -> (1, 20, 4); None for anything else (LATEST, snapshots...)."""
    if not re.fullmatch(r"\d+(\.\d+)*", value):
        return None
    return tuple(int(n) for n in value.split("."))


class TagChoice(_Strict):
    """An image tag picked by a form value, exact or as a version range."""

    tag: str
    value: str | None = None  # this exact value
    below: str | None = None  # versions lower than this one (choices go in ascending order)
    frozen: bool = False  # a deliberately old version: skipped by the freshness check

    @model_validator(mode="after")
    def _one_rule(self) -> "TagChoice":
        if (self.value is None) == (self.below is None):
            raise ValueError("a tag choice needs exactly one of value or below")
        if self.below is not None and version_tuple(self.below) is None:
            raise ValueError(f"below: {self.below!r} is not a version number")
        return self


class TagSelect(_Strict):
    """The image tag follows a form field (e.g. game version -> Java runtime)."""

    field: str
    choices: list[TagChoice]

    def pick(self, value: object) -> str | None:
        text = "" if value is None else str(value)
        version = version_tuple(text)
        for c in self.choices:
            below = version_tuple(c.below) if c.below else None
            if c.value == text or (below and version is not None and version < below):
                return c.tag
        return None


class FileSpec(_Strict):
    """A file placed in the container at start (Compose ``configs``, read-only).

    Its content may use expressions, secrets included (resolved from ``.env``).
    """

    target: Annotated[str, Field(pattern=r"^/[A-Za-z0-9._/ -]+$")]
    content: str

    @model_validator(mode="after")
    def _no_parent(self) -> "FileSpec":
        if ".." in self.target.split("/"):
            raise ValueError(f"{self.target!r}: no '..' in a file target")
        return self


class ServiceSpec(_Strict):
    role: Literal["main", "database", "cache", "sidecar"] = "main"
    image: str
    tag: str
    env: dict[str, str | int | bool] = {}
    arch: dict[Arch, ArchVariant] = {}
    tag_select: TagSelect | None = None  # default: ``tag``
    files: list[FileSpec] = []
    # Narrow grants for network tools (WireGuard); never `privileged` (CLAUDE.md).
    cap_add: list[Literal["NET_ADMIN"]] = []
    sysctls: dict[
        Literal["net.ipv4.ip_forward", "net.ipv4.conf.all.src_valid_mark"], Literal[0, 1]
    ] = {}
    shm_size: Annotated[str, Field(pattern=r"^\d{1,5}[mg]b$")] | None = None
    # Freshness check (scripts/check_images.py): "minor" keeps the major version
    # (a database upgrade needs a migration); frozen: pinned by the app's own vendor.
    track: Literal["all", "minor"] = "all"
    frozen: bool = False
    ports: list[PortSpec] = []
    volumes: list[VolumeSpec] = []
    command: str | list[str] | None = None
    healthcheck: dict[str, Any] | None = None
    depends_on: list[str] = []
    user: str | None = None
    stdin_open: bool = False  # needed by the game server console (attach)
    # Time to save and exit on stop before Docker kills the server (e.g. "120s").
    stop_grace_period: Annotated[str, Field(pattern=r"^\d{1,4}s$")] | None = None
    tty: bool = False

    @property
    def image_ref(self) -> str:
        return f"{self.image}:{self.tag}"

    def for_values(self, values: dict[str, Any]) -> "ServiceSpec":
        tag = self.tag_select.pick(values.get(self.tag_select.field)) if self.tag_select else None
        return self.model_copy(update={"tag": tag}) if tag else self

    def for_arch(self, arch: str) -> "ServiceSpec":
        v = self.arch.get(arch)  # type: ignore[call-overload]
        if v is None:
            return self
        return self.model_copy(
            update={"image": v.image, "tag": v.tag, "env": {**self.env, **v.env}}
        )


class Access(_Strict):
    web: str | None = None
    game: str | None = None
    credentials: dict[str, str] = {}


class Backup(_Strict):
    volumes: list[str] = []
    pause: bool = False


class Update(_Strict):
    strategy: Literal["manual", "auto-patch", "auto-minor"] = "manual"


class GameCommand(_Strict):
    command: str
    description: Localized


def _relative(path: str) -> str:
    """A path inside a volume: relative, no `..`, plain characters."""
    if (
        path.startswith("/")
        or ".." in path.split("/")
        or not re.fullmatch(r"[A-Za-z0-9._/-]*", path)
    ):
        raise ValueError(f"{path!r}: expected a relative path inside the volume")
    return path


RelPath = Annotated[str, AfterValidator(_relative)]


class GamePlayers(_Strict):
    """Who is online: a command run in the main service, or a Steam A2S query."""

    command: list[str] | None = None  # e.g. ["rcon-cli", "list"]
    # Parser of the command output: Minecraft's `list`, or CSV (header, then one row per player).
    format: Literal["minecraft", "csv"] | None = None
    a2s_port: int | None = None  # container port answering A2S (must be published)

    @model_validator(mode="after")
    def _check(self) -> "GamePlayers":
        if bool(self.command) == bool(self.a2s_port) or bool(self.command) != bool(self.format):
            raise ValueError("players: either command + format, or a2s_port")
        return self


class GameList(_Strict):
    """A player list (whitelist, admins, bans) stored in a file of the saves volume."""

    id: Annotated[str, Field(pattern=FIELD_ID)]
    label: Localized
    file: RelPath
    format: Literal["json_names", "lines"] = "lines"  # [{"name": ...}] or one entry per line
    # Commands run in the running server ("{name}" is replaced); none: the file is edited.
    add: list[str] = []
    remove: list[str] = []
    enabled_field: str | None = None  # boolean form field that turns the list on
    extra_key: str | None = None  # json_names: shown next to the name (e.g. "level")
    name_pattern: str = r"^[A-Za-z0-9_]{3,16}$"


class GameSaves(_Strict):
    """Worlds/saves: folders holding ``marker``, or files grouped by name (``*.ext``)."""

    volume: str = "data"
    path: RelPath = ""
    marker: str = "level.dat"
    siblings: list[str] = []  # suffixed folders belonging to a world (e.g. "_nether")
    active_field: str | None = None  # form field naming the active world
    flush: list[str] = []  # command saving the running world before a download

    @property
    def by_file(self) -> bool:
        return self.marker.startswith("*.")


class Game(_Strict):
    # Server console: command run (with a TTY) in the main service, e.g. ["rcon-cli"].
    console: list[str] | None = None
    commands: list[GameCommand] = []  # the console's command guide
    # Who runs players/lists/saves commands: the container's user, or PUID:PGID
    # (a server dropped to PUID cannot be reached from root without ptrace).
    run_as: Literal["container", "app"] = "container"
    players: GamePlayers | None = None
    lists: list[GameList] = []
    saves: GameSaves | None = None
    max_players: int | str | None = None
    stop_command: str | None = None  # graceful stop through the console


class Defaults(_Strict):
    zone: str | None = None
    restart: Literal["no", "always", "unless-stopped", "on-failure"] = "unless-stopped"


class Template(_Strict):
    api_version: Literal["hivora/v1"] = Field(alias="apiVersion")
    kind: Literal["Template"]
    metadata: Metadata
    requirements: Requirements
    form: Form = Form()
    services: Annotated[dict[str, ServiceSpec], Field(min_length=1)]
    access: Access | None = None
    backup: Backup | None = None
    update: Update | None = None
    game: Game | None = None
    defaults: Defaults = Defaults()
    # Form fields highlighted on the app page (e.g. server type, version, memory).
    summary: list[str] = []

    @property
    def main_service(self) -> str:
        return next(
            (n for n, s in self.services.items() if s.role == "main"), next(iter(self.services))
        )

    @model_validator(mode="after")
    def _check_references(self) -> "Template":
        fields = {f.id: f for f in self.form.fields}
        if len(fields) != len(self.form.fields):
            raise ValueError("duplicate form field ids")
        if unknown := set(self.summary) - set(fields):
            raise ValueError(f"summary lists unknown fields {sorted(unknown)}")
        if self.game:
            for ref in (
                *(gl.enabled_field for gl in self.game.lists),
                self.game.saves.active_field if self.game.saves else None,
            ):
                if ref and ref not in fields:
                    raise ValueError(f"game: unknown form field {ref!r}")
            main = self.services.get(self.main_service)
            if (
                self.game.saves
                and main
                and self.game.saves.volume not in {v.name for v in main.volumes}
            ):
                raise ValueError("game.saves: unknown volume of the main service")
        names = set(self.services)
        for name, svc in self.services.items():
            if svc.tag_select and (svc.arch or svc.tag_select.field not in fields):
                raise ValueError(f"service {name!r}: tag_select needs a form field and no arch")
            if extra := set(svc.arch) - set(self.requirements.arch):
                raise ValueError(f"service {name!r}: image for unsupported arch {sorted(extra)}")
            if unknown := set(svc.depends_on) - names:
                raise ValueError(f"service {name!r} depends on unknown {sorted(unknown)}")
        exprs = (e for text in iter_strings(self.model_dump()) for e in find_expressions(text))
        for expr in exprs:
            ns, rest = expr.namespace, expr.path[1:]
            if ns in ("form", "secret"):
                field = fields.get(rest[0])
                if field is None or len(rest) != 1:
                    raise ValueError(f"{expr.source!r}: unknown form field")
                if (ns == "secret") != (field.type == "secret"):
                    raise ValueError(f"{expr.source!r}: use secret.* for secret fields only")
            elif ns == "service" and (rest[0] not in names or rest[1:] != ("host",)):
                raise ValueError(f"{expr.source!r}: expected service.<name>.host")
        return self

    def check_pinned(self) -> None:
        """Official templates must pin every image by digest."""
        for name, svc in self.services.items():
            choices = svc.tag_select.choices if svc.tag_select else []
            for tag in (svc.tag, *(v.tag for v in svc.arch.values()), *(c.tag for c in choices)):
                if not DIGEST.search(tag):
                    raise ValueError(f"service {name!r}: tag must be pinned by digest")
