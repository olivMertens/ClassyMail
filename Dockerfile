FROM python:3.12-slim

ENV UV_PROJECT_ENV=.venv \
    UV_PIP_NO_WARN_SCRIPT_LOCATION=1 \
    UV_PYTHON=python3
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y curl build-essential && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /app
COPY pyproject.toml uv.lock requirements.txt README.md ./
RUN uv sync --frozen --no-dev

# Use the project virtualenv at runtime (avoid `uv run` resolving deps on startup).
ENV PATH="/app/.venv/bin:${PATH}"

# Create non-root user
RUN addgroup --system app && adduser --system --ingroup app app \
    && chown -R app:app /app

COPY . .

# Offline-friendly build: Vue must be provided in the build context.
# The repo tracks a small stub at static/js/vue.global.prod.js; builds should replace it with
# the real Vue runtime (see scripts/fetch_vue_runtime.*).
ARG ALLOW_VUE_STUB=0
RUN python - <<'PY'
import os
from pathlib import Path

p = Path('/app/static/js/vue.global.prod.js')
if not p.exists():
    raise SystemExit('ERROR: Missing static/js/vue.global.prod.js. Provide the Vue runtime file before building.')

content = p.read_text(encoding='utf-8', errors='ignore')
is_stub = ('Vue stub loaded' in content) or ('Vue stub:' in content)
allow = os.environ.get('ALLOW_VUE_STUB', '0').lower() in {'1', 'true', 'yes'}

if is_stub and not allow:
    raise SystemExit(
        'ERROR: Vue runtime stub detected in static/js/vue.global.prod.js.\n'
        'Run scripts/fetch_vue_runtime.sh (Linux/macOS/CI) or scripts/fetch_vue_runtime.ps1 (Windows),\n'
        'or copy the real vue.global.prod.js into static/js before building.\n'
        'If you *really* want the stub (dev only), build with --build-arg ALLOW_VUE_STUB=1.'
    )
PY
RUN chown -R app:app /app
USER app

EXPOSE 8000
CMD ["uvicorn", "classificationg2s.app:app", "--host", "0.0.0.0", "--port", "8000"]
# Worker entrypoint example:
# CMD ["python", "-m", "classificationg2s.worker_main"]
