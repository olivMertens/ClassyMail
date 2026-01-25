from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from classificationg2s.core.paths import project_root


router = APIRouter(tags=["ui"])


@router.get("/", response_class=HTMLResponse)
async def index():
    # Try serving the built frontend first
    dist_index = Path(project_root()) / "static" / "dist" / "index.html"
    if dist_index.exists():
        return HTMLResponse(dist_index.read_text(encoding="utf-8"))

    return HTMLResponse("<h1>Frontend not built</h1><p>Please run 'npm run build' in frontend/ directory.</p>", status_code=500)
