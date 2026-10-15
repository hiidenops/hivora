# Development

## Layout

| Path | What |
|---|---|
| `backend/src/hivora/` | the server (Python 3.13, FastAPI, SQLAlchemy on SQLite, Alembic): one module per domain (`apps`, `vpn`, `zones`, `system`, …), `runtime.py` wires them |
| `backend/tests/` | pytest; `e2e_app.py` runs the real API with a fake Docker for the browser tests |
| `frontend/` | the panel (Next.js exported as static files, TypeScript, Tailwind), `e2e/` Playwright tests |
| `templates/` | the catalog (one `template.yaml` per app or game) |
| `deploy/` | `install.sh` and `compose.yaml` |
| `docs/` | user documentation (English); `ARCHITECT_BRAIN.md`, `PROGRESS.md` and `vision-prd-architecture.md` are the project's design notes (French) |

## Running the tests

```sh
cd backend
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy src tests
uv run pytest -q

cd ../frontend
npm ci
npm run lint && npm test && npm run build && npm run check:bundle
npx playwright test          # starts the backend itself, with a fake Docker
```

`npm run gen:api` regenerates the frontend's API types after a change of the routes.

## Running the panel from the sources

```sh
cd frontend && npm run build
cd ../backend
HIVORA_DATA_DIR=$HOME/hivora-dev/data HIVORA_VOLUMES_ROOT=$HOME/hivora-dev/srv \
HIVORA_CATALOG_DIR=../templates HIVORA_FRONTEND_DIR=../frontend/out \
HIVORA_DEV_INSECURE_COOKIES=true HIVORA_CHANGELOG_PATH=../CHANGELOG.md \
uv run uvicorn --factory hivora.main:app --host 0.0.0.0 --port 8000
```

This uses the machine's real Docker.

## Rules for a change

- **`CHANGELOG.md`**: every functional change adds one line under `## [Non publié]`
  (French), in the same commit. It becomes the release notes (see
  [releasing.md](releasing.md)).
- Changes to the API: regenerate `frontend/lib/api/openapi.json` and the types.
- Texts of the panel: in French and in English (`frontend/lib/i18n/`).
- Changes to the installer: keep [installation.md](installation.md) in step; a test checks
  that the options and commands the documentation names exist.
- The architecture rules (module boundaries, jobs for changes, no external call inside a
  database transaction, size limits) are in `docs/ARCHITECT_BRAIN.md`.
