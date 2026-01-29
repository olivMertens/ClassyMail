# ruff: noqa: E402
import asyncio
import httpx
import logging
import os
import sys
from dotenv import load_dotenv

# Add project root to path
sys.path.append(os.getcwd())

# Load environment variables
load_dotenv('secrets.env')

from classificationg2s.services.azure_clients import Clients, auth_headers
from classificationg2s.core import config

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_test():
    # Only need MISTRAL for this test, but Clients() inits others.
    # If other vars are missing, Clients() might fail.
    # But usually Clients() connects lazily OR checks env.

    # Just in case Clients needs these to be non-None:
    if not os.getenv("AZURE_SERVICE_BUS_FQDN"):
        print("AZURE_SERVICE_BUS_FQDN not in secrets.env, faking it for clients init")
        config.SERVICE_BUS_FQDN = "fake.servicebus.windows.net"

    # Reload config because it reads at import time
    import importlib
    importlib.reload(config)

    c = Clients()
    # c.init() creates service bus client which validates FQDN format immediately
    await c.init()

    try:
        if not config.MISTRAL_ENDPOINT:
            print("MISTRAL_ENDPOINT not set")
            return

        headers = await auth_headers(c, model_type="mistral")
        url = f"{config.MISTRAL_ENDPOINT.rstrip('/')}/providers/mistral/azure/ocr"

        print(f"URL: {url}")

        pixel_b64 = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAMCAgMCAgMDAwMEAwMEBQgFBQQEBQoHBwYIDAoMDAsKCwsNDhIQDQ4RDgsLEBYQERMUFRUVDA8XGBYUGBIUFRT/2wBDAQMEBAUEBQkFBQkUDQsNFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBT/wAARCAABAAEGMgASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAf/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFAEBAAAAAAAAAAAAAAAAAAAAAP/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAMEARECEQA/AP/Z"

        # Test 1: Single string
        print("\n--- Test 1: Single String ---")
        payload_1 = {
            "model": config.MISTRAL_DEPLOYMENT,
            "document": {
                "type": "image_url",
                "image_url": pixel_b64
            },
            "include_image_base64": False
        }
        await call_ocr(url, payload_1, headers)

        # Test 2: List of strings
        print("\n--- Test 2: List of Strings ---")
        payload_2 = {
            "model": config.MISTRAL_DEPLOYMENT,
            "document": {
                "type": "image_url",
                "image_url": [pixel_b64, pixel_b64]
            },
            "include_image_base64": False
        }
        await call_ocr(url, payload_2, headers)

    finally:
        await c.close()

async def call_ocr(url, payload, headers):
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.post(url, json=payload, headers=headers)
            print(f"Status: {resp.status_code}")
            if resp.status_code != 200:
                print(f"Error: {resp.text}")
            else:
                print("Success")
        except Exception as e:
            print(f"Exception: {e}")

if __name__ == "__main__":
    asyncio.run(run_test())
