from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Optional

from classificationg2s.models import EmailRecord
from classificationg2s.services.azure_clients import Clients, get_default_clients
from classificationg2s.services.anonymizer import anonymize_markdown_for_finetune
from classificationg2s.services.llm_pipeline import generate_embedding
from classificationg2s.core import config


def compute_search_text(markdown: str | None, *, max_chars: int = 8192) -> str | None:
    if not markdown:
        return None

    text = markdown
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\t", " ")
    # Cheap normalization to keep a compact, index-friendly search blob.
    text = " ".join(text.split())
    if not text:
        return None
    return text[:max_chars]


def _bound_limit(limit: int) -> int:
    return min(max(limit, 1), config.COSMOS_QUERY_MAX_LIMIT)


def _query(container, query: str, parameters: list[dict] | None = None, max_items: int | None = None):
    # Cosmos SDK supports max_item_count to limit page size, reducing RU burn when ORDER BY + no partition key.
    return container.query_items(query, parameters=parameters, max_item_count=max_items)


async def save_to_cosmos(record: EmailRecord, clients: Clients | None = None) -> None:
    record.updated_at = datetime.now(timezone.utc)
    if record.search_text is None:
        record.search_text = compute_search_text(record.markdown)
    clients = clients or get_default_clients()
    await clients.ensure_cosmos_container()
    await clients.cosmos_container.upsert_item(record.model_dump(mode="json"))


async def count_by_status(status: str, clients: Clients | None = None) -> int:
    clients = clients or get_default_clients()
    await clients.ensure_cosmos_container()
    query = "SELECT VALUE COUNT(1) FROM c WHERE c.status=@status"
    it = clients.cosmos_container.query_items(
        query,
        parameters=[{"name": "@status", "value": status}],
    )
    async for v in it:
        return v
    return 0


async def count_reviewed_ready_items(clients: Clients | None = None) -> int:
    clients = clients or get_default_clients()
    await clients.ensure_cosmos_container()
    query = (
        "SELECT VALUE COUNT(1) FROM c "
        "WHERE c.status='PROCESSED' "
        "AND IS_DEFINED(c.classification) "
        "AND c.classification.needs_review = false "
        "AND (IS_DEFINED(c.reviewed) AND c.reviewed = true) "
        "AND IS_DEFINED(c.classification.detected_intents) "
        "AND ARRAY_LENGTH(c.classification.detected_intents) > 0"
    )
    it = clients.cosmos_container.query_items(query)
    async for v in it:
        return v
    return 0


async def get_average_confidence(*, clients: Clients | None = None) -> float:
    clients = clients or get_default_clients()
    await clients.ensure_cosmos_container()
    query = "SELECT VALUE AVG(i.confidence) FROM c JOIN i IN c.classification.detected_intents WHERE c.status IN ('PROCESSED','REVIEW_REQUIRED')"
    it = clients.cosmos_container.query_items(query)
    async for v in it:
        return float(v or 0.0)
    return 0.0


async def _scalar_query(query: str, *, clients: Clients | None = None, parameters: list[dict] | None = None):
    clients = clients or get_default_clients()
    await clients.ensure_cosmos_container()
    it = clients.cosmos_container.query_items(
        query,
        parameters=parameters,
    )
    async for v in it:
        return v
    return None


async def sum_phi4_cost_usd(*, clients: Clients | None = None) -> float:
    v = await _scalar_query(
        "SELECT VALUE SUM(c.usage.phi4_cost_usd) FROM c WHERE IS_DEFINED(c.usage) AND IS_DEFINED(c.usage.phi4_cost_usd)",
        clients=clients,
    )
    return float(v or 0.0)


async def sum_mistral_cost_usd(*, clients: Clients | None = None) -> float:
    v = await _scalar_query(
        "SELECT VALUE SUM(c.usage.mistral.cost_usd) FROM c WHERE IS_DEFINED(c.usage) AND IS_DEFINED(c.usage.mistral) AND IS_DEFINED(c.usage.mistral.cost_usd)",
        clients=clients,
    )
    return float(v or 0.0)


