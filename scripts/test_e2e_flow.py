#!/usr/bin/env python3
"""
End-to-end test script that generates realistic emails and uploads them via API.

This script:
1. Generates realistic French insurance email PDFs
2. Uploads them to the API (/api/upload)
3. Waits for processing
4. Checks the results

Usage:
    uv run python scripts/test_e2e_flow.py --count 5 --api-url http://localhost:8000
"""

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from classificationg2s.services.generator import generate_email_pdf




def upload_pdf(api_url: str, pdf_bytes: bytes, filename: str) -> dict:
    """Upload a PDF via the API."""
    url = f"{api_url.rstrip('/')}/api/upload"

    files = {
        "file": (filename, pdf_bytes, "application/pdf")
    }

    try:
        response = httpx.post(url, files=files, timeout=30.0)
        response.raise_for_status()
        return {"success": True, "data": response.json()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def check_email_status(api_url: str, email_id: str) -> dict:
    """Check the status of a processed email."""
    url = f"{api_url.rstrip('/')}/api/emails/{email_id}"

    try:
        response = httpx.get(url, timeout=10.0)
        response.raise_for_status()
        return {"success": True, "data": response.json()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="E2E test with realistic email generation")
    parser.add_argument("--count", type=int, default=5, help="Number of emails to generate")
    parser.add_argument("--api-url", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--wait", type=int, default=10, help="Seconds to wait between uploads")
    parser.add_argument("--use-aoai", action="store_true", help="Use Azure OpenAI to enhance email bodies")
    args = parser.parse_args()

    print("=" * 70)
    print("📧 End-to-End Email Classification Test")
    print("=" * 70)
    print()
    print(f"API URL: {args.api_url}")
    print(f"Emails to generate: {args.count}")
    print(f"Wait time: {args.wait}s")
    print(f"Use AOAI enhancement: {args.use_aoai}")
    print()

    # Generate and upload emails
    results = []

    for i in range(args.count):
        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"test_email_{timestamp}_{i+1}.pdf"

        print(f"[{i+1}/{args.count}] Generating email...")

        # Generate PDF
        pdf_bytes, category, subject = generate_email_pdf(use_aoai=args.use_aoai)

        print(f"  Category: {category}")
        print(f"  Subject: {subject}")
        print(f"  PDF size: {len(pdf_bytes):,} bytes")

        # Upload
        print(f"  Uploading to {args.api_url}...")
        result = upload_pdf(args.api_url, pdf_bytes, filename)

        if result["success"]:
            email_id = result["data"].get("email_id")
            print(f"  ✅ Uploaded! Email ID: {email_id}")
            results.append({
                "filename": filename,
                "category": category,
                "email_id": email_id,
                "uploaded": True
            })
        else:
            print(f"  ❌ Upload failed: {result['error']}")
            results.append({
                "filename": filename,
                "category": category,
                "uploaded": False,
                "error": result["error"]
            })

        print()

        # Wait before next upload (except for last one)
        if i < args.count - 1:
            print(f"⏳ Waiting {args.wait}s before next upload...")
            time.sleep(args.wait)
            print()

    # Summary
    print()
    print("=" * 70)
    print("📊 SUMMARY")
    print("=" * 70)

    uploaded = [r for r in results if r.get("uploaded")]
    failed = [r for r in results if not r.get("uploaded")]

    print(f"\n✅ Successfully uploaded: {len(uploaded)}/{args.count}")
    if uploaded:
        print("\nUploaded emails:")
        for r in uploaded:
            print(f"  • {r['filename']} (ID: {r['email_id']}) - Expected: {r['category']}")

    if failed:
        print(f"\n❌ Failed uploads: {len(failed)}")
        for r in failed:
            print(f"  • {r['filename']}: {r.get('error', 'Unknown error')}")

    print()
    print("💡 Next steps:")
    print(f"  1. Check dashboard: {args.api_url}")
    print("  2. Wait for processing to complete (~30-60s per email)")
    print("  3. Verify classifications match expected categories")
    if not args.use_aoai:
        print("  4. For more realistic emails, run with: --use-aoai (requires AZURE_OPENAI_ENDPOINT)")
    print()

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
