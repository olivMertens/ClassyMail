"""Quick smoke-test for Kimi-K2.5 deployment on the tenant."""

import asyncio
from dotenv import load_dotenv

load_dotenv("secrets.env")

from classymail.core import config  # noqa: E402
from classymail.core.llm_compat import build_chat_params, extract_message_content, is_reasoning_model  # noqa: E402
from classymail.services.azure_clients import Clients, auth_headers  # noqa: E402
from classymail.services.llm_pipeline import resolve_model_config  # noqa: E402


async def main() -> None:
    endpoint, deployment, api_version = resolve_model_config("Kimi-K2.5")
    reasoning = is_reasoning_model(deployment)

    print("=" * 60)
    print("  Kimi-K2.5 Smoke Test")
    print("=" * 60)
    print(f"  Endpoint:   {endpoint}")
    print(f"  Deployment: {deployment}")
    print(f"  Reasoning:  {reasoning}")
    print(f"  API Ver:    {api_version}")

    clients = Clients()
    headers = await auth_headers(clients, model_type="openai")
    auth_type = "Bearer Token" if "Bearer" in str(headers.get("Authorization", "")) else "API Key"
    print(f"  Auth:       {auth_type}")

    # Try the resolved api-version first, then fall back to config default
    api_versions = [api_version, config.AI_API_VERSION]
    seen: set[str] = set()

    import httpx

    for api_ver in api_versions:
        if api_ver in seen:
            continue
        seen.add(api_ver)

        url = (
            f"{endpoint.rstrip('/')}/openai/deployments/{deployment}"
            f"/chat/completions?api-version={api_ver}"
        )
        print(f"\n  --- Trying api-version={api_ver} ---")
        print(f"  URL:        {url}")

        payload = {
            "messages": [{"role": "user", "content": "Say hello in French, one sentence only."}],
            **build_chat_params(deployment, temperature=0.0, max_output_tokens=50),
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload, headers=headers)

        print(f"  HTTP Status: {resp.status_code}")

        if resp.is_error:
            print(f"  ERROR: {resp.text[:800]}")
            try:
                err = resp.json()
                msg = err.get("error", {}).get("message", "")
                code = err.get("error", {}).get("code", "")
                print(f"  Code:    {code}")
                print(f"  Message: {msg}")
            except Exception:
                pass
            print("  ❌ Failed with this api-version, trying next...")
        else:
            data = resp.json()
            choice = data["choices"][0]
            msg = choice.get("message", {})
            print(f"  Message keys: {list(msg.keys())}")
            content = extract_message_content(msg)
            print(f"  Content:   {repr(content)[:200]}")
            usage = data.get("usage", {})
            print(f"  Usage:     in={usage.get('prompt_tokens', '?')} out={usage.get('completion_tokens', '?')}")
            print(f"  Model:     {data.get('model', '?')}")
            print("\n  ✅ Kimi-K2.5 is working!")
            return

    print("\n  ❌ Kimi-K2.5 deployment not found. Deploy it in Azure AI Foundry first.")
    print("     Go to: https://ai.azure.com → your project → Model Catalog → search 'Kimi-K2.5' → Deploy")


if __name__ == "__main__":
    asyncio.run(main())
