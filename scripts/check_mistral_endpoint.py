"""
Test different Mistral Document AI API endpoints to find the correct one.

This script tests various API patterns for Mistral Document AI in Azure AI Foundry.

Usage:
    uv run python scripts/check_mistral_endpoint.py
"""

import sys
import httpx
from pathlib import Path

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from classificationg2s.core import config


ENDPOINTS_TO_TEST = [
    # Standard OpenAI-compatible chat completions
    ("/chat/completions", "2024-05-01-preview"),
    ("/chat/completions", "2024-02-15-preview"),
    ("/chat/completions", "2023-12-01-preview"),

    # Mistral-specific endpoints (potential)
    ("/v1/chat/completions", None),
    ("/v1/completions", None),
    ("/openai/deployments/{deployment}/chat/completions", "2024-02-15-preview"),

    # Azure AI Inference API
    ("/models/{deployment}/chat/completions", "2024-05-01-preview"),
]


def test_endpoint(base_url, path, api_version, deployment_name, api_key):
    """Test a specific endpoint pattern."""
    # Replace {deployment} placeholder
    path = path.replace("{deployment}", deployment_name)

    # Build URL
    if api_version:
        url = f"{base_url.rstrip('/')}{path}?api-version={api_version}"
    else:
        url = f"{base_url.rstrip('/')}{path}"

    headers = {
        "api-key": api_key,
        "Content-Type": "application/json"
    }

    # Simple test payload for chat completions
    payload = {
        "messages": [
            {"role": "user", "content": "Test"}
        ],
        "max_tokens": 10
    }

    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=30.0)
        return {
            "url": url,
            "status": response.status_code,
            "success": response.status_code in [200, 201],
            "error": None if response.status_code in [200, 201] else response.text[:200]
        }
    except Exception as e:
        return {
            "url": url,
            "status": None,
            "success": False,
            "error": str(e)[:200]
        }


def main():
    print("=== Mistral Document AI Endpoint Tester ===\n")

    # Get config from environment
    base_url = config.MISTRAL_ENDPOINT
    deployment = config.MISTRAL_DEPLOYMENT
    api_key = config.AI_API_KEY  # Use AI_API_KEY from config

    if not all([base_url, deployment, api_key]):
        print("❌ Missing required environment variables:")
        print(f"  MISTRAL_ENDPOINT: {'✓' if base_url else '✗'}")
        print(f"  MISTRAL_DEPLOYMENT: {'✓' if deployment else '✗'}")
        print(f"  MISTRAL_API_KEY: {'✓' if api_key else '✗'}")
        return 1

    print(f"Base URL: {base_url}")
    print(f"Deployment: {deployment}")
    print(f"API Key: {'*' * 20}{api_key[-4:] if len(api_key) > 4 else '****'}\n")
    print("Testing endpoints...\n")

    results = []
    for path, api_version in ENDPOINTS_TO_TEST:
        result = test_endpoint(base_url, path, api_version, deployment, api_key)
        results.append(result)

        status_icon = "✅" if result["success"] else "❌"
        print(f"{status_icon} [{result['status'] or 'ERR'}] {result['url']}")
        if result["error"]:
            print(f"    Error: {result['error']}")
        print()

    # Summary
    print("\n=== SUMMARY ===")
    successful = [r for r in results if r["success"]]

    if successful:
        print(f"\n✅ Found {len(successful)} working endpoint(s):\n")
        for r in successful:
            print(f"  {r['url']}")
        print("\nUpdate your code to use one of these endpoints!")
    else:
        print("\n❌ No working endpoint found.")
        print("\nPossible solutions:")
        print("  1. Check if the deployment name is correct")
        print("  2. Verify API key is valid")
        print("  3. Check Azure AI Foundry documentation for Mistral Document AI")
        print("  4. Try using Azure AI Inference SDK instead of raw HTTP")

    return 0 if successful else 1


if __name__ == "__main__":
    sys.exit(main())
