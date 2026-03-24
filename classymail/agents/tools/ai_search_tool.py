"""Per-intent Azure AI Search retrieval tool.

Each intent/category has its own search index ``classymail-intent-{slug}``
with semantic ranking and human-reinforced label fields.

Falls back gracefully when AI Search is not configured (Phase 1: prompt-only).
"""

from __future__ import annotations

import logging
from typing import Optional

from opentelemetry import trace

from classymail.agents.config import SEARCH_ENDPOINT
from classymail.agents.models import RAGGroundingRef
from classymail.services.azure_clients import Clients

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


def _index_name(slug: str) -> str:
    """Build the AI Search index name for a given category slug."""
    return f"classymail-intent-{slug}"


async def search_intent_index(
    query_text: str,
    slug: str,
    *,
    retrieval_mode: str = "semantic",
    top_k: int = 5,
    clients: Clients | None = None,
    query_vector: Optional[list[float]] = None,
) -> list[RAGGroundingRef]:
    """Search the per-intent AI Search index.

    Returns a list of ``RAGGroundingRef`` items from the index, or an empty
    list if AI Search is not configured (Phase 1 / prompt-only mode).

    Args:
        query_text: The email content to search for.
        slug: Category slug (maps to index name).
        retrieval_mode: ``vector`` | ``hybrid`` | ``semantic``.
        top_k: Maximum number of results.
        clients: Azure clients for credential.
        query_vector: Pre-computed embedding vector (1536d).  If *None* and
            retrieval_mode requires a vector, the function generates one.
    """
    if not SEARCH_ENDPOINT:
        return []  # AI Search not configured — Phase 1 prompt-only

    index = _index_name(slug)

    with tracer.start_as_current_span(f"agentic.search.{slug}") as span:
        span.set_attribute("agentic.search_index", index)
        span.set_attribute("agentic.retrieval_mode", retrieval_mode)

        try:
            # Lazy-import to avoid hard dependency when AI Search is not used
            from azure.search.documents.aio import SearchClient
            from azure.search.documents.models import VectorizedQuery

            credential = clients.credential if clients else None
            if not credential:
                from azure.identity.aio import DefaultAzureCredential
                credential = DefaultAzureCredential()

            search_client = SearchClient(
                endpoint=SEARCH_ENDPOINT,
                index_name=index,
                credential=credential,
            )

            # Build vector query if needed
            vector_queries = None
            if retrieval_mode in ("vector", "hybrid", "semantic") and query_vector:
                vector_queries = [
                    VectorizedQuery(
                        vector=query_vector,
                        k_nearest_neighbors=top_k,
                        fields="content_vector",
                    )
                ]
            elif retrieval_mode in ("vector", "hybrid", "semantic") and not query_vector:
                # Generate embedding on the fly
                from classymail.services.llm_pipeline import generate_embedding
                try:
                    vec = await generate_embedding(query_text[:2000], clients=clients)
                    if vec:
                        vector_queries = [
                            VectorizedQuery(
                                vector=vec,
                                k_nearest_neighbors=top_k,
                                fields="content_vector",
                            )
                        ]
                except Exception as e:
                    logger.warning("AI Search: embedding generation failed for %s: %s", slug, e)

            search_text = query_text[:500] if retrieval_mode in ("hybrid", "semantic") else None
            query_type = "semantic" if retrieval_mode == "semantic" else None
            semantic_config = "default-semantic" if retrieval_mode == "semantic" else None

            async with search_client:
                results = await search_client.search(
                    search_text=search_text,
                    vector_queries=vector_queries,
                    query_type=query_type,
                    semantic_configuration_name=semantic_config,
                    top=top_k,
                    select=["id", "content", "label", "label_source", "human_verified", "is_positive", "correction_reason"],
                )

                refs: list[RAGGroundingRef] = []
                async for result in results:
                    full_content = result.get("content", "")
                    snippet = full_content[:300] + "..." if len(full_content) > 300 else full_content
                    refs.append(RAGGroundingRef(
                        doc_id=result.get("id", ""),
                        score=result.get("@search.score", 0.0),
                        label=result.get("label", slug),
                        source=result.get("label_source", "llm_classified"),
                        content_snippet=snippet,
                        is_positive=result.get("is_positive", True),
                        correction_reason=result.get("correction_reason"),
                    ))

            span.set_attribute("agentic.rag_hits", len(refs))
            logger.info("[agentic] AI Search %s: %d hits (mode=%s)", index, len(refs), retrieval_mode)
            return refs

        except ImportError:
            logger.info("azure-search-documents not installed — AI Search disabled")
            return []
        except Exception as e:
            logger.warning("AI Search query failed for %s: %s", index, e)
            span.set_attribute("agentic.search_error", str(e))
            return []
