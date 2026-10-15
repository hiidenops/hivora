""".github/scripts/release-check.sh: the release tag matches the versions, and the GitHub
Release body is the version's CHANGELOG.md section (release.yml publishes it)."""

import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / ".github" / "scripts" / "release-check.sh"
CHANGELOG = """# Journal des modifications

## [Non publié]

- Pas encore publié.

## [0.2.0-rc.1]

- Candidate seulement.

## [0.1.0] - 2026-10-20

### Ajouté

- Première version.
"""


def repo(tmp_path: Path, version: str, changelog: str = CHANGELOG) -> Path:
    """The three files the script reads, at their places in the repository."""
    (tmp_path / "backend").mkdir(parents=True)
    (tmp_path / "frontend").mkdir()
    (tmp_path / "backend" / "pyproject.toml").write_text(
        f'[project]\nname = "hivora"\nversion = "{version}"\n'
    )
    (tmp_path / "frontend" / "package.json").write_text(json.dumps({"version": version}))
    (tmp_path / "CHANGELOG.md").write_text(changelog)
    return tmp_path


def check(root: Path, tag: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["/bin/sh", str(SCRIPT), tag, "notes.md"], cwd=root,  # noqa: S603
                          capture_output=True, text=True, timeout=30, check=False)  # fmt: skip


def test_the_versions_section_becomes_the_release_notes(tmp_path: Path) -> None:
    done = check(repo(tmp_path, "0.1.0"), "v0.1.0")
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == ["version=0.1.0", "prerelease=false"]
    assert (tmp_path / "notes.md").read_text() == "\n### Ajouté\n\n- Première version.\n"


def test_a_release_candidate_uses_its_section_else_the_final_one(tmp_path: Path) -> None:
    root = repo(tmp_path, "0.2.0-rc.1")
    done = check(root, "v0.2.0-rc.1")
    assert done.returncode == 0 and "prerelease=true" in done.stdout
    assert "Candidate seulement." in (root / "notes.md").read_text()
    other = repo(tmp_path / "b", "0.1.0-rc.3")
    done = check(other, "v0.1.0-rc.3")  # no [0.1.0-rc.3]: the [0.1.0] section
    assert done.returncode == 0 and "Première version." in (other / "notes.md").read_text()


@pytest.mark.parametrize(("tag", "version", "changelog", "message"), [
    ("v0.3.0", "0.3.0", CHANGELOG, "no section for 0.3.0"),  # still under [Non publié]
    ("v0.1.0", "0.1.0", "# Journal\n\n## [0.1.0]\n\n## [0.0.9]\n\n- old\n",
     "no section for 0.1.0"),  # an empty section
    ("v0.1.0", "0.1.1", CHANGELOG, "version mismatch"),
    ("0.1.0", "0.1.0", CHANGELOG, "not a release tag"),
    ("v0.1.0-beta", "0.1.0-beta", CHANGELOG, "not a release version"),
])  # fmt: skip
def test_a_wrong_release_is_refused(tmp_path: Path, tag: str, version: str, changelog: str,
                                    message: str) -> None:  # fmt: skip
    done = check(repo(tmp_path, version, changelog), tag)
    assert done.returncode == 1 and message in done.stderr, done.stderr
    assert not (tmp_path / "notes.md").exists() or not (tmp_path / "notes.md").read_text()


def test_the_repositorys_changelog_has_an_unreleased_section() -> None:
    """Every functional lot adds its line there; a release renames it (docs/releasing.md)."""
    text = (Path(__file__).parents[2] / "CHANGELOG.md").read_text()
    head = text.split("\n## [", 2)
    assert head[1].startswith("Non publié]"), "the first section must be [Non publié]"
