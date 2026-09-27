"""List template images that have a newer version on Docker Hub (exit 1 if any).

uv run python scripts/check_images.py [templates_dir]
"""

import json
import sys
import urllib.request
from pathlib import Path

from hivora.templates.catalog import Catalog
from hivora.templates.freshness import Finding, newer, pins

HUB = "https://hub.docker.com/v2/repositories/{repo}/tags?page_size=100&ordering=last_updated"
PAGES = 5  # the 500 most recent tags


def published_ghcr(image: str) -> dict[str, str]:
    """ghcr.io: tag names only (moving tags there cannot be compared, versioned ones can)."""
    repo = image.removeprefix("ghcr.io/")
    token_url = f"https://ghcr.io/token?scope=repository:{repo}:pull"
    with urllib.request.urlopen(token_url, timeout=30) as r:
        token = json.load(r)["token"]
    req = urllib.request.Request(f"https://ghcr.io/v2/{repo}/tags/list?n=10000",
                                 headers={"Authorization": f"Bearer {token}"})  # fmt: skip
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
        return dict.fromkeys(json.load(r).get("tags") or [], "")


def published(image: str) -> dict[str, str]:
    if image.startswith("ghcr.io/"):
        return published_ghcr(image)
    image = image.removeprefix("docker.io/")
    repo = image if "/" in image else f"library/{image}"
    tags: dict[str, str] = {}
    url: str | None = HUB.format(repo=repo)
    for _ in range(PAGES):
        if not url:
            break
        with urllib.request.urlopen(url, timeout=30) as r:  # noqa: S310 (fixed https host)
            page = json.load(r)
        tags.update({t["name"]: t.get("digest") or "" for t in page["results"]})
        url = page.get("next")
    return tags


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parents[2] / "templates")
    catalog = Catalog()
    if errors := catalog.load_directory(root):
        print("\n".join(errors))
        return 2
    cache: dict[str, dict[str, str]] = {}
    findings: list[Finding] = []
    for pin in pins(catalog):
        host = pin.image.split("/")[0]
        if "." in host and host not in ("ghcr.io", "docker.io"):  # quay.io...: not checked
            print(f"skip   {pin.template}: {pin.image} (not on Docker Hub)")
            continue
        tags = cache.setdefault(pin.image, published(pin.image))
        if found := newer(pin, tags):
            findings.append(found)
    for f in findings:
        what = "rebuilt" if f.newest == f.pin.tag else f"-> {f.newest}"
        print(f"update {f.pin.template}: {f.pin.image}:{f.pin.tag} {what}")
    print(f"{len(findings)} image(s) to update" if findings else "all images up to date")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
