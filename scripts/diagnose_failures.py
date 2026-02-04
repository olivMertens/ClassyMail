import asyncio
from collections import Counter
from dotenv import load_dotenv

# Load env
load_dotenv("secrets.env")

# Re-use project modules
try:
    from classificationg2s.services.azure_clients import Clients
except ImportError:
    # Allow running from root context where package might not be installed but is in path
    import sys
    sys.path.append(".")
    from classificationg2s.services.azure_clients import Clients


async def main():
    print("Initializing Clients...")
    clients = Clients()
    await clients.init()

    try:
        container = await clients.ensure_cosmos_container()
        if not clients.cosmos_container:
            print("Failed to access Cosmos DB.")
            return
        # Use the container from clients if the helper returned None for simple variable assignment
        container = clients.cosmos_container

        print("Querying failed items (status='ERROR')...")

        # Select error fields
        query = "SELECT c.id, c.error, c.error_stage, c.file_url FROM c WHERE c.status = 'ERROR'"

        items = [i async for i in container.query_items(query)]

        print(f"\nFound {len(items)} items in ERROR state.\n")

        error_counts = Counter()
        detailed_errors = []

        for item in items:
            err_msg = item.get("error", "Unknown Error")
            # Simplify error for grouping
            if "ReadTimeout" in err_msg:
                category = "Timeout (LLM/Network took too long)"
            elif "handler has already been shutdown" in err_msg:
                category = "Worker Restart (Deployment Interruption)"
            elif "503" in err_msg or "502" in err_msg:
                category = "Service Unavailable (502/503)"
            elif "429" in err_msg:
                category = "Rate Limited (429)"
            elif "404" in err_msg:
                category = "Model/Resource Not Found"
            elif "corrupted" in err_msg.lower():
                category = "Corrupted PDF"
            else:
                category = f"Other: {err_msg[:50]}..."

            error_counts[category] += 1
            detailed_errors.append(f"[{category}] {item.get('id')} -> {err_msg[:100]}")

        print("--- Error Distribution ---")
        for cat, count in error_counts.most_common():
            print(f"{count: <5} | {cat}")

        print("\n--- Diagnostic Conclusion ---")
        if error_counts["Service Unavailable (502/503)"] > 0:
            print("⚠️  CONFIRMED: Some errors were due to Service Unavailable (AI Model down).")
        elif error_counts["Rate Limited (429)"] > 0:
            print("⚠️  CONFIRMED: Some errors were due to Rate Limiting.")
        else:
            print("✅  NO evidence of AI Service Unavailability (503) or Rate Limiting (429).")
            print("    The errors appear to be client-side Timeouts or Worker Restarts.")

    except Exception as e:
        print(f"Script Error: {e}")
    finally:
        await clients.close()

if __name__ == "__main__":
    asyncio.run(main())
