#!/usr/bin/env python3
"""
Quick test script to verify Mistral Document AI endpoint is working.
Tests the Microsoft Foundry endpoint with a sample PDF.

Usage:
    uv run python scripts/check_mistral_ocr.py
"""

import sys
import base64
import asyncio
from pathlib import Path

# Add parent directory to path to import from classificationg2s
sys.path.insert(0, str(Path(__file__).parent.parent))

from classificationg2s.services.llm_pipeline import ocr_with_mistral
from classificationg2s.services.azure_clients import Clients
from classificationg2s.core import config


async def test_ocr():
    """Test OCR with a small sample PDF."""
    print("🔍 Testing Mistral Document AI OCR endpoint...")
    print(f"   Endpoint: {config.MISTRAL_ENDPOINT}")
    print(f"   Deployment: {config.MISTRAL_DEPLOYMENT}")
    print()

    # Check if we have a sample PDF in dataset/pdf/
    dataset_dir = Path(__file__).parent.parent / "dataset" / "pdf"
    sample_pdfs = list(dataset_dir.glob("*.pdf"))

    if not sample_pdfs:
        print("⚠️  No PDF files found in dataset/pdf/")
        print("   Generating a minimal test PDF in memory...")
        # Create a minimal PDF with text
        from io import BytesIO
        try:
            from fpdf import FPDF
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", size=12)
            pdf.cell(200, 10, txt="Test Document for OCR", ln=True, align="C")
            pdf.cell(200, 10, txt="This is a test email about insurance.", ln=True)
            buffer = BytesIO()
            pdf.output(buffer)
            pdf_bytes = buffer.getvalue()
            base64_pdf = base64.b64encode(pdf_bytes).decode("utf-8")
            print("   ✅ Generated test PDF in memory")
        except ImportError:
            print("   ❌ fpdf2 not installed, cannot generate test PDF")
            print("   Install with: uv pip install fpdf2")
            return
    else:
        # Use first PDF found
        sample_pdf = sample_pdfs[0]
        print(f"   Using sample PDF: {sample_pdf.name}")
        with open(sample_pdf, "rb") as f:
            pdf_bytes = f.read()
        base64_pdf = base64.b64encode(pdf_bytes).decode("utf-8")
        print(f"   PDF size: {len(pdf_bytes):,} bytes")

    print()
    print("📤 Sending request to Mistral Document AI...")

    try:
        # Create clients
        clients = Clients.create_from_env()

        # Call OCR (no image extraction for this test)
        result = await ocr_with_mistral(base64_pdf, clients=clients, include_images=False)

        print("✅ OCR SUCCESS!")
        print()
        print("📄 Extracted Content:")
        print("─" * 80)
        content = result.get("content", "")
        if len(content) > 500:
            print(content[:500] + "...")
            print(f"... (truncated, total {len(content)} chars)")
        else:
            print(content)
        print("─" * 80)
        print()
        print("📊 Metadata:")
        print(f"   Pages processed: {result.get('pages_count', 'N/A')}")
        print(f"   Images found: {len(result.get('annotated_images', []))}")
        print()
        print("🎉 Test completed successfully!")

    except Exception as e:
        print("❌ OCR FAILED!")
        print(f"   Error: {e}")
        print()
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(test_ocr())