async def count_items_with_any_usage_cost(*, clients: Clients | None = None) -> int:
    v = await _scalar_query(
        "SELECT VALUE COUNT(1) FROM c WHERE (IS_DEFINED(c.usage.phi4_cost_usd) OR IS_DEFINED(c.usage.mistral.cost_usd))",
        clients=clients,
    )
    return int(v or 0)


async def export_finetune_jsonl_iter(
    *,
    clients: Clients | None = None,
    anonymize: bool,
    include_unreviewed: bool,
    max_examples: Optional[int],
    taxonomy_version: str,
    include_metadata: bool,
    split_mode: str = "all",
    test_ratio: float = 0.2
):
    # Emit UTF-8 BOM (required by Foundry fine-tuning dataset validation)
    yield "\ufeff"

    clients = clients or get_default_clients()
    await clients.ensure_cosmos_container()

    where = ["c.status = 'PROCESSED'", "IS_DEFINED(c.classification)", "c.classification.needs_review = false"]
    if not include_unreviewed:
        where.append("(IS_DEFINED(c.reviewed) AND c.reviewed = true)")

    query = "SELECT c.id, c.markdown, c.classification, c.updated_at FROM c WHERE " + " AND ".join(where)
    it = clients.cosmos_container.query_items(query)

    system_prompt = os.getenv(
        "FINETUNE_SYSTEM_PROMPT",
        "You classify insurance emails into intents and output strict JSON only.",
    )

    written = 0
    async for item in it:
        if max_examples is not None and written >= max_examples:
            break

        classification = item.get("classification") or {}
        intents = classification.get("detected_intents") or []
        if not intents:
            continue

        # Split logic: use a stable hash of the ID to determine if it's train or test
        item_id = item.get("id") or ""
        # Create a deterministic float 0.0-1.0 from the ID
        h = int(hashlib.sha256(item_id.encode("utf-8")).hexdigest(), 16)
        # Normalize to 0-1
        normalized_hash = (h % 1000) / 1000.0

        if split_mode == "train":
            if normalized_hash < test_ratio:
                # This item belongs to "test" bucket (0 to 0.2), so skip it for "train"
                continue
        elif split_mode == "test":
             if normalized_hash >= test_ratio:
                 # This item belongs to "train" bucket (0.2 to 1.0), so skip it for "test"
                 continue

        # Proceed with generation
        raw_markdown = item.get("markdown") or ""
        anonymization_meta = None
        user_markdown = raw_markdown

        if anonymize:
            try:
                anon = await anonymize_markdown_for_finetune(raw_markdown, clients=clients)
                user_markdown = anon.get("anonymized_markdown") or ""
                anonymization_meta = {
                    "model": anon.get("model"),
                    "prompt_version": anon.get("prompt_version"),
                    "usage": anon.get("usage"),
                }
            except Exception:
                continue

        target = {"detected_intents": intents}
        if classification.get("global_complexity"):
            target["global_complexity"] = classification.get("global_complexity")

        assistant_content = json.dumps(target, ensure_ascii=False)
        example = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_markdown},
                {"role": "assistant", "content": assistant_content},
            ]
        }
        if include_metadata:
            example["metadata"] = {
                "example_id": item.get("id"),
                "taxonomy_version": taxonomy_version,
                "source": "human_review",
                "updated_at": item.get("updated_at"),
                "anonymized": bool(anonymize),
                "anonymization": anonymization_meta,
                "hash": hashlib.sha256((user_markdown + assistant_content).encode("utf-8")).hexdigest(),
            }

        yield json.dumps(example, ensure_ascii=False) + "\n"
        written += 1


