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
RUN chown -R app:app /app
USER app

EXPOSE 8000
CMD ["uvicorn", "classificationg2s.app:app", "--host", "0.0.0.0", "--port", "8000"]
# Worker entrypoint example:
# CMD ["python", "-m", "classificationg2s.worker_main"]
