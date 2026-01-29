import asyncio
import logging
import os
import argparse
import base64
from classificationg2s.services.azure_clients import Clients, set_default_clients, build_sas_url, auth_headers
from classificationg2s.services.llm_pipeline import ocr_with_mistral, classify_with_phi4
from classificationg2s.core import config
from dotenv import load_dotenv

# Configure logging to see all steps
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def run_diagnostics(pdf_path: str = None, blob_url: str = None):
    print("--- 1. Initialize Clients ---")
    clients = Clients()
    set_default_clients(clients)

    try:
        await clients.init()
        print("✅ Clients initialized.")

        print("\n--- 2. Environment Config Check ---")
        print(f"MISTRAL_ENDPOINT: {config.MISTRAL_ENDPOINT}")
        print(f"PHI_ENDPOINT: {config.PHI_ENDPOINT}")
        print(f"EMBEDDING_ENDPOINT: {config.EMBEDDING_ENDPOINT}")
        print(f"STORAGE_ACCOUNT_URL: {config.BLOB_ACCOUNT_URL}")

        pdf_b64 = None

        if blob_url:
            print("\n--- 3. Testing Blob URL Access & SAS Generation ---")
            print(f"Target Blob: {blob_url}")

            # 3.1 Test SAS Generation
            sas_url = await build_sas_url(blob_url, clients=clients)
            print(f"Generated SAS URL: {sas_url}")

            if not sas_url or sas_url == blob_url:
                print("⚠️  Warning: SAS URL is identical to input or empty. User Delegation SAS might have failed if no account key is present.")
            else:
                 print("✅ SAS URL generated (assumed valid format).")

        if pdf_path:
            print(f"\n--- 4. Reading Local PDF: {pdf_path} ---")
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()
                pdf_b64 = base64.b64encode(pdf_bytes).decode('utf-8')
            print(f"✅ PDF loaded. Size: {len(pdf_bytes)} bytes")

            print("\n--- 5. Testing CLI OCR (Mistral) ---")

            # Helper to try paths
            import httpx
            import json

            async def try_path(suffix, test_payload):
                try:
                    t_url = config.MISTRAL_ENDPOINT.rstrip('/') + suffix
                    print(f"Testing URL: {t_url}")

                    api_key = os.environ.get("AZURE_AI_KEY")
                    if api_key:
                        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
                    else:
                        headers = await auth_headers(clients)

                    async with httpx.AsyncClient(timeout=10) as client:
                        resp = await client.post(t_url, json=test_payload, headers=headers)
                        print(f"Status: {resp.status_code}")
                        if resp.status_code < 300:
                            print(f"✅ Success on {suffix}!")
                            print(f"Response: {resp.text[:200]}...")
                            return True
                        else:
                            print(f"Response: {resp.text[:200]}")
                            return False
                except Exception as e:
                    print(f"Error: {e}")
                return False

            paths_to_test = [
                "/providers/mistral/azure/ocr",
                "/v1/ocr",
                "/ocr"
            ]

            payloads_to_test = [
                {
                    "model": config.MISTRAL_DEPLOYMENT,
                    "document": {
                        "type": "image_url",
                        "image_url": f"data:application/pdf;base64,{pdf_b64}"
                    },
                    "include_image_base64": True
                },
                {
                    "model": config.MISTRAL_DEPLOYMENT,
                    "document": {
                        "type": "image_url",
                        "image_url": "https://mw1.google.com/mw-earth-vectordb/kml-samples/gp/seattle/gigapxl/google-earth-touchup.jpg"
                    }
                }
            ]

            success = False
            for p in paths_to_test:
                 for pl in payloads_to_test:
                     print(f"\n--- Testing Path: {p} with payload type: {pl['document']['type']} ---")
                     if await try_path(p, pl):
                         success = True
                         # We don't break yet, let's see which ones work

            if not success:
                print("\n❌ All paths/payloads failed. Checking control plane...")

            # Original call if one succeeded or just to show trace
            try:
                print("\n--- 5.1 Final attempt with library code ---")
                ocr_result = await ocr_with_mistral(pdf_b64, clients=clients)
                print("✅ OCR Success!")
                markdown_text = ocr_result.get("markdown", "")
                print(f"Markdown length: {len(markdown_text)} chars")
                print(f"Pages processed: {ocr_result.get('usage', {}).get('pages_processed')}")

                print("\n--- 6. Testing Classification (Phi-4) ---")
                classification = await classify_with_phi4(markdown_text, clients=clients)
                import json
                print("✅ Classification Success!")
                print(json.dumps(classification, indent=2))

            except Exception as e:
                print(f"❌ Error during pipeline execution: {e}")
                import traceback
                traceback.print_exc()

    except Exception as ex:
        print(f"❌ Global Error: {ex}")
    finally:
        await clients.close()
        print("\n--- Diagnostic Complete ---")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Diagnostics for PDF processing pipeline")
    parser.add_argument("--pdf", help="Path to local PDF file to test OCR/Classification")
    parser.add_argument("--blob", help="Blob URL to test valid SAS generation")

    args = parser.parse_args()

    # Load env vars from .env if present
    load_dotenv()

    asyncio.run(run_diagnostics(pdf_path=args.pdf, blob_url=args.blob))
