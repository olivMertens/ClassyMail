FROM mcr.microsoft.com/devcontainers/python:1-3.12

# Install system dependencies
# poppler-utils: Required for pdf2image/pymupdf processing
RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get -y install --no-install-recommends \
    poppler-utils \
    && apt-get clean -y && rm -rf /var/lib/apt/lists/*

# Install uv (Fast Python package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
