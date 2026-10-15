#!/bin/sh
# Checks a release tag and writes its notes (used by release.yml; runnable locally).
#   release-check.sh vX.Y.Z[-rc.N] NOTES_FILE
# Fails unless the tag, backend/pyproject.toml and frontend/package.json give the same
# version, and CHANGELOG.md has a section for it ("## [X.Y.Z-rc.N]", else "## [X.Y.Z]").
# Prints "version=…" and "prerelease=true|false" (for $GITHUB_OUTPUT).
set -eu
tag=$1 notes=$2
case "$tag" in
  v[0-9]*.[0-9]*.[0-9]*) ;;
  *) echo "not a release tag: $tag (vX.Y.Z or vX.Y.Z-rc.N)" >&2; exit 1 ;;
esac
version=${tag#v}
echo "$version" | grep -Eqx '[0-9]+\.[0-9]+\.[0-9]+(-rc\.[0-9]+)?' \
  || { echo "not a release version: $version" >&2; exit 1; }
py=$(python3 -c "import tomllib; print(tomllib.load(open('backend/pyproject.toml', 'rb'))['project']['version'])")
js=$(python3 -c "import json; print(json.load(open('frontend/package.json'))['version'])")
if [ "$py" != "$version" ] || [ "$js" != "$version" ]; then
  echo "version mismatch: tag $version, pyproject.toml $py, package.json $js" >&2
  exit 1
fi
section() {  # the body of "## [$1]" in CHANGELOG.md, up to the next "## ["
  awk -v head="## [$1]" 'index($0, head) == 1 { on = 1; next } /^## \[/ { on = 0 } on' CHANGELOG.md
}
body=$(section "$version")
[ -n "$(echo "$body" | tr -d '[:space:]')" ] || body=$(section "${version%%-*}")
[ -n "$(echo "$body" | tr -d '[:space:]')" ] \
  || { echo "CHANGELOG.md has no section for $version" >&2; exit 1; }
printf '%s\n' "$body" > "$notes"
echo "version=$version"
case "$version" in *-*) echo "prerelease=true" ;; *) echo "prerelease=false" ;; esac
