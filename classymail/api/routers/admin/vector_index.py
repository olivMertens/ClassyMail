"""Admin vector index — rebuild Cosmos DB embeddings and chunks."""

from fastapi import APIRouter, Depends, HTTPException, status
from classymail.services.azure_clients import Clients, get_clients
from classymail.services.repository import save_chunks
from classymail.services.llm_pipeline import generate_embedding
from classymail.services.pipeline import chunk_markdown
import logging

router = APIRouter()
logger = logging.getLogger("ClassyMail.admin")


@router.post("/reindex-embeddings", status_code=status.HTTP_200_OK)
async def reindex_embeddings(
    clients: Clients = Depends(get_clients),
):
    """
    Rebuild the vector search index: delete all chunks, regenerate
    embeddings for every email, and recreate chunk documents.
    Does NOT re-run classification — only embeddings + chunking.
    """
    await clients.ensure_cosmos_container()
    container = clients.cosmos_container
    if not container:
        raise HTTPException(status_code=503, detail="Cosmos container not available")

    errors = []
    chunks_deleted = 0
    emails_reindexed = 0
    chunks_created = 0

    # Phase 1: Delete all existing chunks
    try:
        chunk_query = "SELECT c.id FROM c WHERE c.type = 'chunk'"
        chunk_ids = [x async for x in container.query_items(chunk_query)]
        for chunk_doc in chunk_ids:
            try:
                await container.delete_item(item=chunk_doc["id"], partition_key=chunk_doc["id"])
                chunks_deleted += 1
            except Exception as del_err:
                errors.append({"phase": "delete_chunk", "id": chunk_doc["id"], "error": str(del_err)})
        logger.info("Reindex: deleted %d chunks", chunks_deleted)
    except Exception as e:
        logger.error("Reindex: chunk deletion query failed: %s", e)
        errors.append({"phase": "delete_chunks_query", "error": str(e)})

    # Phase 2: Re-embed all emails
    try:
        email_query = (
            "SELECT c.id, c.markdown, c.subject, c.file_url FROM c "
            "WHERE IS_DEFINED(c.markdown) AND c.markdown != null "
            "AND (NOT IS_DEFINED(c.type) OR c.type != 'chunk')"
        )
        emails = [x async for x in container.query_items(email_query)]
        logger.info("Reindex: found %d emails to re-embed", len(emails))

        for i, email_doc in enumerate(emails):
            email_id = email_doc["id"]
            markdown = email_doc.get("markdown", "")
            subject = email_doc.get("subject")
            file_url = email_doc.get("file_url")
            try:
                vector = await generate_embedding(markdown, clients=clients)

                full_doc = await container.read_item(item=email_id, partition_key=email_id)
                full_doc["vector"] = vector
                await container.upsert_item(full_doc)

                chunks = chunk_markdown(markdown)
                chunk_docs = []
                for ch in chunks:
                    ch_vec = []
                    try:
                        ch_vec = await generate_embedding(ch["content"], clients=clients)
                    except Exception:
                        pass
                    chunk_docs.append({"index": ch["index"], "content": ch["content"], "vector": ch_vec})

                await save_chunks(email_id, chunk_docs, subject=subject, file_url=file_url, clients=clients)
                chunks_created += len(chunk_docs)
                emails_reindexed += 1

                if (i + 1) % 10 == 0:
                    logger.info("Reindex progress: %d/%d emails", i + 1, len(emails))
            except Exception as emb_err:
                logger.error("Reindex: failed for email %s: %s", email_id, emb_err)
                errors.append({"phase": "embed_email", "id": email_id, "error": str(emb_err)})
    except Exception as e:
        logger.error("Reindex: email query failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Reindex failed: {str(e)}")

    logger.info("Reindex complete: %d emails, %d chunks deleted, %d chunks created, %d errors",
                emails_reindexed, chunks_deleted, chunks_created, len(errors))

    return {
        "status": "success" if not errors else "partial",
        "emails_reindexed": emails_reindexed,
        "chunks_deleted": chunks_deleted,
        "chunks_created": chunks_created,
        "errors": errors[:20],
    }
