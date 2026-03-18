from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from opentelemetry import trace

from classymail.models import EmailRecord
from classymail.services.azure_clients import Clients, get_default_clients
from classymail.services.anonymizer import anonymize_markdown_for_finetune, basic_pii_scrub
from classymail.services.settings_store import get_categories_prompt_text_async
from classymail.services.llm_pipeline import generate_embedding
from classymail.core import config

logger = logging.getLogger("ClassyMail.repository")
tracer = trace.get_tracer(__name__)


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


def _bound_limit(limit: int, max_val: int = 50) -> int:
    return min(max(limit, 1), config.COSMOS_QUERY_MAX_LIMIT)


def _query(container, query: str, parameters: list[dict] | None = None, max_items: int | None = None):
    # Cosmos SDK supports max_item_count to limit page size, reducing RU burn when ORDER BY + no partition key.
    return container.query_items(query, parameters=parameters if parameters is not None else [], max_item_count=max_items)


async def save_to_cosmos(record: EmailRecord, clients: Clients | None = None) -> None:
    record.updated_at = datetime.now(timezone.utc)
    if record.search_text is None:
        record.search_text = compute_search_text(record.markdown)
    clients = clients or get_default_clients()
    await clients.ensure_cosmos_container()
    # Ensure type for filtering
    payload = record.model_dump(mode="json")
    payload.setdefault("type", "email")
    await clients.cosmos_container.upsert_item(payload)

    # Optional: save chunks attached to record (set by pipeline)
    chunks = getattr(record, "chunks", None)
    if chunks:
        await save_chunks(record.id, chunks, subject=record.subject, file_url=record.file_url, clients=clients)


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
        parameters=parameters if parameters is not None else [],
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


async def sum_llm_tokens(*, clients: Clients | None = None) -> dict:
    """Aggregate prompt/completion tokens across all processed emails."""
    prompt_q = "SELECT VALUE SUM(c.usage.phi4.prompt_tokens) FROM c WHERE IS_DEFINED(c.usage) AND IS_DEFINED(c.usage.phi4)"
    comp_q = "SELECT VALUE SUM(c.usage.phi4.completion_tokens) FROM c WHERE IS_DEFINED(c.usage) AND IS_DEFINED(c.usage.phi4)"

    p = await _scalar_query(prompt_q, clients=clients)
    c = await _scalar_query(comp_q, clients=clients)

    return {
        "prompt_tokens": int(p or 0),
        "completion_tokens": int(c or 0),
    }


async def sum_mistral_cost_usd(*, clients: Clients | None = None) -> float:
    v = await _scalar_query(
        "SELECT VALUE SUM(c.usage.mistral.cost_usd) FROM c WHERE IS_DEFINED(c.usage) AND IS_DEFINED(c.usage.mistral) AND IS_DEFINED(c.usage.mistral.cost_usd)",
        clients=clients,
    )
    return float(v or 0.0)


async def sum_di_cost_usd(*, clients: Clients | None = None) -> float:
    v = await _scalar_query(
        "SELECT VALUE SUM(c.usage.doc_intelligence.cost_usd) FROM c WHERE IS_DEFINED(c.usage) AND IS_DEFINED(c.usage.doc_intelligence) AND IS_DEFINED(c.usage.doc_intelligence.cost_usd)",
        clients=clients,
    )
    return float(v or 0.0)


