from __future__ import annotations

import asyncio
import os
from typing import Optional

from azure.cosmos import PartitionKey
from azure.cosmos.aio import CosmosClient
from azure.identity.aio import DefaultAzureCredential

from classificationg2s.core import config


_credential: DefaultAzureCredential | None = None
_cosmos_client: CosmosClient | None = None
cosmos_container = None
_cosmos_lock = asyncio.Lock()


async def ensure_cosmos_container() -> None:
    global _credential, _cosmos_client, cosmos_container

    if cosmos_container is not None:
        return
    if not config.COSMOS_ENDPOINT:
        raise RuntimeError("AZURE_COSMOS_ENDPOINT is not set")

    async with _cosmos_lock:
        if cosmos_container is not None:
            return

        if _credential is None:
            _credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)

        if _cosmos_client is None:
            _cosmos_client = CosmosClient(
                config.COSMOS_ENDPOINT,
                credential=_credential if not config.COSMOS_KEY else None,
                key=config.COSMOS_KEY,
            )

        db = await _cosmos_client.create_database_if_not_exists(id=config.COSMOS_DB)
        cosmos_container = await db.create_container_if_not_exists(
            id=config.COSMOS_CONTAINER,
            partition_key=PartitionKey(path="/id"),
        )


async def close_cosmos() -> None:
    global _credential, _cosmos_client

    if _cosmos_client is not None:
        await _cosmos_client.close()
        _cosmos_client = None

    if _credential is not None:
        await _credential.close()
        _credential = None





async def export_cosmos_to_csv(path: str = "./data/output.csv"):
    import csv

    await ensure_cosmos_container()

    query = "SELECT c.id, c.file_url, c.status, c.confidence, c.classification, c.markdown FROM c"
    it = cosmos_container.query_items(query)

    out_dir = os.path.dirname(path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "id",
                "file_url",
                "status",
                "intents",
                "needs_review",
                "global_complexity",
                "phi4_cost_usd",
                "mistral_cost_usd",
            ]
        )
        async for item in it:
            classification = item.get("classification") or {}
            intents = classification.get("detected_intents") or []
            intents_str = "|".join([f"{i.get('intent')}:{i.get('confidence')}" for i in intents])
            writer.writerow(
                [
                    item.get("id"),
                    item.get("file_url"),
                    item.get("status"),
                    intents_str,
                    classification.get("needs_review", False),
                    classification.get("global_complexity"),
                    (item.get("usage") or {}).get("phi4_cost_usd"),
                    (item.get("usage") or {}).get("mistral", {}).get("cost_usd")
                    if isinstance((item.get("usage") or {}).get("mistral"), dict)
                    else None,
                ]
            )
    return path


async def export_cosmos_to_finetune_jsonl(
    path: str = "./data/fine_tune.jsonl",
    anonymize: bool = True,
    include_unreviewed: bool = False,
    max_examples: Optional[int] = None,
    taxonomy_version: str = "v1",
):
    # Kept for backward compatibility with the README CLI.
    # Prefer the HTTP endpoint for streaming exports.

    import hashlib
    import json

    from classificationg2s.services.anonymizer import anonymize_markdown_for_finetune

    await ensure_cosmos_container()

    out_dir = os.path.dirname(path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    where = ["c.status = 'PROCESSED'", "IS_DEFINED(c.classification)", "c.classification.needs_review = false"]
    if not include_unreviewed:
        where.append("(IS_DEFINED(c.reviewed) AND c.reviewed = true)")

    query = "SELECT c.id, c.markdown, c.classification, c.updated_at FROM c WHERE " + " AND ".join(where)
    it = cosmos_container.query_items(query)

    system_prompt = os.getenv(
        "FINETUNE_SYSTEM_PROMPT",
        "You classify insurance emails into intents and output strict JSON only.",
    )

    written = 0
    with open(path, "w", encoding="utf-8") as f:
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
                    anon = await anonymize_markdown_for_finetune(raw_markdown)
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
                ],
                "metadata": {
                    "example_id": item.get("id"),
                    "taxonomy_version": taxonomy_version,
                    "source": "human_review",
                    "updated_at": item.get("updated_at"),
                    "anonymized": bool(anonymize),
                    "anonymization": anonymization_meta,
                    "hash": hashlib.sha256((user_markdown + assistant_content).encode("utf-8")).hexdigest(),
                },
            }

            f.write(json.dumps(example, ensure_ascii=False) + "\n")
            written += 1

    return path


def _parse_args():
    import argparse

    parser = argparse.ArgumentParser(description="ClassificationG2S export helpers")
    parser.add_argument("--export-csv", nargs="?", const="./data/output.csv", help="Export Cosmos items to CSV")
    parser.add_argument(
        "--export-finetune-jsonl",
        nargs="?",
        const="./data/fine_tune.jsonl",
        help="Export reviewed examples to fine-tuning JSONL",
    )
    parser.add_argument(
        "--no-anonymize",
        action="store_true",
        help="Export fine-tuning JSONL without LLM anonymization (NOT recommended)",
    )
    parser.add_argument("--include-unreviewed", action="store_true", help="Include items without reviewed=true")
    parser.add_argument("--max-examples", type=int, default=None, help="Limit number of exported examples")
    parser.add_argument("--taxonomy-version", type=str, default="v1", help="Taxonomy version tag")
    return parser.parse_args()


async def _main_async() -> int:
    args = _parse_args()

    try:
        if args.export_csv:
            await export_cosmos_to_csv(args.export_csv)
            return 0

        if args.export_finetune_jsonl:
            await export_cosmos_to_finetune_jsonl(
                path=args.export_finetune_jsonl,
                anonymize=not args.no_anonymize,
                include_unreviewed=bool(args.include_unreviewed),
                max_examples=args.max_examples,
                taxonomy_version=args.taxonomy_version,
            )
            return 0

        raise SystemExit("No action specified. Use --export-csv or --export-finetune-jsonl")
    finally:
        await close_cosmos()


def main() -> int:
    import asyncio

    return asyncio.run(_main_async())


if __name__ == "__main__":
    raise SystemExit(main())
