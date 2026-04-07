"""Admin API — split into domain sub-modules for maintainability.

Re-exports a single ``router`` for backward-compatible registration in ``app.py``.
"""

from fastapi import APIRouter

from classymail.api.routers.admin.diagnostics import router as diagnostics_router
from classymail.api.routers.admin.data_ops import router as data_ops_router
from classymail.api.routers.admin.testing import router as testing_router
from classymail.api.routers.admin.analytics import router as analytics_router
from classymail.api.routers.admin.ai_search import router as ai_search_router
from classymail.api.routers.admin.vector_index import router as vector_index_router

router = APIRouter(prefix="/api/admin", tags=["admin"])

router.include_router(diagnostics_router)
router.include_router(data_ops_router)
router.include_router(testing_router)
router.include_router(analytics_router)
router.include_router(ai_search_router)
router.include_router(vector_index_router)
