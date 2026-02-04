from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
    # classymail/core/paths.py -> classymail -> repo root
    return Path(__file__).resolve().parents[2]
