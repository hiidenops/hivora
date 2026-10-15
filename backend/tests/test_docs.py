"""The README and docs/ stay true: every installer option and `python -m hivora` command
they name exists, every relative link resolves, the README stays a short showcase."""

import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
DOCS = [ROOT / "README.md", ROOT / "SECURITY.md", *sorted((ROOT / "docs").glob("*.md"))]
PUBLIC = [p for p in DOCS if p.name not in {"ARCHITECT_BRAIN.md", "PROGRESS.md",
                                           "vision-prd-architecture.md"}]  # fmt: skip
SECTIONS = ["Hivora in a few words", "Key features", "Quick install", "Access modes",
            "First login", "Screenshots", "Documentation", "Security", "License",
            "Development"]  # fmt: skip


def test_the_public_docs_are_there() -> None:
    names = {p.name for p in PUBLIC}
    assert {"README.md", "SECURITY.md", "installation.md", "admin-vpn.md", "updating.md",
            "backups.md", "troubleshooting.md", "uninstall.md", "development.md",
            "releasing.md"} <= names  # fmt: skip


def test_installer_options_exist() -> None:
    installer = (ROOT / "deploy" / "install.sh").read_text()
    known = set(re.findall(r"^\s+(--[a-z][a-z-]+)\)", installer, re.M))
    known |= set(re.findall(r"(--[a-z][a-z-]+)\|", installer))  # grouped: --version|--image
    assert "--reconfigure" in known and "--vpn-host" in known
    for doc in PUBLIC:
        text = doc.read_text()
        for line in text.splitlines():
            if "install.sh" not in line and not line.lstrip().startswith(("| `--", "`--")):
                continue
            for option in re.findall(r"(?<![\w-])(--[a-z][a-z-]+)", line):
                if option in {"--package-lock-only", "--filter"}:  # npm, docker
                    continue
                assert option in known, f"{doc.name}: {option}"


def test_hivora_commands_exist() -> None:
    main = (ROOT / "backend" / "src" / "hivora" / "__main__.py").read_text()
    for doc in PUBLIC:
        for command in re.findall(r"python -m hivora ([a-z-]+)", doc.read_text()):
            assert f'"{command}"' in main, f"{doc.name}: {command}"


def test_relative_links_and_images_resolve() -> None:
    for doc in PUBLIC:
        for target in re.findall(r"\]\((?!https?://|#)([^)#\s]+)", doc.read_text()):
            assert (doc.parent / target).exists(), f"{doc.name}: {target}"
    for image in (ROOT / "docs" / "images").glob("*.png"):
        assert image.stat().st_size < 300_000, image.name


def test_the_readme_is_a_short_showcase() -> None:
    text = (ROOT / "README.md").read_text()
    titles = re.findall(r"^## (.+)$", text, re.M)
    assert titles == SECTIONS
    assert len(text.splitlines()) < 200
    for image in ("dashboard", "catalog", "health"):
        assert f"docs/images/{image}.png" in text
    assert "CHANGELOG.md" in text and "security/advisories/new" in text
