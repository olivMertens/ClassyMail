"""Idempotent AI Search index management for per-category indexes.

Provides create-or-update semantics so indexes are provisioned on demand
(e.g. when a user adds a new category in the UI) without destroying
existing data.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from classymail.agents.config import SEARCH_ENDPOINT, SEARCH_ADMIN_KEY
from classymail.services.azure_clients import Clients

logger = logging.getLogger(__name__)

EMBEDDING_DIMENSIONS = 1536

# ── Schema ───────────────────────────────────────────────────────────


def _index_name(slug: str) -> str:
    return f"classymail-intent-{slug}"


def _build_index_fields() -> list[dict]:
    return [
        {"name": "id", "type": "Edm.String", "key": True, "filterable": True},
        {"name": "email_id", "type": "Edm.String", "filterable": True},
        {"name": "content", "type": "Edm.String", "searchable": True},
        {"name": "label", "type": "Edm.String", "filterable": True},
        {"name": "label_source", "type": "Edm.String", "filterable": True},
        {"name": "human_verified", "type": "Edm.Boolean", "filterable": True},
        {"name": "is_positive", "type": "Edm.Boolean", "filterable": True},
        {"name": "correction_reason", "type": "Edm.String", "searchable": True},
        {"name": "confidence_original", "type": "Edm.Double"},
        {
            "name": "content_vector",
            "type": "Collection(Edm.Single)",
            "searchable": True,
            "dimensions": EMBEDDING_DIMENSIONS,
            "vectorSearchProfile": "default-profile",
        },
        {"name": "created_at", "type": "Edm.DateTimeOffset", "filterable": True, "sortable": True},
    ]


def build_index_schema(slug: str) -> dict:
    """Build the full AI Search index schema for a category."""
    return {
        "name": _index_name(slug),
        "fields": _build_index_fields(),
        "vectorSearch": {
            "algorithms": [{"name": "hnsw", "kind": "hnsw", "hnswParameters": {"metric": "cosine"}}],
            "profiles": [{"name": "default-profile", "algorithm": "hnsw"}],
        },
        "semantic": {
            "configurations": [
                {
                    "name": "default-semantic",
                    "prioritizedFields": {
                        "prioritizedContentFields": [{"fieldName": "content"}],
                    },
                }
            ]
        },
    }


# ── Helpers ──────────────────────────────────────────────────────────


def _auth_headers() -> dict[str, str]:
    """Build auth headers for AI Search REST calls."""
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if SEARCH_ADMIN_KEY:
        headers["api-key"] = SEARCH_ADMIN_KEY
    return headers


# ── Idempotent index management ─────────────────────────────────────


async def ensure_index(slug: str, *, clients: Clients | None = None) -> dict:
    """Create-or-update an AI Search index for the given category slug.

    Returns ``{"status": "created"|"exists"|"disabled", "index": "..."}``
    """
    if not SEARCH_ENDPOINT:
        return {"status": "disabled", "index": _index_name(slug)}

    import httpx

    index = _index_name(slug)
    headers = _auth_headers()
    api = f"{SEARCH_ENDPOINT}/indexes/{index}?api-version=2024-07-01"

    async with httpx.AsyncClient(timeout=30) as http:
        check = await http.get(api, headers=headers)
        if check.status_code == 200:
            logger.info("AI Search index '%s' already exists", index)
            return {"status": "exists", "index": index}

        schema = build_index_schema(slug)
        resp = await http.put(api, headers=headers, json=schema)
        if resp.status_code in (200, 201):
            logger.info("AI Search index '%s' created", index)
            return {"status": "created", "index": index}
        else:
            logger.error("Failed to create index '%s': %d %s", index, resp.status_code, resp.text[:300])
            return {"status": "error", "index": index, "detail": resp.text[:300]}


async def ensure_indexes_for_categories(categories: list[dict], *, clients: Clients | None = None) -> list[dict]:
    """Ensure AI Search indexes exist for all given categories."""
    results = []
    for cat in categories:
        slug = cat.get("slug", "")
        if slug:
            r = await ensure_index(slug, clients=clients)
            results.append(r)
    return results


async def delete_index(slug: str) -> dict:
    """Delete an AI Search index (used when removing a category)."""
    if not SEARCH_ENDPOINT:
        return {"status": "disabled"}

    import httpx

    index = _index_name(slug)
    headers = _auth_headers()
    api = f"{SEARCH_ENDPOINT}/indexes/{index}?api-version=2024-07-01"

    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.delete(api, headers=headers)
        if resp.status_code in (200, 204, 404):
            return {"status": "deleted", "index": index}
        return {"status": "error", "detail": resp.text[:300]}


async def list_indexes() -> list[dict]:
    """List all classymail-intent-* indexes from AI Search."""
    if not SEARCH_ENDPOINT:
        return []

    import httpx

    headers = _auth_headers()
    api = f"{SEARCH_ENDPOINT}/indexes?api-version=2024-07-01&$select=name"

    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.get(api, headers=headers)
        if resp.status_code != 200:
            return []
        indexes = resp.json().get("value", [])
        return [ix for ix in indexes if ix.get("name", "").startswith("classymail-intent-")]


async def get_index_doc_count(slug: str) -> int:
    """Get document count for a category's AI Search index."""
    if not SEARCH_ENDPOINT:
        return 0

    import httpx

    index = _index_name(slug)
    headers = _auth_headers()
    api = f"{SEARCH_ENDPOINT}/indexes/{index}/docs/$count?api-version=2024-07-01"

    async with httpx.AsyncClient(timeout=15) as http:
        resp = await http.get(api, headers=headers)
        if resp.status_code == 200:
            try:
                return int(resp.text.strip())
            except ValueError:
                return 0
        return 0


