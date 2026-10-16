# Publier une version

`CHANGELOG.md` est la source de vérité de ce qui a changé. Chaque modification fonctionnelle
ajoute sa ligne sous `## [Non publié]` dans le même commit. Une release transforme cette
section en celle de la version, et la GitHub Release la publie automatiquement.

## Étapes

1. Dans `CHANGELOG.md`, renommer `## [Non publié]` en `## [X.Y.Z] - AAAA-MM-JJ` et ajouter
   au-dessus un nouveau `## [Non publié]` vide. Si une section `## [X.Y.Z]` existe déjà
   (comme pour la 0.1.0, qui contient aussi un résumé de la première version), y déplacer
   plutôt les lignes de `[Non publié]`, et laisser `[Non publié]` vide.
2. Mettre la version `X.Y.Z` dans `backend/pyproject.toml` et `frontend/package.json`, puis
   mettre à jour les deux fichiers de verrouillage : `uv lock` dans `backend/` (la CI lance
   `uv sync --locked`, qui échoue avec un verrou portant l'ancienne version ; `uv.lock`
   l'écrit normalisée, par exemple `0.1.0rc1`) et `npm install --package-lock-only` dans
   `frontend/` (la `version` racine de `package-lock.json`). Contrôler avec
   `uv lock --check` et `npm ci --dry-run`.
3. Commiter (`release: vX.Y.Z`) sur `main`, pousser, et attendre que la CI passe.
4. Taguer et pousser le tag :
   ```sh
   git tag vX.Y.Z && git push origin vX.Y.Z
   ```
5. `.github/workflows/release.yml` alors :
   - vérifie que le commit tagué est sur `main`, que le tag, `pyproject.toml` et
     `package.json` concordent, et que `CHANGELOG.md` a une section non vide pour la version
     (`.github/scripts/release-check.sh` ; sinon il échoue) ;
   - construit et publie l'image (`amd64`, `arm64`) : `vX.Y.Z`, `X.Y` et `latest` ;
   - crée la GitHub Release : **la section de la version dans `CHANGELOG.md`**, la commande
     d'installation et le digest de l'image, avec `install.sh` (réglé sur cette version) et
     son `.sha256`.
6. Vérifier la page de la release, puis l'installer sur une machine vierge avec la commande
   du README.

## Release candidates

Taguer `vX.Y.Z-rc.N` (avec la même version dans les deux fichiers et les deux verrous). Les
notes sont la section `## [X.Y.Z-rc.N]`, sinon `## [X.Y.Z]` : pour une candidate,
rassembler les lignes de `[Non publié]` sous `## [X.Y.Z]` **sans date** (et laisser
`[Non publié]` vide) ; la date est ajoutée par le commit de la version finale, qui ne change
qu'elle et la version. L'image ne reçoit que son propre tag (jamais `X.Y` ni `latest`) et la
GitHub Release est marquée pré-version : les panels sur le canal **Pré-versions** la voient.

## Essayer la vérification en local

```sh
sh .github/scripts/release-check.sh vX.Y.Z notes.md && cat notes.md
```
