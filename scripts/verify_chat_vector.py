import asyncio
import os
import logging
from dotenv import load_dotenv

# Set explicit path to secrets.env
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env_path = os.path.join(base_dir, "secrets.env")
print(f"Loading env from: {env_path}")
load_dotenv(env_path)

from classificationg2s.services.llm_pipeline import generate_embedding  # noqa: E402
from classificationg2s.services.azure_clients import Clients, set_default_clients  # noqa: E402
from classificationg2s.core import config  # noqa: E402

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("verify_chat_vector")

async def verify_embedding():
    print("\n--- Verifying Embedding Generation ---")

    # DEBUG: Check config
    print(f"COSMOS_ENDPOINT: {config.COSMOS_ENDPOINT}")
    print(f"COSMOS_KEY present: {bool(config.COSMOS_KEY)}")
    if not config.COSMOS_KEY:
        print("Using RBAC (credential)")
    else:
        print("Using Key auth")

    if not config.EMBEDDING_ENDPOINT:
        print("❌ EMBEDDING_ENDPOINT is not set in environment.")
        return False

    print(f"Endpoint: {config.EMBEDDING_ENDPOINT}")
    print(f"Deployment: {config.EMBEDDING_DEPLOYMENT}")

    clients = Clients()

    # DEBUG: Check credential type in Clients
    print(f"Clients credential type: {type(clients.credential)}")

    try:
        await clients.init()
    except Exception as e:
        print(f"❌ Clients init failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    set_default_clients(clients)

    try:
        vector = await generate_embedding("This is a test sentence for embedding verification.", clients=clients)
        if vector and len(vector) > 0:
            print(f"✅ Embedding generated successfully! Dimensions: {len(vector)}")
            # print(f"Sample: {vector[:5]}...")
            return True
        else:
            print("❌ Embedding generation returned empty list/None.")
            return False
    except Exception as e:
        print(f"❌ Embedding validation failed: {e}")
        return False
    finally:
        await clients.close()


async def verify_chat_endpoint():
    print("\n--- Verifying Chat Endpoint Integration ---")

    # We call the FastAPI endpoint locally
    # Assumes the API is running or we simulate the client call.
    # Since we can't depend on uvicorn running in this script, we will simulate the ChatAgent run directly.

    from classificationg2s.services.chat_agent import agent

    clients = Clients()
    try:
        await clients.init()
    except Exception:
         print("Skipping chat verification due to init failure")
         return

    query = "Find emails about car accidents or damage"
    messages = [{"role": "user", "content": query}]

    print(f"Query: '{query}'")

    try:
        # We need to ensure we use the "search_similar_emails" tool.
        # But ChatAgent logic depends on how it is implemented.
        response = await agent.run(messages, clients=clients)
        content = response.get("content", "")
        print("\n--- Chatbot Response ---")
        print(content)

        if len(content) > 10:
            print("\n✅ Chatbot responded with content.")
        else:
             print("\n⚠️ Chatbot response looks empty or too short.")

    except Exception as e:
        print(f"\n❌ Chatbot execution error: {e}")
    finally:
        await clients.close()

async def main():
    success_embed = await verify_embedding()
    if success_embed:
        await verify_chat_endpoint()

if __name__ == "__main__":
    asyncio.run(main())
