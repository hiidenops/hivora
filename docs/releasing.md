# Releasing

`CHANGELOG.md` is the source of truth of what changed. Every functional change adds its
line under `## [Non publié]` (in French) in the same commit. A release turns that section
into the version's, and the GitHub Release publishes it automatically.

## Steps

1. In `CHANGELOG.md`, rename `## [Non publié]` to `## [X.Y.Z] - YYYY-MM-DD` and add a new,
   empty `## [Non publié]` above it. If a `## [X.Y.Z]` section already exists (as for
   0.1.0, which also holds a summary of the first version), move the lines of
   `[Non publié]` into it instead, and leave `[Non publié]` empty.
2. Set the version in `backend/pyproject.toml` and `frontend/package.json` to `X.Y.Z`, then
   update both lock files: `uv lock` in `backend/` (the CI runs `uv sync --locked`, which
   fails on a lock with the old version; `uv.lock` writes it normalized, e.g. `0.1.0rc1`)
   and `npm install --package-lock-only` in `frontend/` (the root `version` of
   `package-lock.json`). Check with `uv lock --check` and `npm ci --dry-run`.
3. Commit (`release: vX.Y.Z`) on `main`, push, and wait for the CI to pass.
4. Tag and push the tag:
   ```sh
   git tag vX.Y.Z && git push origin vX.Y.Z
   ```
5. `.github/workflows/release.yml` then:
   - checks that the tagged commit is on `main`, that the tag, `pyproject.toml` and
     `package.json` agree, and that `CHANGELOG.md` has a non-empty section for the version
     (`.github/scripts/release-check.sh`; it fails otherwise);
   - builds and publishes the image (`amd64`, `arm64`): `vX.Y.Z`, `X.Y` and `latest`;
   - creates the GitHub Release: **the version's `CHANGELOG.md` section**, the install
     command and the image digest, with `install.sh` (set to this version) and its
     `.sha256`.
6. Check the release page, then install it on a clean machine with the README's command.

## Release candidates

Tag `vX.Y.Z-rc.N` (with the same version in both files and both lock files). The notes
are the `## [X.Y.Z-rc.N]` section, or else `## [X.Y.Z]`: for a candidate, gather the lines
of `[Non publié]` under `## [X.Y.Z]` **without a date** (and leave `[Non publié]` empty);
the date is added by the final release's commit, which only sets it and the version. The image only gets its own tag (never
`X.Y` nor `latest`) and the GitHub Release is marked as a pre-release: panels on the
**Pre-releases** channel see it.

## Trying the check locally

```sh
sh .github/scripts/release-check.sh vX.Y.Z notes.md && cat notes.md
```
