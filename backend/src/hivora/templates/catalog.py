"""Template catalog loaded from a directory of ``<slug>/template.yaml`` files.

Alpha: the official templates ship with Hivora. Git/HTTPS sources and
ed25519-signed indexes come later.
"""

import hashlib
import logging
import platform
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError as PydanticValidationError

from hivora.core.errors import NotFoundError, ValidationError
from hivora.templates.schema import Template

logger = logging.getLogger(__name__)

TEMPLATE_FILE = "template.yaml"
CUSTOM_SOURCE = "custom"
_ARCH = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}


class TemplateNotFoundError(NotFoundError):
    code = "template_not_found"


class TemplateInvalidError(ValidationError):
    code = "template_invalid"


def normalize_arch(machine: str) -> str:
    return _ARCH.get(machine.lower(), machine.lower())


def host_arch() -> str:
    """This machine's own architecture. The running panel asks its catalog instead
    (``Catalog.host_arch``), which knows what Docker reports."""
    return normalize_arch(platform.machine())


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    template: Template
    manifest: str  # raw YAML, stored verbatim in template_version
    checksum: str  # sha256 of the manifest
    source: str

    @property
    def slug(self) -> str:
        return self.template.metadata.slug

    def supports(self, arch: str) -> bool:
        return arch in self.template.requirements.arch


def parse_template(manifest: str, *, require_pinned: bool) -> Template:
    try:
        template = Template.model_validate(yaml.safe_load(manifest))
        if require_pinned:
            template.check_pinned()
    except (PydanticValidationError, ValueError, yaml.YAMLError) as exc:
        raise TemplateInvalidError(str(exc)) from exc
    return template


class Catalog:
    def __init__(self) -> None:
        self._entries: dict[str, CatalogEntry] = {}
        self._custom: dict[str, CatalogEntry] = {}  # free images: resolvable, never listed
        self._docker_arch: str | None = None  # what Docker reports, set at startup

    def set_host_arch(self, machine: str) -> None:
        """Architecture reported by Docker (the source of truth), set at startup."""
        self._docker_arch = normalize_arch(machine) if machine else None

    def host_arch(self) -> str:
        """The host's architecture: Docker's, else this machine's own."""
        return self._docker_arch or host_arch()

    def add_custom(self, manifest: str) -> CatalogEntry:
        """Register a template generated for a free image (pinned by digest)."""
        template = parse_template(manifest, require_pinned=True)
        entry = CatalogEntry(template, manifest, hashlib.sha256(manifest.encode()).hexdigest(),
                             CUSTOM_SOURCE)  # fmt: skip
        self._custom[template.metadata.slug] = entry
        return entry

    def load_directory(self, directory: Path, *, source: str = "official") -> list[str]:
        """Load every template; invalid ones are logged and skipped. Returns errors."""
        errors = []
        for path in sorted(directory.glob(f"*/{TEMPLATE_FILE}")):
            manifest = path.read_text(encoding="utf-8")
            try:
                template = parse_template(manifest, require_pinned=source == "official")
            except TemplateInvalidError as exc:
                logger.error("invalid template", extra={"path": str(path), "error": str(exc)})
                errors.append(f"{path}: {exc}")
                continue
            if template.metadata.slug != path.parent.name:
                errors.append(f"{path}: slug does not match its directory")
                continue
            checksum = hashlib.sha256(manifest.encode()).hexdigest()
            self._entries[template.metadata.slug] = CatalogEntry(
                template, manifest, checksum, source
            )
        return errors

    def get(self, slug: str) -> CatalogEntry:
        try:
            return self._entries.get(slug) or self._custom[slug]
        except KeyError:
            raise TemplateNotFoundError(slug) from None

    def entries(self) -> list[CatalogEntry]:
        return sorted(self._entries.values(), key=lambda e: e.template.metadata.name.lower())

    def custom_entries(self) -> list[CatalogEntry]:
        """The templates generated for free images (not listed by entries())."""
        return list(self._custom.values())
