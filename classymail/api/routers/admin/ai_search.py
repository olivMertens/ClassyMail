"""Admin AI Search — per-category index CRUD and example management."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from classymail.services.azure_clients import Clients, get_clients
import logging

router = APIRouter()
logger = logging.getLogger("ClassyMail.admin")


class EnsureIndexRequest(BaseModel):
    slug: str


class UpsertExampleRequest(BaseModel):
    content: str
    is_positive: bool = True
    correction_reason: str = ""
    label_source: str = "human_verified"
    email_id: str = ""


@router.get("/ai-search/indexes")
async def list_ai_search_indexes(clients: Clients = Depends(get_clients)):
    """List all per-category AI Search indexes with doc counts."""
    from classymail.agents.tools.ai_search_index import list_indexes, get_index_doc_count
    from classymail.agents.config import SEARCH_ENDPOINT

    if not SEARCH_ENDPOINT:
        return {"enabled": False, "indexes": []}

    indexes = await list_indexes()
    result = []
    for ix in indexes:
        name = ix.get("name", "")
        slug = name.replace("classymail-intent-", "")
        count = await get_index_doc_count(slug)
        result.append({"index": name, "slug": slug, "doc_count": count})

    return {"enabled": True, "indexes": result}


@router.post("/ai-search/indexes/ensure")
async def ensure_ai_search_index(req: EnsureIndexRequest, clients: Clients = Depends(get_clients)):
    """Idempotent create-or-skip for a single category's AI Search index."""
    from classymail.agents.tools.ai_search_index import ensure_index

    result = await ensure_index(req.slug, clients=clients)
    if result.get("status") == "error":
        raise HTTPException(status_code=502, detail=result.get("detail", "Index creation failed"))
    return result


@router.post("/ai-search/indexes/ensure-all")
async def ensure_all_indexes(clients: Clients = Depends(get_clients)):
    """Ensure AI Search indexes exist for all configured categories."""
    from classymail.agents.tools.ai_search_index import ensure_indexes_for_categories
    from classymail.services.settings_store import load_settings

    settings = load_settings()
    categories = settings.get("categories", [])
    results = await ensure_indexes_for_categories(categories, clients=clients)
    return {"results": results}


@router.delete("/ai-search/indexes/{slug}")
async def delete_ai_search_index(slug: str):
    """Delete a category's AI Search index."""
    from classymail.agents.tools.ai_search_index import delete_index

    result = await delete_index(slug)
    if result.get("status") == "error":
        raise HTTPException(status_code=502, detail=result.get("detail", "Delete failed"))
    return result


@router.get("/ai-search/indexes/{slug}/examples")
async def list_ai_search_examples(slug: str, top: int = 20):
    """List example documents in a category's AI Search index."""
    from classymail.agents.tools.ai_search_index import list_examples

    return {"slug": slug, "examples": await list_examples(slug, top=top)}


@router.post("/ai-search/indexes/{slug}/examples")
async def add_ai_search_example(
    slug: str,
    req: UpsertExampleRequest,
    clients: Clients = Depends(get_clients),
):
    """Add a good or bad example document to a category's AI Search index.

    The index is auto-created if it doesn't exist yet. Provide
    ``is_positive=true`` for a good example, ``is_positive=false`` with a
    ``correction_reason`` for a bad/negative example.
    """
    from classymail.agents.tools.ai_search_index import ensure_index, upsert_example

    await ensure_index(slug, clients=clients)

    result = await upsert_example(
        slug,
        req.content,
        is_positive=req.is_positive,
        correction_reason=req.correction_reason,
        label_source=req.label_source,
        email_id=req.email_id,
        clients=clients,
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=502, detail=result.get("detail", "Upload failed"))
    return result


@router.delete("/ai-search/indexes/{slug}/examples/{doc_id}")
async def remove_ai_search_example(slug: str, doc_id: str):
    """Delete a specific example from a category's index."""
    from classymail.agents.tools.ai_search_index import delete_example

    result = await delete_example(slug, doc_id)
    if result.get("status") == "error":
        raise HTTPException(status_code=502, detail=result.get("detail", "Delete failed"))
    return result
