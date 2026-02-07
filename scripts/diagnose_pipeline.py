import asyncio
import logging
import argparse
import base64
import json
from classymail.services.azure_clients import Clients, set_default_clients
from classymail.services.llm_pipeline import ocr_with_mistral, classify_with_phi4
from classymail.core import config
from classymail.cli import ensure_cosmos_container, cosmos_container, close_cosmos
from dotenv import load_dotenv

# Configure logging to see all steps
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def show_error_records(limit: int = 5, include_processing_log: bool = True):
    """Query and display recent ERROR records from Cosmos DB."""
    print("\n=== ERROR RECORDS FROM COSMOS DB ===\n")

    await ensure_cosmos_container()
    query = "SELECT * FROM c WHERE c.status = 'ERROR' ORDER BY c.updated_at DESC"
    items = []
    it = cosmos_container.query_items(query)
    async for item in it:
        items.append(item)
        if len(items) >= limit:
            break

    if not items:
        print("✅ No ERROR records found.")
        await close_cosmos()
        return

    for idx, item in enumerate(items, 1):
        print(f"[{idx}] id={item.get('id')} status={item.get('status')} error_stage={item.get('error_stage')}")
        print(f"error: {item.get('error')}")
        if include_processing_log:
            plog = item.get('processing_log')
            if plog:
                print("processing_log:")
                for entry in plog:
                    print(json.dumps(entry, ensure_ascii=False, indent=2))
            else:
                print("processing_log: <none>")
        print("-" * 80)

    await close_cosmos()
    print(f"\n=== Total ERROR records shown: {len(items)} ===\n")


async def run_diagnostics(pdf_path: str = None):
    """Run pipeline diagnostics with OCR and classification testing."""
    print("--- 1. Initialize Clients ---")
    clients = Clients()
    set_default_clients(clients)

    try:
        await clients.init()
        print("✅ Clients initialized.")

        print("\n--- 2. Environment Config Check ---")
        print(f"MISTRAL_ENDPOINT: {config.MISTRAL_ENDPOINT}")
        print(f"PHI_ENDPOINT: {config.PHI_ENDPOINT}")
        print(f"CHAT_DEPLOYMENT: {config.CHAT_DEPLOYMENT}")
        print(f"EMBEDDING_DEPLOYMENT: {config.EMBEDDING_DEPLOYMENT}")
        print(f"STORAGE_ACCOUNT_URL: {config.BLOB_ACCOUNT_URL}")

        if not pdf_path:
            print("\n⚠️  No PDF provided. Use --pdf to test OCR/Classification pipeline.")
            return

        print(f"\n--- 3. Reading Local PDF: {pdf_path} ---")
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
            pdf_b64 = base64.b64encode(pdf_bytes).decode('utf-8')
        print(f"✅ PDF loaded. Size: {len(pdf_bytes)} bytes")

        print("\n--- 4. Testing OCR (Mistral) ---")
        try:
            ocr_result = await ocr_with_mistral(pdf_b64, clients=clients)
            print("✅ OCR Success!")
            markdown_text = ocr_result.get("markdown", "")
            print(f"Markdown length: {len(markdown_text)} chars")
            print(f"Pages processed: {ocr_result.get('usage', {}).get('pages_processed')}")

            print("\n--- 5. Testing Classification (Phi-4) ---")
            classification = await classify_with_phi4(markdown_text, clients=clients)
            print("✅ Classification Success!")
            print(json.dumps(classification, indent=2))

        except Exception as e:
            print(f"❌ Error during pipeline execution: {e}")
            import traceback
            traceback.print_exc()

    except Exception as ex:
        print(f"❌ Global Error: {ex}")
        import traceback
        traceback.print_exc()
    finally:
        await clients.close()
        print("\n--- Diagnostic Complete ---")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Diagnostics for PDF processing pipeline and Cosmos DB errors",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test OCR/Classification pipeline with local PDF
  python scripts/diagnose_pipeline.py --pdf dataset/pdf/test.pdf

  # Show recent ERROR records from Cosmos DB
  python scripts/diagnose_pipeline.py --show-errors

  # Show 10 ERROR records without processing logs
  python scripts/diagnose_pipeline.py --show-errors --limit 10 --no-log
"""
    )
    parser.add_argument("--pdf", help="Path to local PDF file to test OCR/Classification")
    parser.add_argument("--show-errors", action="store_true", help="Query and display recent ERROR records from Cosmos DB")
    parser.add_argument("--limit", type=int, default=5, help="Number of ERROR records to show (default: 5)")
    parser.add_argument("--no-log", action="store_true", help="Do not show processing_log in error records")

    args = parser.parse_args()

    # Load env vars from .env if present
    load_dotenv("secrets.env")

    if args.show_errors:
        asyncio.run(show_error_records(limit=args.limit, include_processing_log=not args.no_log))
    else:
        asyncio.run(run_diagnostics(pdf_path=args.pdf))
