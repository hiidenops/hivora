"""Runtime configuration, read from environment variables prefixed with ``HIVORA_``."""

from functools import cached_property
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HIVORA_", frozen=True)

    # Mounted at the same path inside and outside the container, so generated
    # compose files can reference absolute host paths.
    data_dir: Path = Path("/opt/hivora/data")
    volumes_root: Path = Path("/srv/hivora")

    # Static frontend build (Next.js export), served when present.
    frontend_dir: Path = Path("/app/frontend")

    # Official templates shipped with Hivora (the repo's templates/ in development).
    catalog_dir: Path = Path("/app/templates")

    # Host facts used by templates (`host.*`) and port bindings.
    host_public_ip: str | None = None
    host_lan_ip: str | None = None
    host_vpn_ip: str | None = None
    timezone: str = "UTC"
    puid: int = 1000
    pgid: int = 1000

    job_workers: int = 2

    # How the panel is reached, as the installer published it (install.env, passed as
    # HIVORA_ACCESS; never stored). "public": every account needs TOTP (auth.totp).
    access: Literal["lan", "public", "vpn", "vpn+lan"] = "lan"
    # The games of the catalog (install.env, HIVORA_GAMES; never stored). Off: hidden from
    # the catalog and refused to new deploys; game apps already there keep running.
    games: bool = True
    # The admin VPN (vpn modes, vpn.admin): address and UDP port its clients connect to.
    # No host: the public address, else the LAN one.
    admin_vpn_host: str | None = None
    admin_vpn_port: int = Field(default=51820, ge=1, le=65535)

    # The installed version's notes (shipped in the image; the repository's in development).
    changelog_path: Path = Path("/app/CHANGELOG.md")

    # Where this version's source code is (AGPL-3.0, section 13): a modified version
    # points to its own.
    source_url: str = Field(default="https://github.com/hiidenops/hivora",
                            pattern=r"^https?://[^\s]{3,500}$")  # fmt: skip

    # How to run Compose v2: the docker CLI plugin, or the standalone binary
    # (the Hivora image ships only that: HIVORA_COMPOSE_CMD='["docker-compose"]').
    compose_cmd: list[str] = ["docker", "compose"]

    # HTTPS (the image's default): a self-signed certificate is created in
    # <data>/tls/ on first start unless one is already there. False: plain HTTP
    # (behind a reverse proxy that terminates TLS).
    tls: bool = True
    port: int = 8443

    session_idle_hours: int = 12
    session_max_days: int = 30
    # Development over plain HTTP only: drops the Secure cookie flag.
    dev_insecure_cookies: bool = False

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "text"] = "json"

    @cached_property
    def db_path(self) -> Path:
        return self.data_dir / "hivora.db"

    @cached_property
    def secret_key_path(self) -> Path:
        return self.data_dir / "secret.key"

    @cached_property
    def apps_dir(self) -> Path:
        return self.data_dir / "apps"

    @cached_property
    def templates_dir(self) -> Path:
        return self.data_dir / "templates"
