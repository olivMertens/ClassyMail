#!/usr/bin/env python3
"""
Test the real Mistral Document AI endpoint with a sample PDF.

This script tests the actual Microsoft Foundry endpoint used in production.

Usage:
    uv run python scripts/check_mistral_endpoint.py
"""

import sys
import base64
import httpx
from pathlib import Path
from io import BytesIO

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from classificationg2s.core import config


def create_test_pdf():
    """Create a minimal test PDF."""
    try:
        from fpdf import FPDF
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        pdf.cell(200, 10, txt="Test OCR Document", ln=True, align="C")
        pdf.cell(200, 10, txt="This is a test email for insurance classification.", ln=True)
        pdf.cell(200, 10, txt="Subject: Demande d'attestation d'assurance", ln=True)
        buffer = BytesIO()
        pdf.output(buffer)
        return buffer.getvalue()
    except ImportError:
        print("Warning: fpdf2 not installed, using minimal PDF")
        # Minimal valid PDF (empty page)
        return b"%PDF-1.4\\n1 0 obj\\n<< /Type /Catalog /Pages 2 0 R >>\\nendobj\\n2 0 obj\\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\\nendobj\\n3 0 obj\\n<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> /MediaBox [0 0 612 792] /Contents 5 0 R >>\\nendobj\\n4 0 obj\\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\\nendobj\\n5 0 obj\\n<< /Length 44 >>\\nstream\\nBT\\n/F1 12 Tf\\n100 700 Td\\n(Test Document) Tj\\nET\\nendstream\\nendobj\\nxref\\n0 6\\n0000000000 65535 f\\n0000000009 00000 n\\n0000000058 00000 n\\n0000000115 00000 n\\n0000000261 00000 n\\n0000000338 00000 n\\ntrailer\\n<< /Size 6 /Root 1 0 R >>\\nstartxref\\n430\\n%%EOF"


def test_mistral_endpoint():
    """Test the Mistral Document AI endpoint with a real document."""
    print("=== Mistral Document AI Endpoint Test ===")
    print()

    # Get config from environment
    base_url = config.MISTRAL_ENDPOINT
    deployment = config.MISTRAL_DEPLOYMENT
    api_key = config.AI_API_KEY

    if not all([base_url, deployment]):
        print("❌ Missing required environment variables:")
        print(f"  MISTRAL_ENDPOINT: {'✓' if base_url else '✗'}")
        print(f"  MISTRAL_DEPLOYMENT: {'✓' if deployment else '✗'}")
        return 1

    print(f"Endpoint: {base_url}")
    print(f"Deployment: {deployment}")
    print(f"API Key: {'✓ (via Entra ID)' if not api_key else '*' * 20 + api_key[-4:]}")
    print()

    # Create test PDF
    print("Creating test PDF...")
    pdf_bytes = create_test_pdf()
    base64_pdf = base64.b64encode(pdf_bytes).decode("utf-8")
    print(f"✓ PDF created ({len(pdf_bytes)} bytes)")
    print()

    # Prepare request
    url = base_url.rstrip('/')
    payload = {
        "model": deployment,
        "document": {
            "type": "document_url",
            "document_url": f"data:application/pdf;base64,{base64_pdf}"
        }
    }

    headers = {
        "Content-Type": "application/json"
    }

    if api_key:
        headers["api-key"] = api_key
    else:
        # Use Azure CLI token
        from azure.identity import AzureCliCredential
        try:
            credential = AzureCliCredential()
            token = credential.get_token("https://cognitiveservices.azure.com/.default")
            headers["Authorization"] = f"Bearer {token.token}"
        except Exception as e:
            print(f"❌ Failed to get Azure CLI token: {e}")
            return 1

    print(f"Testing endpoint: {url}")
    print("Sending OCR request...")
    print()

    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=90.0)

        print(f"Status: {response.status_code}")
        print()

        if response.status_code == 200:
            data = response.json()
            pages = data.get("pages", [])

            print("✅ SUCCESS!")
            print()
            print(f"Pages processed: {len(pages)}")

            if pages:
                markdown = pages[0].get("markdown", "")
                print("Extracted content:")
                print("─" * 60)
                print(markdown[:300] if len(markdown) > 300 else markdown)
                if len(markdown) > 300:
                    print("...")
                print("─" * 60)

            usage = data.get("usage", {})
            if usage:
                print()
                print("Usage:")
                print(f"  Prompt tokens: {usage.get('prompt_tokens', 'N/A')}")
                print(f"  Completion tokens: {usage.get('completion_tokens', 'N/A')}")

            return 0
        else:
            print("❌ FAILED")
            print()
            print("Response body:")
            print(response.text[:500])
            return 1

    except Exception as e:
        print(f"❌ Error: {e}")
        return 1


def main():
    return test_mistral_endpoint()


if __name__ == "__main__":
    sys.exit(main())
