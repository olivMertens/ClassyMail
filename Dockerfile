FROM python:3.11-slim

ENV UV_PROJECT_ENV=.venv \
    UV_PIP_NO_WARN_SCRIPT_LOCATION=1 \
    UV_PYTHON=python3

RUN apt-get update && apt-get install -y curl build-essential && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /app
COPY pyproject.toml uv.lock requirements.txt README.md ./
COPY classificationg2s ./classificationg2s
RUN uv sync --frozen --no-dev

COPY . .

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
