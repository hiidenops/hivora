"""Runtime configuration, read from environment variables prefixed with ``HIVORA_``."""

from functools import cached_property
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HIVORA_", frozen=True)

    # Mounted at the same path inside and outside the container, so generated
    # compose files can reference absolute host paths.
    data_dir: Path = Path("/opt/hivora/data")
    volumes_root: Path = Path("/srv/hivora")

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
