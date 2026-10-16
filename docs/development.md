# Développement

## Organisation

| Chemin | Contenu |
|---|---|
| `backend/src/hivora/` | le serveur (Python 3.13, FastAPI, SQLAlchemy sur SQLite, Alembic) : un module par domaine (`apps`, `vpn`, `zones`, `system`…), `runtime.py` les assemble |
| `backend/tests/` | pytest ; `e2e_app.py` fait tourner la vraie API avec un faux Docker pour les tests dans le navigateur |
| `frontend/` | le panel (Next.js exporté en fichiers statiques, TypeScript, Tailwind), tests Playwright dans `e2e/` |
| `templates/` | le catalogue (un `template.yaml` par application ou jeu) |
| `deploy/` | `install.sh` et `compose.yaml` |
| `docs/` | la documentation utilisateur ; `ARCHITECT_BRAIN.md`, `PROGRESS.md` et `vision-prd-architecture.md` sont les notes de conception du projet |

## Lancer les tests

```sh
cd backend
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy src tests
uv run pytest -q

cd ../frontend
npm ci
npm run lint && npm test && npm run build && npm run check:bundle
npx playwright test          # démarre lui-même le backend, avec un faux Docker
```

`npm run gen:api` régénère les types de l'API côté frontend après un changement des routes.

## Lancer le panel depuis les sources

```sh
cd frontend && npm run build
cd ../backend
HIVORA_DATA_DIR=$HOME/hivora-dev/data HIVORA_VOLUMES_ROOT=$HOME/hivora-dev/srv \
HIVORA_CATALOG_DIR=../templates HIVORA_FRONTEND_DIR=../frontend/out \
HIVORA_DEV_INSECURE_COOKIES=true HIVORA_CHANGELOG_PATH=../CHANGELOG.md \
uv run uvicorn --factory hivora.main:app --host 0.0.0.0 --port 8000
```

Le panel utilise alors le vrai Docker de la machine.

## Règles pour une modification

- **`CHANGELOG.md`** : chaque modification fonctionnelle ajoute une ligne sous
  `## [Non publié]`, dans le même commit. Elle devient les notes de version (voir
  [releasing.md](releasing.md)).
- Modification de l'API : régénérer `frontend/lib/api/openapi.json` et les types.
- Textes du panel : en français et en anglais (`frontend/lib/i18n/`).
- Modification de l'installeur : garder [installation.md](installation.md) à jour ; un test
  vérifie que les options et commandes citées par la documentation existent.
- Captures de la documentation (`docs/images/`) : `npx playwright test -c
  playwright.screenshots.config.ts` dans `frontend/`.
- Les règles d'architecture (frontières des modules, modifications par tâches, aucun appel
  externe dans une transaction de base, limites de taille) sont dans
  `docs/ARCHITECT_BRAIN.md`.