async def count_items_with_any_usage_cost(*, clients: Clients | None = None) -> int:
    v = await _scalar_query(
        "SELECT VALUE COUNT(1) FROM c WHERE (IS_DEFINED(c.usage.phi4_cost_usd) OR IS_DEFINED(c.usage.mistral.cost_usd) OR IS_DEFINED(c.usage.doc_intelligence.cost_usd))",
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

    query = "SELECT c.id, c.markdown, c.classification, c.updated_at, c.reviewed, c.correction_reason, c.classification_history, c.subject, c.sender FROM c WHERE " + " AND ".join(where)
    it = clients.cosmos_container.query_items(query)

    # Get production-grade system prompt with categories (matches inference exactly)
    categories_text = await get_categories_prompt_text_async(clients=clients)

    system_prompt = os.getenv(
        "FINETUNE_SYSTEM_PROMPT",
        f"""Tu es un assistant expert en classification d'emails d'service.
Ta tâche est d'analyser le contenu de l'email (fourni en markdown) et d'identifier :
- TOUTES les intentions présentes.
- Le sujet principal (Subject).
- L'expéditeur (Sender) si identifiable.

LISTE DES INTENTIONS POSSIBLES (NOM + DÉFINITION + EXCLUSIONS) :
{categories_text}

RÈGLES DE CLASSIFICATION :
- Choisis les intentions dont la DÉFINITION correspond le mieux au contenu. Appuie-toi sur les mots/phrases clés des définitions.
- Les EXCLUSIONS précisent ce que chaque catégorie ne doit PAS inclure. Utilise-les pour éliminer les faux positifs.
- Un email peut contenir UNE SEULE intention OU PLUSIEURS intentions.
- Si aucune intention ne correspond vraiment, retourne une liste vide (detected_intents: []). NE PAS deviner.
- Assigne un score de confiance (0.0 à 1.0) pour CHAQUE intention détectée.
- La justification DOIT citer un extrait du texte et/ou la définition de la catégorie correspondante.

FORMAT DE RÉPONSE ATTENDU (JSON UNIQUEMENT) :
{{
    "detected_intents": [
        {{
            "intent": "Nom de l'intention",
            "confidence": 0.95,
            "justification": "Court extrait du texte ou référence à la description justifiant ce choix"
        }}
    ],
    "global_complexity": "Simple|Complexe",
    "classification_reason": "Explication courte si detected_intents est vide (ex: 'Aucune intention ne correspond car le contenu est hors périmètre service')",
    "subject": "Sujet ou Objet de l'email extrait du texte",
    "sender": "Nom ou Email de l'expéditeur extrait"
}}

IMPORTANT: Si detected_intents est vide, TOUJOURS remplir classification_reason avec une explication claire."""
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

        # Build complete response matching production inference format
        target = {
            "detected_intents": intents,
            "global_complexity": classification.get("global_complexity") or "Simple",
        }

        # Include classification_reason if available (especially for empty intents)
        if classification.get("classification_reason"):
            target["classification_reason"] = classification.get("classification_reason")

        # Include subject and sender from email metadata if available
        # Apply PII scrubbing if anonymize is enabled to prevent leaking raw emails/names
        if item.get("subject"):
            subject = item.get("subject")
            target["subject"] = basic_pii_scrub(subject) if anonymize else subject
        if item.get("sender"):
            sender = item.get("sender")
            target["sender"] = basic_pii_scrub(sender) if anonymize else sender

        assistant_content = json.dumps(target, ensure_ascii=False, indent=None)
        example = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_markdown},
                {"role": "assistant", "content": assistant_content},
            ]
        }
        if include_metadata:
            # Track if this is a human-corrected example (reinforcement learning signal)
            is_corrected = item.get("reviewed", False) and item.get("classification_history")
            correction_metadata = None

            if is_corrected:
                history = item.get("classification_history", [])
                if history:
                    # Get the latest correction entry
                    latest = history[-1]
                    correction_metadata = {
                        "was_corrected": True,
                        "correction_reason": item.get("correction_reason") or latest.get("correction_reason"),
                        "llm_feedback": latest.get("llm_feedback"),
                        "correction_timestamp": latest.get("timestamp"),
                    }

            example["metadata"] = {
                "example_id": item.get("id"),
                "taxonomy_version": taxonomy_version,
                "source": "human_corrected" if is_corrected else "auto_classified",
                "updated_at": item.get("updated_at"),
                "anonymized": bool(anonymize),
                "anonymization": anonymization_meta,
                "correction": correction_metadata,
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
    """Point read by ID — 1 RU instead of cross-partition query."""
    clients = clients or get_default_clients()
    await clients.ensure_cosmos_container()
    try:
        return await clients.cosmos_container.read_item(item=item_id, partition_key=item_id)
    except Exception:
        return None


async def search_email_by_text(q: str, limit: int = 5, days: int | None = None, clients: Clients | None = None) -> list[dict]:
    clients = clients or get_default_clients()
    await clients.ensure_cosmos_container()
    limit = _bound_limit(limit)
    # Case-insensitive search, exclude chunk documents
    date_filter = ""
    params = [
        {"name": "@q", "value": q},
        {"name": "@limit", "value": limit},
    ]
    if days and days > 0:
        date_filter = " AND c.created_at >= DateTimeAdd('day', -@days, GetCurrentDateTime()) "
        params.append({"name": "@days", "value": min(days, 365)})
    query = (
        "SELECT c.id, c.status, c.file_url, c.subject, c.sender, c.error, c.updated_at, c.processing_time_ms FROM c "
        "WHERE IS_DEFINED(c.search_text) AND CONTAINS(LOWER(c.search_text), LOWER(@q)) "
        "AND (NOT IS_DEFINED(c.type) OR c.type != 'chunk') "
        f"{date_filter}"
        "OFFSET 0 LIMIT @limit"
    )
    params = [
        {"name": "@q", "value": q},
        {"name": "@limit", "value": limit},
    ]
    items = [x async for x in _query(clients.cosmos_container, query, parameters=params, max_items=limit)]
    return items


async def save_chunks(parent_id: str, chunks: list[dict], *, subject: str | None = None, file_url: str | None = None, clients: Clients | None = None) -> None:
    clients = clients or get_default_clients()
    await clients.ensure_cosmos_container()
    # Each chunk: {content, vector, index}
    docs = []
    for ch in chunks:
        idx = ch.get("index")
        content = ch.get("content")
        vector = ch.get("vector")
        doc = {
            "id": f"{parent_id}::chunk-{idx}",
            "type": "chunk",
            "parent_id": parent_id,
            "chunk_index": idx,
            "content": content,
            "vector": vector,
            "subject": subject,
            "file_url": file_url,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        docs.append(doc)
    # Upsert sequentially (batch SDK not used here)
    for d in docs:
        await clients.cosmos_container.upsert_item(d)


async def search_chunks_by_vector(q: str, limit: int = 5, clients: Clients | None = None) -> list[dict]:
    with tracer.start_as_current_span("repository.search_chunks_by_vector") as span:
        span.set_attribute("db.cosmosdb.limit", limit)
        clients = clients or get_default_clients()
        await clients.ensure_cosmos_container()
        limit = _bound_limit(limit)
        vector = await generate_embedding(q, clients=clients)
        if not vector:
            logger.warning("search_chunks_by_vector: embedding returned empty, skipping vector search")
            span.set_attribute("db.cosmosdb.embedding_empty", True)
            return []
        span.set_attribute("db.cosmosdb.vector_dims", len(vector))
        query = (
            "SELECT TOP @limit c.id, c.parent_id, c.subject, c.file_url, c.chunk_index, c.content, "
            "VectorDistance(c.vector, @vector) as distance "
            "FROM c WHERE c.type = 'chunk' AND IS_DEFINED(c.vector) AND ARRAY_LENGTH(c.vector) > 0 "
            "ORDER BY VectorDistance(c.vector, @vector) ASC"
        )
        params = [
            {"name": "@vector", "value": vector},
            {"name": "@limit", "value": limit},
        ]
        try:
            items = [x async for x in _query(clients.cosmos_container, query, parameters=params, max_items=limit)]
            span.set_attribute("db.cosmosdb.result_count", len(items))
            logger.info("search_chunks_by_vector: found %d chunks", len(items))
            return items
        except Exception as e:
            logger.error("search_chunks_by_vector failed: %s", e, exc_info=True)
            span.set_attribute("error.type", type(e).__name__)
            span.set_attribute("error.message", str(e))
            return []

async def search_similar_emails(q: str, limit: int = 5, days: int | None = None, clients: Clients | None = None) -> list[dict]:
    with tracer.start_as_current_span("repository.search_similar_emails") as span:
        span.set_attribute("db.cosmosdb.limit", limit)
        clients = clients or get_default_clients()
        await clients.ensure_cosmos_container()
        limit = _bound_limit(limit)

        # Generate vector for query
        vector = await generate_embedding(q, clients=clients)
        if not vector:
            logger.warning("search_similar_emails: embedding returned empty, falling back to text search")
            span.set_attribute("db.cosmosdb.fallback", "embedding_empty")
            return await search_email_by_text(q, limit, days=days, clients=clients)

        span.set_attribute("db.cosmosdb.vector_dims", len(vector))

        # Build optional date filter
        date_filter = ""
        params = [
            {"name": "@vector", "value": vector},
            {"name": "@limit", "value": limit},
        ]
        if days and days > 0:
            date_filter = "AND c.created_at >= DateTimeAdd('day', -@days, GetCurrentDateTime()) "
            params.append({"name": "@days", "value": min(days, 365)})

        # Vector Search Query — match only email documents with valid vectors
        query = (
            "SELECT TOP @limit c.id, c.status, c.file_url, c.subject, c.sender, "
            "c.classification.detected_intents, c.error, c.updated_at, c.processing_time_ms, "
            "VectorDistance(c.vector, @vector) as distance "
            "FROM c "
            "WHERE c.type = 'email' AND ARRAY_LENGTH(c.vector) > 0 "
            f"{date_filter}"
            "ORDER BY VectorDistance(c.vector, @vector) ASC"
        )

        try:
            items = [x async for x in _query(clients.cosmos_container, query, parameters=params, max_items=limit)]
            span.set_attribute("db.cosmosdb.result_count", len(items))
            logger.info("search_similar_emails: found %d results via vector search", len(items))
            return items
        except Exception as e:
            logger.error("search_similar_emails vector query failed: %s", e, exc_info=True)
            span.set_attribute("error.type", type(e).__name__)
            span.set_attribute("error.message", str(e))
            span.set_attribute("db.cosmosdb.fallback", "vector_query_error")
            return await search_email_by_text(q, limit, days=days, clients=clients)



async def get_seed_examples_for_synthesis(limit: int = 10, clients: Clients | None = None) -> list[dict]:
    clients = clients or get_default_clients()
    await clients.ensure_cosmos_container()
    limit = _bound_limit(limit)
    # Fetch processed items that have valid classification
    query = (
        "SELECT c.markdown, c.classification, c.subject FROM c "
        "WHERE c.status='PROCESSED' "
        "AND IS_DEFINED(c.classification) "
        "AND IS_DEFINED(c.markdown) "
        "ORDER BY c._ts DESC OFFSET 0 LIMIT @limit"
    )
    params = [{"name": "@limit", "value": limit}]
    items = [x async for x in _query(clients.cosmos_container, query, parameters=params, max_items=limit)]
    return items


async def save_synthetic_record(record: dict, clients: Clients | None = None) -> None:
    clients = clients or get_default_clients()
    await clients.ensure_cosmos_container()
    # Ensure it looks like a regular record
    # record should have id, markdown, classification, status='PROCESSED', etc.
    await clients.cosmos_container.upsert_item(record)


async def get_latest_errors(limit: int = 5, clients: Clients | None = None) -> list[dict]:
    with tracer.start_as_current_span("repository.get_latest_errors") as span:
        span.set_attribute("db.cosmosdb.limit", limit)
        try:
            clients = clients or get_default_clients()
            await clients.ensure_cosmos_container()
            limit = _bound_limit(limit)
            query = (
                "SELECT c.id, c.subject, c.error, c.updated_at FROM c "
                "WHERE c.status='ERROR' ORDER BY c._ts DESC OFFSET 0 LIMIT @limit"
            )
            params = [{"name": "@limit", "value": limit}]
            items = [x async for x in _query(clients.cosmos_container, query, parameters=params, max_items=limit)]
            span.set_attribute("db.cosmosdb.result_count", len(items))
            return items
        except Exception as e:
            logger.error("get_latest_errors failed: %s", e, exc_info=True)
            span.set_attribute("error.type", type(e).__name__)
            span.set_attribute("error.message", str(e))
            raise


async def get_stats_summary(clients: Clients | None = None) -> dict:
    with tracer.start_as_current_span("repository.get_stats_summary") as span:
        try:
            clients = clients or get_default_clients()
            # Reuse existing helpers to avoid duplicating queries
            pending = await count_by_status("PENDING", clients=clients)
            processing = await count_by_status("PROCESSING", clients=clients)
            processed = await count_by_status("PROCESSED", clients=clients)
            error = await count_by_status("ERROR", clients=clients)
            review_required = await count_by_status("REVIEW_REQUIRED", clients=clients)
            total = pending + processing + processed + error + review_required
            span.set_attribute("db.cosmosdb.total", total)
            return {
                "total": total,
                "pending": pending,
                "processing": processing,
                "processed": processed,
                "error": error,
                "review_required": review_required,
                "average_confidence": await get_average_confidence(clients=clients),
            }
        except Exception as e:
            logger.error("get_stats_summary failed: %s", e, exc_info=True)
            span.set_attribute("error.type", type(e).__name__)
            span.set_attribute("error.message", str(e))
            raise


async def get_top_intents(limit: int = 5, clients: Clients | None = None) -> list[dict]:
    """Get top classification intents by document count.

    Cosmos DB NoSQL does not support ORDER BY on aggregate aliases in
    GROUP BY queries, so we fetch all groups and sort/limit in Python.
    """
    with tracer.start_as_current_span("repository.get_top_intents") as span:
        span.set_attribute("db.cosmosdb.limit", limit)
        try:
            clients = clients or get_default_clients()
            await clients.ensure_cosmos_container()
            limit = _bound_limit(limit)
            query = (
                "SELECT i.intent AS intent, COUNT(1) AS doc_count "
                "FROM c JOIN i IN c.classification.detected_intents "
                "WHERE c.status='PROCESSED' "
                "GROUP BY i.intent"
            )
            # Fetch all groups then sort/limit client-side
            items = [x async for x in _query(clients.cosmos_container, query)]
            items.sort(key=lambda x: x.get("doc_count", 0), reverse=True)
            items = items[:limit]
            span.set_attribute("db.cosmosdb.result_count", len(items))
            return items
        except Exception as e:
            logger.error("get_top_intents failed: %s", e, exc_info=True)
            span.set_attribute("error.type", type(e).__name__)
            span.set_attribute("error.message", str(e))
            raise


async def get_low_confidence_items(limit: int = 5, intent: str | None = None, clients: Clients | None = None) -> list[dict]:
    """Get lowest-confidence processed emails.

    Cosmos DB NoSQL does not support ORDER BY on computed sub-query
    expressions, so we fetch candidates and sort/limit in Python.
    """
    with tracer.start_as_current_span("repository.get_low_confidence_items") as span:
        span.set_attribute("db.cosmosdb.limit", limit)
        span.set_attribute("db.cosmosdb.intent_filter", intent or "")
        try:
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
                )
                params = [{"name": "@intent", "value": intent}]
                sort_key = "intent_confidence"
            else:
                query = (
                    "SELECT c.id, c.status, c.subject, c.updated_at, "
                    " ARRAY_MAX(ARRAY(SELECT VALUE i.confidence FROM i IN c.classification.detected_intents)) AS max_confidence "
                    "FROM c "
                    "WHERE c.status='PROCESSED' AND ARRAY_LENGTH(c.classification.detected_intents) > 0 "
                )
                params = []
                sort_key = "max_confidence"
            # Fetch then sort/limit client-side
            items = [x async for x in _query(clients.cosmos_container, query, parameters=params)]
            items.sort(key=lambda x: x.get(sort_key) or 0.0)
            items = items[:limit]
            span.set_attribute("db.cosmosdb.result_count", len(items))
            return items
        except Exception as e:
            logger.error("get_low_confidence_items failed: %s", e, exc_info=True)
            span.set_attribute("error.type", type(e).__name__)
            span.set_attribute("error.message", str(e))
            raise


async def get_processing_stats_by_day(days: int = 7, clients: Clients | None = None) -> list[dict]:
    clients = clients or get_default_clients()
    await clients.ensure_cosmos_container()
    days = max(1, min(days, 30))
    with tracer.start_as_current_span("repository.get_processing_stats_by_day") as span:
        span.set_attribute("db.cosmosdb.days", days)
        try:
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
            )
            params = [{"name": "@days", "value": days}]
            items = [x async for x in _query(clients.cosmos_container, query, parameters=params, max_items=days)]
            # Sort client-side: Cosmos DB doesn't support ORDER BY on GROUP BY aggregates
            items.sort(key=lambda x: x.get("day", ""), reverse=True)
            span.set_attribute("db.cosmosdb.result_count", len(items))
            return items
        except Exception as e:
            logger.error("get_processing_stats_by_day failed: %s", e, exc_info=True)
            span.set_attribute("error.type", type(e).__name__)
            span.set_attribute("error.message", str(e))
            return []


