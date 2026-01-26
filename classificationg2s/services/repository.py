from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Optional

from classificationg2s.models import EmailRecord
from classificationg2s.services.azure_clients import Clients, get_default_clients
from classificationg2s.services.anonymizer import anonymize_markdown_for_finetune


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


async def save_to_cosmos(record: EmailRecord, clients: Clients | None = None) -> None:
    record.updated_at = datetime.now(timezone.utc)
    if record.search_text is None:
        record.search_text = compute_search_text(record.markdown)
    clients = clients or get_default_clients()
    await clients.ensure_cosmos_container()
    await clients.cosmos_container.upsert_item(record.model_dump())


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
    query = "SELECT VALUE AVG(i.confidence) FROM c JOIN i IN c.classification.detected_intents WHERE c.status='PROCESSED'"
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
):
    # Emit UTF-8 BOM (required by Foundry fine-tuning dataset validation)
    yield "\ufeff"

    clients = clients or get_default_clients()
    await clients.ensure_cosmos_container()

    where = ["c.status = 'PROCESSED'", "IS_DEFINED(c.classification)", "c.classification.needs_review = false"]
    if not include_unreviewed:
        where.append("(IS_DEFINED(c.reviewed) AND c.reviewed = true)")

    query = "SELECT c.id, c.markdown, c.classification, c.updated_at FROM c WHERE " + " AND ".join(where)
    it = clients.cosmos_container.query_items(query, enable_cross_partition_query=True)

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
