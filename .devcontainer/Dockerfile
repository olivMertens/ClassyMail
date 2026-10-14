FROM mcr.microsoft.com/devcontainers/python:1-3.12

# Install system dependencies
# poppler-utils: Required for pdf2image/pymupdf processing
# The base image's Yarn apt source has an expired GPG key and breaks apt-get update.
RUN rm -f /etc/apt/sources.list.d/yarn.list \
    && apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get -y install --no-install-recommends \
    poppler-utils \
    && apt-get clean -y && rm -rf /var/lib/apt/lists/*

# Install uv (Fast Python package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
