from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response

from classymail.core.paths import project_root


router = APIRouter(tags=["ui"])


def _serve_index() -> HTMLResponse:
    # Try serving the built frontend first
    dist_index = Path(project_root()) / "static" / "dist" / "index.html"
    if dist_index.exists():
        return HTMLResponse(dist_index.read_text(encoding="utf-8"))

    return HTMLResponse(
        "<h1>Frontend not built</h1><p>Please run 'npm run build' in frontend/ directory.</p>",
        status_code=500,
    )


@router.get("/", response_class=HTMLResponse)
async def index():
    return _serve_index()


@router.get("/{full_path:path}", response_class=HTMLResponse)
async def catch_all(full_path: str):
    """Catch-all for SPA history mode.

    This route is registered LAST in app.py, so it only catches
    paths that didn't match any API route or static file.
    """
    # Explicitly avoid capturing remaining API/docs calls that might be 404s
    # otherwise they would return index.html (200 OK) which confuses clients.
    if full_path.startswith("api/") or full_path.startswith("static/") or full_path in ("docs", "redoc", "openapi.json"):
        return Response(status_code=404)

    return _serve_index()