# ── Example document management ─────────────────────────────────────


async def upsert_example(
    slug: str,
    content: str,
    *,
    is_positive: bool = True,
    correction_reason: str = "",
    label_source: str = "human_verified",
    email_id: str = "",
    clients: Clients | None = None,
    embedding_vector: Optional[list[float]] = None,
) -> dict:
    """Upsert a single example document into a category's AI Search index.

    This is the primary way to add good/bad examples from the UI. The caller
    should provide a pre-computed embedding vector for best results, or
    the function generates one via ``generate_embedding``.
    """
    if not SEARCH_ENDPOINT:
        return {"status": "disabled"}

    import httpx

    index = _index_name(slug)
    headers = _auth_headers()

    # Generate embedding if not provided
    vector = embedding_vector
    if not vector:
        try:
            from classymail.services.llm_pipeline import generate_embedding
            vector = await generate_embedding(content[:8000], clients=clients)
        except Exception as e:
            logger.warning("Embedding generation failed for example in %s: %s", slug, e)
            vector = [0.0] * EMBEDDING_DIMENSIONS

    doc = {
        "@search.action": "upload",
        "id": str(uuid.uuid4()),
        "email_id": email_id or f"ui-example-{slug}",
        "content": content,
        "label": slug,
        "label_source": label_source,
        "human_verified": label_source in ("human_verified", "human_corrected", "human_reinforced"),
        "is_positive": is_positive,
        "correction_reason": correction_reason,
        "confidence_original": 0.95 if is_positive else 0.15,
        "content_vector": vector,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    api = f"{SEARCH_ENDPOINT}/indexes/{index}/docs/index?api-version=2024-07-01"
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.post(api, headers=headers, json={"value": [doc]})
        if resp.status_code in (200, 207):
            results = resp.json().get("value", [])
            ok = all(r.get("status") for r in results)
            return {"status": "ok" if ok else "partial", "doc_id": doc["id"]}
        return {"status": "error", "detail": resp.text[:300]}


async def list_examples(slug: str, *, top: int = 20) -> list[dict]:
    """List example documents from a category's AI Search index."""
    if not SEARCH_ENDPOINT:
        return []

    import httpx

    index = _index_name(slug)
    headers = _auth_headers()
    api = f"{SEARCH_ENDPOINT}/indexes/{index}/docs?api-version=2024-07-01&$top={top}&$orderby=created_at desc&$select=id,email_id,content,label,label_source,is_positive,correction_reason,human_verified,created_at"

    async with httpx.AsyncClient(timeout=15) as http:
        resp = await http.get(api, headers=headers)
        if resp.status_code != 200:
            return []
        docs = resp.json().get("value", [])
        return [
            {
                "id": d.get("id"),
                "email_id": d.get("email_id"),
                "content": d.get("content", "")[:500],
                "label": d.get("label"),
                "label_source": d.get("label_source"),
                "is_positive": d.get("is_positive"),
                "correction_reason": d.get("correction_reason"),
                "human_verified": d.get("human_verified"),
                "created_at": d.get("created_at"),
            }
            for d in docs
        ]


async def delete_example(slug: str, doc_id: str) -> dict:
    """Delete a specific example from a category's AI Search index."""
    if not SEARCH_ENDPOINT:
        return {"status": "disabled"}

    import httpx

    index = _index_name(slug)
    headers = _auth_headers()
    api = f"{SEARCH_ENDPOINT}/indexes/{index}/docs/index?api-version=2024-07-01"

    payload = {"value": [{"@search.action": "delete", "id": doc_id}]}
    async with httpx.AsyncClient(timeout=15) as http:
        resp = await http.post(api, headers=headers, json=payload)
        if resp.status_code in (200, 207):
            return {"status": "deleted", "doc_id": doc_id}
        return {"status": "error", "detail": resp.text[:300]}
