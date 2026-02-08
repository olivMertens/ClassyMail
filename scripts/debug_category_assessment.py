
import asyncio
import os
import json
import httpx
from dotenv import load_dotenv

# Load environment variables
load_dotenv('secrets.env')

# Mock config and helpers locally to avoid importing the whole app stack
class Config:
    AI_API_VERSION = os.getenv("AI_API_VERSION", "2024-08-01-preview")
    # Using the exact configuration from secrets.env for gpt-5-nano if available, else hardcode
    PHI_ENDPOINT = os.getenv("PHI_ENDPOINT")
    PHI_DEPLOYMENT = "gpt-5-nano"

config = Config()

def build_chat_params(deployment, temperature=0.3, max_output_tokens=1500):
    # Simplified reasoning model logic
    is_reasoning = "gpt-5" in deployment.lower() or "o1" in deployment.lower()
    params = {}
    if is_reasoning:
        params["max_completion_tokens"] = max_output_tokens
    else:
        params["max_tokens"] = max_output_tokens
        params["temperature"] = temperature
    return params

async def get_token():
    # Attempt to get a token using az cli if possible, or use key if available
    # For now, let's assume Managed Identity or local AZ CLI login context
    # This is a bit complex to simulate fully without the app's auth helper,
    # but we can try using `az account get-access-token`
    proc = await asyncio.create_subprocess_shell(
        "az account get-access-token --resource https://cognitiveservices.azure.com/.default --query accessToken -o tsv",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    if stdout:
        return stdout.decode().strip()
    print(f"Error getting token: {stderr.decode()}")
    return None

async def test_assessment():
    print("--- Starting Category Assessment Test ---")

    token = await get_token()
    if not token:
        print("Failed to acquire auth token. Ensure you're logged in with 'az login'.")
        return

    endpoint = config.PHI_ENDPOINT
    deployment = config.PHI_DEPLOYMENT

    if not endpoint:
        print("Error: PHI_ENDPOINT not set in secrets.env")
        return

    url = f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/chat/completions?api-version={config.AI_API_VERSION}"
    print(f"Target URL: {url}")
    print(f"Model: {deployment}")

    system_prompt = """You are a classification taxonomy expert specialized in insurance and customer service categories, with deep expertise in LLM prompt engineering.
    (Truncated for brevity, but assume full prompt logic here...)
    RESPONSE FORMAT (JSON):
    {
      "quality_score": "Good|Needs Improvement|Poor",
      "advice": "...",
      "specific_suggestions": []
    }
    """

    user_content = """Assess this category definition:
    **Category Name:** Attestation habitation
    **Technical Slug:** ddedoc_habitation
    **Current DEFINITION:** Demande d'attestation habitation pour son logement résidentiel.
    **Current EXCLUSIONS:** Demande d'attestation habitation avec pour motif le télétravail.
    """

    # We use a larger max_token to test if that's the fix
    # Trying with 2000 first (current code uses 1500)
    MAX_TOKENS = 1500

    payload = {
        "model": deployment,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        **build_chat_params(deployment, temperature=0.3, max_output_tokens=MAX_TOKENS),
    }

    # For reasoning models, we strip response_format
    if "gpt-5" not in deployment:
         payload["response_format"] = {"type": "json_object"}

    print(f"Payload keys: {list(payload.keys())}")
    if "max_completion_tokens" in payload:
        print(f"Using max_completion_tokens: {payload['max_completion_tokens']}")
    if "max_tokens" in payload:
        print(f"Using max_tokens: {payload['max_tokens']}")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(timeout=60) as client:
        try:
            print("Sending request...")
            resp = await client.post(url, json=payload, headers=headers)
            print(f"Response Status: {resp.status_code}")

            try:
                data = resp.json()
                # print(json.dumps(data, indent=2))

                choices = data.get("choices", [])
                if choices:
                    choice = choices[0]
                    finish_reason = choice.get("finish_reason")
                    content = choice.get("message", {}).get("content")

                    print(f"Finish Reason: {finish_reason}")
                    print(f"Content Length: {len(content) if content else 0}")

                    if content:
                        print("--- Content Preview ---")
                        print(content[:200] + "...")
                        print("-----------------------")
                    else:
                        print("!!! CONTENT IS EMPTY !!!")
                else:
                    print("No choices returned.")

            except json.JSONDecodeError:
                print("Failed to decode JSON response.")
                print(resp.text)

        except Exception as e:
            print(f"Request failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_assessment())
