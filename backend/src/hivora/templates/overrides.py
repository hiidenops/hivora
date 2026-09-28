"""Advanced settings of an app, per service, applied on top of its template.

Kept with each revision (so restores and upgrades carry them). Deliberately
bounded: extra folders live under the app's own volume directory and ports
are published like the template's, so an operator cannot mount the host.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ENV_KEY = r"^[A-Za-z_][A-Za-z0-9_]{0,127}$"
VOLUME_NAME = r"^[a-z0-9][a-z0-9_-]{0,62}$"
CONTAINER_PATH = r"^/[A-Za-z0-9._/@:+-]{0,500}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExtraPort(_Strict):
    container: Annotated[int, Field(ge=1, le=65535)]
    host: Annotated[int, Field(ge=1, le=65535)]
    protocol: Literal["tcp", "udp"] = "tcp"
    exposure: Literal["lan", "public"] = "lan"


class ExtraVolume(_Strict):
    name: Annotated[str, Field(pattern=VOLUME_NAME)]  # /srv/hivora/<app>/<name>
    target: Annotated[str, Field(pattern=CONTAINER_PATH)]
    read_only: bool = False

    @model_validator(mode="after")
    def _no_dotdot(self) -> "ExtraVolume":
        if ".." in self.target.split("/"):
            raise ValueError("target must not contain ..")
        return self


class ServiceOverrides(_Strict):
    env: dict[Annotated[str, Field(pattern=ENV_KEY)], Annotated[str, Field(max_length=4096)]] = {}
    ports: list[ExtraPort] = Field(default=[], max_length=20)
    volumes: list[ExtraVolume] = Field(default=[], max_length=20)
    cpus: Annotated[float, Field(gt=0, le=256)] | None = None  # e.g. 1.5 cores
    memory: Annotated[str, Field(pattern=r"^\d{1,6}(\.\d{1,3})?[kmg]$")] | None = None  # "2g"
    restart: Literal["no", "always", "unless-stopped", "on-failure"] | None = None

    @property
    def empty(self) -> bool:
        return self == ServiceOverrides()


class Overrides(_Strict):
    services: dict[str, ServiceOverrides] = {}

    def of(self, service: str) -> ServiceOverrides | None:
        return self.services.get(service)