async def search_email_records(q: str, limit: int = 5, clients: Clients | None = None) -> list[dict]:
    clients = clients or get_default_clients()
    await clients.ensure_cosmos_container()
    limit = _bound_limit(limit)
    query = (
        "SELECT c.id, c.status, c.file_url, c.subject, c.error, c.updated_at, c.processing_time_ms FROM c "
        "WHERE CONTAINS(c.id, @q) OR (IS_DEFINED(c.subject) AND CONTAINS(c.subject, @q)) "
        "OFFSET 0 LIMIT @limit"
    )
    params = [
        {"name": "@q", "value": q},
        {"name": "@limit", "value": limit},
    ]
    items = [x async for x in _query(clients.cosmos_container, query, parameters=params, max_items=limit)]
    return items


async def get_email_by_id(item_id: str, clients: Clients | None = None) -> dict | None:
    clients = clients or get_default_clients()
    await clients.ensure_cosmos_container()
    query = "SELECT * FROM c WHERE c.id=@id"
    params = [{"name": "@id", "value": item_id}]
    it = clients.cosmos_container.query_items(query, parameters=params)
    async for item in it:
        return item
    return None


async def search_email_by_text(q: str, limit: int = 5, clients: Clients | None = None) -> list[dict]:
    clients = clients or get_default_clients()
    await clients.ensure_cosmos_container()
    limit = _bound_limit(limit)
    query = (
        "SELECT c.id, c.status, c.file_url, c.subject, c.error, c.updated_at, c.processing_time_ms FROM c "
        "WHERE IS_DEFINED(c.search_text) AND CONTAINS(c.search_text, @q) "
        "OFFSET 0 LIMIT @limit"
    )
    params = [
        {"name": "@q", "value": q},
        {"name": "@limit", "value": limit},
    ]
    items = [x async for x in _query(clients.cosmos_container, query, parameters=params, max_items=limit)]
    return items


async def search_similar_emails(q: str, limit: int = 5, clients: Clients | None = None) -> list[dict]:
    clients = clients or get_default_clients()
    await clients.ensure_cosmos_container()
    limit = _bound_limit(limit)

    # Generate vector for query
    vector = await generate_embedding(q, clients=clients)
    if not vector:
         # Fallback to text search if embedding fails
         return await search_email_by_text(q, limit, clients)

    # Vector Search Query (Cosine Distance)
    query = (
        "SELECT TOP @limit c.id, c.status, c.file_url, c.subject, c.error, c.updated_at, c.processing_time_ms, VectorDistance(c.vector, @vector) as distance "
        "FROM c "
        "WHERE IS_DEFINED(c.vector) "
        "ORDER BY VectorDistance(c.vector, @vector) ASC"
    )

    params = [
        {"name": "@vector", "value": vector},
        {"name": "@limit", "value": limit},
    ]

    # Note: Vector search requires container with Vector Policy.
    try:
        items = [x async for x in _query(clients.cosmos_container, query, parameters=params, max_items=limit)]
        return items
    except Exception:
        # If vector search fails (e.g. policy not applied), fallback
        return await search_email_by_text(q, limit, clients)



async def get_latest_errors(limit: int = 5, clients: Clients | None = None) -> list[dict]:
    clients = clients or get_default_clients()
    await clients.ensure_cosmos_container()
    limit = _bound_limit(limit)
    query = (
        "SELECT c.id, c.subject, c.error, c.updated_at FROM c "
        "WHERE c.status='ERROR' ORDER BY c._ts DESC OFFSET 0 LIMIT @limit"
    )
    params = [{"name": "@limit", "value": limit}]
    items = [x async for x in _query(clients.cosmos_container, query, parameters=params, max_items=limit)]
    return items


