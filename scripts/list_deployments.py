"""List all OpenAI deployments on the Foundry endpoint."""

import asyncio
import httpx
from dotenv import load_dotenv

load_dotenv("secrets.env")

from classymail.services.azure_clients import Clients, auth_headers  # noqa: E402


async def main() -> None:
    clients = Clients()
    headers = await auth_headers(clients, model_type="openai")
    ep = "https://email-poc-aifoundry.cognitiveservices.azure.com"

    url = f"{ep}/openai/deployments?api-version=2024-08-01-preview"
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(url, headers=headers)

    print(f"Status: {r.status_code}")
    if r.is_success:
        data = r.json()
        deployments = data.get("data", [])
        print(f"Found {len(deployments)} deployment(s):\n")
        for d in deployments:
            dep_id = d.get("id", "?")
            model = d.get("model", "?")
            status = d.get("status", "?")
            print(f"  {dep_id:30s}  model={model:25s}  status={status}")
    else:
        print(f"Error: {r.text[:500]}")


if __name__ == "__main__":
    asyncio.run(main())
