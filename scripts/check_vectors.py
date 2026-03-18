"""Quick check: verify email vectors and test semantic search in Cosmos DB."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "secrets.env"))
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

from azure.cosmos.aio import CosmosClient  # noqa: E402
from azure.identity.aio import DefaultAzureCredential  # noqa: E402


async def main():
    endpoint = os.getenv("AZURE_COSMOS_ENDPOINT")
    if not endpoint:
        print("ERROR: AZURE_COSMOS_ENDPOINT not set")
        return

    cred = DefaultAzureCredential()
    client = CosmosClient(endpoint, credential=cred)
    db = client.get_database_client("emailsdb")
    emails = db.get_container_client("emails")

    print("=" * 60)
    print("1. EMAIL VECTORS")
    print("=" * 60)
    q = "SELECT c.id, c.subject, ARRAY_LENGTH(c.vector) as vec_len, c.status, c.type FROM c OFFSET 0 LIMIT 15"
    count_with = 0
    count_without = 0
    async for item in emails.query_items(q):
        vec = item.get("vec_len", 0) or 0
        subj = (item.get("subject") or "-")[:50]
        status = item.get("status", "?")
        marker = "OK" if vec > 0 else "EMPTY"
        doc_type = item.get("type", "<none>")
        print(f"  [{marker:5s}] vec={vec:>5} | type={doc_type:15s} | {status:18s} | {subj}")
        if vec > 0:
            count_with += 1
        else:
            count_without += 1
    print(f"\n  Summary: {count_with} with vectors, {count_without} without vectors")

    print("\n" + "=" * 60)
    print("2. CHUNKS")
    print("=" * 60)
    async for v in emails.query_items("SELECT VALUE COUNT(1) FROM c WHERE c.type = 'chunk'"):
        print(f"  Total chunks: {v}")
    async for v in emails.query_items("SELECT VALUE COUNT(1) FROM c WHERE c.type = 'chunk' AND IS_DEFINED(c.vector) AND ARRAY_LENGTH(c.vector) > 0"):
        print(f"  Chunks with vectors: {v}")

    print("\n" + "=" * 60)
    print("3. SEMANTIC SEARCH TEST")
    print("=" * 60)
    import httpx
    from azure.identity.aio import DefaultAzureCredential as DAC2

    ai_endpoint = os.getenv("PHI_ENDPOINT") or os.getenv("AZURE_AI_ENDPOINT")
    emb_deployment = os.getenv("EMBEDDING_DEPLOYMENT", "text-embedding-3-small")
    if not ai_endpoint:
        print("  SKIP: No PHI_ENDPOINT set")
    else:
        cred2 = DAC2()
        token = await cred2.get_token("https://cognitiveservices.azure.com/.default")
        url = f"{ai_endpoint.rstrip('/')}/openai/deployments/{emb_deployment}/embeddings?api-version=2024-08-01-preview"
        headers = {"Authorization": f"Bearer {token.token}", "Content-Type": "application/json"}

        test_query = "urgent"
        print(f"  Generating embedding for: '{test_query}'")
        async with httpx.AsyncClient(timeout=30) as hc:
            resp = await hc.post(url, json={"input": test_query, "model": emb_deployment}, headers=headers)
            resp.raise_for_status()
            vector = resp.json()["data"][0]["embedding"]
        print(f"  Embedding dims: {len(vector)}")

        search_q = (
            "SELECT TOP 5 c.id, c.subject, c.sender, "
            "VectorDistance(c.vector, @vector) as distance "
            "FROM c "
            "WHERE c.type = 'email' AND IS_DEFINED(c.vector) AND ARRAY_LENGTH(c.vector) > 0 "
            "ORDER BY VectorDistance(c.vector, @vector) ASC"
        )
        params = [{"name": "@vector", "value": vector}]
        print(f"\n  Email vector search for '{test_query}':")
        found = 0
        async for item in emails.query_items(search_q, parameters=params):
            subj = (item.get("subject") or "-")[:50]
            dist = item.get("distance", 0)
            print(f"    dist={dist:.4f} | {subj} | {item.get('sender', '?')}")
            found += 1
        if found == 0:
            print("    NO EMAIL RESULTS — email vectors may be empty")

        chunk_q = (
            "SELECT TOP 5 c.parent_id, c.subject, c.chunk_index, "
            "VectorDistance(c.vector, @vector) as distance "
            "FROM c "
            "WHERE c.type = 'chunk' AND IS_DEFINED(c.vector) AND ARRAY_LENGTH(c.vector) > 0 "
            "ORDER BY VectorDistance(c.vector, @vector) ASC"
        )
        print(f"\n  Chunk vector search for '{test_query}':")
        found_chunks = 0
        async for item in emails.query_items(chunk_q, parameters=params):
            subj = (item.get("subject") or "-")[:50]
            dist = item.get("distance", 0)
            print(f"    dist={dist:.4f} | chunk#{item.get('chunk_index',0)} | {subj}")
            found_chunks += 1
        if found_chunks == 0:
            print("    NO CHUNK RESULTS")

        await cred2.close()

    # 4. Text search test (case-insensitive)
    print("\n" + "=" * 60)
    print("4. TEXT SEARCH TEST (case-insensitive)")
    print("=" * 60)
    text_q = (
        "SELECT c.id, c.subject, c.sender FROM c "
        "WHERE IS_DEFINED(c.search_text) AND CONTAINS(LOWER(c.search_text), 'urgent') "
        "AND (NOT IS_DEFINED(c.type) OR c.type != 'chunk') "
        "OFFSET 0 LIMIT 5"
    )
    found_text = 0
    async for item in emails.query_items(text_q):
        subj = (item.get("subject") or "-")[:50]
        sender = item.get("sender") or "?"
        print(f"    {subj} | {sender}")
        found_text += 1
    if found_text == 0:
        print("    NO RESULTS — text search returned nothing")
    else:
        print(f"    Found {found_text} emails containing 'urgent'")

    await client.close()
    await cred.close()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