async def get_stats_summary(clients: Clients | None = None) -> dict:
    clients = clients or get_default_clients()
    # Reuse existing helpers to avoid duplicating queries
    pending = await count_by_status("PENDING", clients=clients)
    processing = await count_by_status("PROCESSING", clients=clients)
    processed = await count_by_status("PROCESSED", clients=clients)
    error = await count_by_status("ERROR", clients=clients)
    review_required = await count_by_status("REVIEW_REQUIRED", clients=clients)
    total = pending + processing + processed + error + review_required
    return {
        "total": total,
        "pending": pending,
        "processing": processing,
        "processed": processed,
        "error": error,
        "review_required": review_required,
        "average_confidence": await get_average_confidence(clients=clients),
    }


async def get_top_intents(limit: int = 5, clients: Clients | None = None) -> list[dict]:
    clients = clients or get_default_clients()
    await clients.ensure_cosmos_container()
    limit = _bound_limit(limit)
    query = (
        "SELECT i.intent as intent, COUNT(1) as doc_count "
        "FROM c JOIN i IN c.classification.detected_intents "
        "WHERE c.status='PROCESSED' "
        "GROUP BY i.intent ORDER BY doc_count DESC OFFSET 0 LIMIT @limit"
    )
    params = [{"name": "@limit", "value": limit}]
    items = [x async for x in _query(clients.cosmos_container, query, parameters=params, max_items=limit)]
    return items


async def get_low_confidence_items(limit: int = 5, intent: str | None = None, clients: Clients | None = None) -> list[dict]:
    clients = clients or get_default_clients()
    await clients.ensure_cosmos_container()
    limit = _bound_limit(limit)
    if intent:
        query = (
            "SELECT c.id, c.status, c.subject, c.updated_at, "
            " ARRAY_MAX(ARRAY(SELECT VALUE i.confidence FROM i IN c.classification.detected_intents WHERE i.intent=@intent)) AS intent_confidence "
            "FROM c "
            "WHERE c.status='PROCESSED' "
            " AND ARRAY_LENGTH(c.classification.detected_intents) > 0 "
            " AND EXISTS(SELECT VALUE 1 FROM i IN c.classification.detected_intents WHERE i.intent=@intent) "
            "ORDER BY intent_confidence ASC OFFSET 0 LIMIT @limit"
        )
        params = [
            {"name": "@intent", "value": intent},
            {"name": "@limit", "value": limit},
        ]
    else:
        query = (
            "SELECT c.id, c.status, c.subject, c.updated_at, "
            " ARRAY_MAX(ARRAY(SELECT VALUE i.confidence FROM i IN c.classification.detected_intents)) AS max_confidence "
            "FROM c "
            "WHERE c.status='PROCESSED' AND ARRAY_LENGTH(c.classification.detected_intents) > 0 "
            "ORDER BY max_confidence ASC OFFSET 0 LIMIT @limit"
        )
        params = [
            {"name": "@limit", "value": limit},
        ]
    items = [x async for x in _query(clients.cosmos_container, query, parameters=params, max_items=limit)]
    return items


async def get_processing_stats_by_day(days: int = 7, clients: Clients | None = None) -> list[dict]:
    clients = clients or get_default_clients()
    await clients.ensure_cosmos_container()
    days = max(1, min(days, 30))
    query = (
        "SELECT STRING(TimestampToDateTime("
        "   DateTimeToTimestamp(c.updated_at) - (DateTimeToTimestamp(c.updated_at) % 86400)"
        ")) as day, "
        " COUNT(1) as count, "
        " SUM(c.processing_time_ms) as sum_ms, "
        " AVG(c.processing_time_ms) as avg_ms "
        "FROM c "
        "WHERE c.status='PROCESSED' AND IS_DEFINED(c.processing_time_ms) "
        " AND c.updated_at >= DateTimeAdd('day', -@days, GetCurrentDateTime()) "
        "GROUP BY STRING(TimestampToDateTime("
        "   DateTimeToTimestamp(c.updated_at) - (DateTimeToTimestamp(c.updated_at) % 86400)"
        ")) "
        "ORDER BY day DESC"
    )
    params = [{"name": "@days", "value": days}]
    items = [x async for x in _query(clients.cosmos_container, query, parameters=params, max_items=days)]
    return items
