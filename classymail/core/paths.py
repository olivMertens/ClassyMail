from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
    # classificationg2s/core/paths.py -> classificationg2s -> repo root
    return Path(__file__).resolve().parents[2]
