from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from classificationg2s.core.paths import project_root


router = APIRouter(tags=["ui"])


@router.get("/", response_class=HTMLResponse)
async def index():
    path = Path(project_root()) / "templates" / "index.html"
    return HTMLResponse(path.read_text(encoding="utf-8"))
