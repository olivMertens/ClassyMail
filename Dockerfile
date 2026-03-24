# ── Stage 1: Build Vue frontend ──────────────────────────────────────
FROM node:22-alpine AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --prefer-offline
COPY frontend/ ./
RUN npm run build
# Output: /static/dist (vite outDir is '../static/dist' relative to /frontend)

# ── Stage 2: Python application ─────────────────────────────────────
FROM python:3.12-slim AS runtime

# Single ENV block — reduces layers
ENV UV_PROJECT_ENV=.venv \
    UV_PIP_NO_WARN_SCRIPT_LOCATION=1 \
    UV_PYTHON=python3 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System deps: only what's needed at runtime.
# build-essential is NOT needed — all Python deps ship pre-compiled wheels.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install uv (fast Python package manager)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

# Create non-root user early (before COPY — avoids double chown)
RUN addgroup --system app && adduser --system --ingroup app app

WORKDIR /app

# ── Layer 1: Python deps (cached unless pyproject.toml/uv.lock change) ──
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# ── Layer 2: Application source (changes frequently) ──
COPY classymail/ ./classymail/
COPY main.py ./

# ── Layer 3: Built frontend from Stage 1 ──
COPY --from=frontend-build /static/dist ./static/dist/

# ── Layer 4: Install project itself (fast — deps already cached) ──
RUN uv sync --frozen --no-dev

# Build metadata (set via --build-arg during ACR build)
ARG COMMIT_SHA=unknown
ARG BUILD_TIMESTAMP=unknown
ENV COMMIT_SHA=${COMMIT_SHA} \
    BUILD_TIMESTAMP=${BUILD_TIMESTAMP} \
    PATH="/app/.venv/bin:${PATH}"

RUN chown -R app:app /app
USER app

EXPOSE 8000
CMD ["uvicorn", "classymail.app:app", "--host", "0.0.0.0", "--port", "8000"]
# Worker override: CMD ["python", "-m", "classymail.worker_main"]
