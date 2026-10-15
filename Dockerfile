# syntax=docker/dockerfile:1.7
# Hivora: one container (API, WebSocket, static UI), linux/amd64 and linux/arm64.
# Build: docker buildx build --platform linux/amd64,linux/arm64 -t ghcr.io/hiidenops/hivora .

# --- frontend: static export -------------------------------------------------
FROM --platform=$BUILDPLATFORM node:22-alpine@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402 AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- backend: locked dependencies in a venv ------------------------------------
FROM python:3.13-alpine@sha256:79e7a9b9ff1cbceff819f856fb374477792a5967759d94df266de7b7b4120e6f AS py
RUN apk add --no-cache binutils
COPY --from=ghcr.io/astral-sh/uv:0.12.18 /uv /bin/uv
ENV UV_PROJECT_ENVIRONMENT=/venv UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /src
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
RUN uv sync --frozen --no-dev --no-editable \
 && find /venv \( -name tests -o -name __pycache__ \) -type d -prune -exec rm -rf {} + \
 && find /venv -name "*.so" -exec strip --strip-unneeded {} + 2>/dev/null; true

# --- runtime --------------------------------------------------------------------
FROM python:3.13-alpine@sha256:79e7a9b9ff1cbceff819f856fb374477792a5967759d94df266de7b7b4120e6f
# Compose v2 standalone: the only Docker binary Hivora runs (the API goes through the socket).
COPY --from=docker/compose-bin:v2.40.3@sha256:e39da8206cc48c6e2c99ce371935eef9d7eff7db600a993fd357de8b75621edf /docker-compose /usr/local/bin/docker-compose
COPY --from=py /venv /venv
COPY --from=ui /ui/out /app/frontend
COPY templates /app/templates
COPY CHANGELOG.md /app/CHANGELOG.md
ENV PATH=/venv/bin:$PATH \
    HIVORA_COMPOSE_CMD='["docker-compose"]' \
    HIVORA_FRONTEND_DIR=/app/frontend \
    HIVORA_CATALOG_DIR=/app/templates \
    HIVORA_LOG_FORMAT=json \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8443
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import ssl,urllib.request as u,os; s=os.environ.get('HIVORA_TLS','true')!='false'; u.urlopen(('https' if s else 'http')+'://127.0.0.1:'+os.environ.get('HIVORA_PORT','8443')+'/api/v1/system/health', context=ssl._create_unverified_context(), timeout=4)"
CMD ["python", "-m", "hivora"]
