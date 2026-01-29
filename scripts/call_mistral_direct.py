import asyncio
import httpx
from classificationg2s.services.azure_clients import Clients, auth_headers
from classificationg2s.core import config

async def main():
    c = Clients()
    await c.init()
    try:
        headers = await auth_headers(c, model_type="mistral")
        url = f"{config.MISTRAL_ENDPOINT}/providers/mistral/azure/ocr"
        payload = {
            "model": config.MISTRAL_DEPLOYMENT,
            "document": {
                "type": "text",
                "text": "Test connection"
            }
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload, headers=headers)
            print(resp.status_code)
            print(resp.text)
            with open('tmp_mistral_direct.txt', 'w', encoding='utf-8') as f:
                f.write(f"{resp.status_code}\n{resp.text}")
    finally:
        await c.close()

asyncio.run(main())
