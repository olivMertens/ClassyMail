# ── Stage 1: Build Vue frontend ──────────────────────────────────────
FROM node:22-alpine AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build
# Output: /frontend/../static/dist  →  relative to vite outDir '../static/dist'
# Vite writes to /static/dist because outDir is '../static/dist' relative to /frontend

# ── Stage 2: Python application ─────────────────────────────────────
FROM python:3.12-slim

ENV UV_PROJECT_ENV=.venv \
    UV_PIP_NO_WARN_SCRIPT_LOCATION=1 \
    UV_PYTHON=python3
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y \
    curl \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /app
COPY pyproject.toml uv.lock requirements.txt README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# Use the project virtualenv at runtime (avoid `uv run` resolving deps on startup).
ENV PATH="/app/.venv/bin:${PATH}"

# Create non-root user
RUN addgroup --system app && adduser --system --ingroup app app \
    && chown -R app:app /app

COPY . .

# Copy built frontend from stage 1 into static/dist
COPY --from=frontend-build /static/dist ./static/dist/

# Install the project itself (source is now present).
RUN uv sync --frozen --no-dev

RUN chown -R app:app /app
USER app

EXPOSE 8000
CMD ["uvicorn", "classymail.app:app", "--host", "0.0.0.0", "--port", "8000"]
# Worker entrypoint example:
# CMD ["python", "-m", "classymail.worker_main"]
