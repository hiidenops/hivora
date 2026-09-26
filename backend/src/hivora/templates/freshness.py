"""Are the images pinned by the templates still the newest ones? (scripts/check_images.py)

A versioned tag (``2026.9.2-java25``, ``v1.9.10``) is compared with the newest
tag of the same shape (digits may change, the rest may not); a moving tag
(``latest``, ``stable``) with the digest the registry serves for it today.
"""

import re
from dataclasses import dataclass

from hivora.templates.catalog import Catalog


@dataclass(frozen=True, slots=True)
class Pin:
    template: str
    image: str
    tag: str  # without the digest
    digest: str


@dataclass(frozen=True, slots=True)
class Finding:
    pin: Pin
    newest: str  # newer tag, or the same tag when only its digest moved


def pins(catalog: Catalog) -> list[Pin]:
    out = []
    for entry in catalog.entries():
        for svc in entry.template.services.values():
            choices = svc.tag_select.choices if svc.tag_select else []
            refs = [(svc.image, svc.tag), *((v.image, v.tag) for v in svc.arch.values()),
                    *((svc.image, c.tag) for c in choices)]  # fmt: skip
            for image, ref in refs:
                tag, _, digest = ref.partition("@")
                out.append(Pin(entry.slug, image, tag, digest))
    return out


# A number glued to a word is part of the variant, not of the version:
# "java25" stays, while "v1.9", "vanilla-1.4.5.8" and "2_1_latest" vary.
_VERSION_NUMBER = re.compile(r"(?:(?<=^v)|(?<![A-Za-z0-9]))\d+")


def shape(tag: str) -> re.Pattern[str] | None:
    """Same tag with any version numbers; None for a moving tag (no version)."""
    parts = _VERSION_NUMBER.split(tag)
    if len(parts) == 1:
        return None
    return re.compile("^" + r"\d+".join(re.escape(p) for p in parts) + "$")


def version_key(tag: str) -> tuple[int, ...]:
    return tuple(int(n) for n in _VERSION_NUMBER.findall(tag))


def newer(pin: Pin, published: dict[str, str]) -> Finding | None:
    """``published``: tag -> digest, as the registry lists them."""
    pattern = shape(pin.tag)
    if pattern is None:
        current = published.get(pin.tag)
        return Finding(pin, pin.tag) if current and current != pin.digest else None
    same_shape = [t for t in published if pattern.match(t)]
    best = max(same_shape, key=version_key, default=pin.tag)
    if version_key(best) > version_key(pin.tag):
        return Finding(pin, best)
    return None
