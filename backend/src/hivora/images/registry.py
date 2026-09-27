"""Read an image from its registry (no Docker socket): digest, platforms, declared config.

Anonymous pull tokens (Docker Hub, ghcr.io and any registry speaking the
distribution API). Used to pin a free image by digest, check it runs on this
machine and pre-fill its ports, volumes and environment.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from hivora.core.errors import NotFoundError, ValidationError

ACCEPT = ", ".join([
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
])  # fmt: skip
REF = re.compile(
    r"^(?:(?P<registry>[a-z0-9.-]+\.[a-z]{2,}(?::\d+)?|localhost(?::\d+)?)/)?"
    r"(?P<repo>[a-z0-9]+(?:[._/-][a-z0-9]+)*)(?::(?P<tag>[\w][\w.-]{0,127}))?$"
)
MAX_JSON = 4 * 1024 * 1024


class ImageNotFoundError(NotFoundError):
    code = "image_not_found"


class InvalidImageRefError(ValidationError):
    code = "invalid_image_ref"


@dataclass(frozen=True, slots=True)
class ImageRef:
    registry: str  # API host
    repo: str
    tag: str

    @property
    def name(self) -> str:
        """As written in a compose file (Docker Hub without host, library/ dropped)."""
        if self.registry == "registry-1.docker.io":
            return self.repo.removeprefix("library/")
        return f"{self.registry}/{self.repo}"


@dataclass(frozen=True, slots=True)
class ImageInfo:
    ref: ImageRef
    digest: str
    platforms: list[str]  # linux architectures (e.g. ["amd64", "arm64"])
    ports: list[tuple[int, str]] = field(default_factory=list)  # (port, protocol)
    volumes: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


def parse_ref(text: str) -> ImageRef:
    m = REF.match(text.strip().removeprefix("docker.io/"))
    if not m:
        raise InvalidImageRefError("invalid image name", ref=text[:200])
    registry = m["registry"] or "registry-1.docker.io"
    repo = m["repo"]
    if registry == "registry-1.docker.io" and "/" not in repo:
        repo = f"library/{repo}"
    return ImageRef(registry, repo, m["tag"] or "latest")


def _config_of(config: dict[str, Any]) -> tuple[list[tuple[int, str]], list[str], dict[str, str]]:
    c = config.get("config") or {}
    ports = []
    for spec in c.get("ExposedPorts") or {}:
        port, _, proto = spec.partition("/")
        if port.isdigit():
            ports.append((int(port), proto or "tcp"))
    env = dict(e.split("=", 1) for e in c.get("Env") or [] if "=" in e)
    env.pop("PATH", None)
    return sorted(ports), sorted(c.get("Volumes") or {}), env


class Registry:
    def __init__(self, timeout: float = 15) -> None:
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    async def _get(self, http: aiohttp.ClientSession, url: str, ref: ImageRef,
                   token: list[str]) -> tuple[dict[str, Any], str]:  # fmt: skip
        headers = {"Accept": ACCEPT}
        for _ in range(2):
            if token:
                headers["Authorization"] = f"Bearer {token[0]}"
            async with http.get(url, headers=headers) as r:
                if r.status == 401 and not token:
                    token.append(await self._token(http, r.headers.get("WWW-Authenticate", "")))
                    continue
                if r.status in (401, 403, 404):
                    raise ImageNotFoundError("image not found (or private)", ref=ref.name)
                r.raise_for_status()
                body = b""
                async for chunk in r.content.iter_chunked(65536):  # read() may stop early
                    body += chunk
                    if len(body) > MAX_JSON:
                        raise ValidationError("registry answer too large", ref=ref.name)
                return json.loads(body), r.headers.get("Docker-Content-Digest", "")
        raise ImageNotFoundError("registry refused the anonymous token", ref=ref.name)

    async def _token(self, http: aiohttp.ClientSession, challenge: str) -> str:
        params = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
        realm = params.pop("realm", "")
        if not realm.startswith("https://"):
            raise ImageNotFoundError("registry without anonymous access")
        async with http.get(realm, params=params) as r:
            r.raise_for_status()
            data = await r.json()
        return str(data.get("token") or data.get("access_token") or "")

    async def inspect(self, text: str, arch: str) -> ImageInfo:
        ref = parse_ref(text)
        base = f"https://{ref.registry}/v2/{ref.repo}"
        token: list[str] = []
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as http:
                doc, digest = await self._get(http, f"{base}/manifests/{ref.tag}", ref, token)
                manifests = doc.get("manifests")
                if manifests is not None:  # multi-platform index: config of this machine's arch
                    linux = [m for m in manifests if (m.get("platform") or {}).get("os") == "linux"]
                    platforms = sorted({m["platform"]["architecture"] for m in linux})
                    pick = next((m for m in linux if m["platform"]["architecture"] == arch), None)
                    if pick is None:
                        return ImageInfo(ref, digest, platforms)
                    doc, _ = await self._get(http, f"{base}/manifests/{pick['digest']}", ref, token)
                else:
                    platforms = []
                config, _ = await self._get(
                    http, f"{base}/blobs/{doc['config']['digest']}", ref, token
                )
        except (aiohttp.ClientError, TimeoutError, KeyError, ValueError) as exc:
            raise ImageNotFoundError(f"registry unavailable: {exc}", ref=ref.name) from exc
        if not platforms:  # single-platform image: its config says which
            platforms = [str(config.get("architecture") or "")]
        ports, volumes, env = _config_of(config)
        return ImageInfo(ref, digest, platforms, ports, volumes, env)