# --- Chat History & Semantic Cache ---

async def append_chat_history_entry(session_id: str, role: str, content: str, sources: list[dict] | None = None, clients: Clients | None = None) -> None:
    clients = clients or get_default_clients()
    await clients.ensure_rag_containers()
    doc = {
        "id": f"{session_id}:{datetime.now(timezone.utc).isoformat()}",
        "session_id": session_id,
        "role": role,
        "content": content,
        "sources": sources or [],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "type": "chat_history"
    }
    await clients.cosmos_chat_container.upsert_item(doc)


async def get_chat_history(session_id: str, limit: int = 20, clients: Clients | None = None) -> list[dict]:
    clients = clients or get_default_clients()
    await clients.ensure_rag_containers()
    query = """
    SELECT * FROM c WHERE c.session_id = @session_id
    ORDER BY c.created_at DESC
    """
    params = [{"name": "@session_id", "value": session_id}]
    items = [x async for x in clients.cosmos_chat_container.query_items(query, parameters=params, max_item_count=limit)]
    return list(reversed(items))


async def get_cache_entry(vector: list[float], similarity_score: float = 0.99, num_results: int = 1, clients: Clients | None = None) -> list[dict]:
    clients = clients or get_default_clients()
    await clients.ensure_rag_containers()
    query = """
    SELECT TOP @num_results *
    FROM c
    WHERE VectorDistance(c.vector,@embedding) > @similarity_score
    ORDER BY VectorDistance(c.vector,@embedding)
    """
    params = [
        {"name": "@embedding", "value": vector},
        {"name": "@num_results", "value": num_results},
        {"name": "@similarity_score", "value": similarity_score},
    ]
    results = clients.cosmos_cache_container.query_items(query, parameters=params, populate_query_metrics=True)
    return [x async for x in results]


async def set_cache_entry(prompt: str, vector: list[float], response: str, sources: list[dict] | None = None, clients: Clients | None = None) -> None:
    clients = clients or get_default_clients()
    await clients.ensure_rag_containers()
    doc = {
        "id": f"cache:{hashlib.sha256(prompt.encode('utf-8')).hexdigest()}",
        "prompt": prompt,
        "response": response,
        "sources": sources or [],
        "vector": vector,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "type": "cache_entry"
    }
    await clients.cosmos_cache_container.upsert_item(doc)
