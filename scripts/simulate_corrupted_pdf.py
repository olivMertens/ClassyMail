"""Simulate a corrupted PDF end-to-end.

What it does:
1) Uploads a blob named *.pdf to your configured storage container, but with non-PDF bytes.
2) Triggers the app ingestion via POST /webhook/ingest (BlobCreated Event Grid-style payload).

Expected result:
- The worker downloads the blob, fails stage=download (PDF header check),
  persists an EmailRecord with status=ERROR and error_stage=download,
  and you can see it in the UI under the "⚠ Errors" tab.

Prereqs:
- Set env vars (same as app):
  - AZURE_STORAGE_ACCOUNT_URL (e.g. https://<acct>.blob.core.windows.net)
  - AZURE_STORAGE_CONTAINER (e.g. pdf-inputs)
- Auth:
  - Either `az login` (DefaultAzureCredential), or set AZURE_STORAGE_ACCOUNT_KEY for SAS-less access.
- The app must be running and reachable at BASE_URL (default: http://localhost:8000)

Usage:
  python scripts/simulate_corrupted_pdf.py
  python scripts/simulate_corrupted_pdf.py --base-url https://<aca-app-url>
"""

from __future__ import annotations

import argparse
import os
import uuid
from datetime import datetime, timezone

import httpx


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload a corrupted PDF and trigger ingestion")
    parser.add_argument(
        "--base-url",
        default=os.getenv("BASE_URL", "http://localhost:8000"),
        help="App base URL hosting /webhook/ingest (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--container",
        default=os.getenv("AZURE_STORAGE_CONTAINER", "pdf-inputs"),
        help="Blob container name (default: env AZURE_STORAGE_CONTAINER or pdf-inputs)",
    )
    parser.add_argument(
        "--prefix",
        default="corrupt",
        help="Blob prefix folder inside container (default: corrupt)",
    )
    parser.add_argument(
        "--bytes",
        type=int,
        default=1024,
        help="Payload size in bytes (default: 1024)",
    )
    return parser.parse_args()


async def _upload_corrupted_blob(*, container: str, prefix: str, payload_bytes: int) -> str:
    account_url = os.getenv("AZURE_STORAGE_ACCOUNT_URL")
    if not account_url:
        raise SystemExit("Missing AZURE_STORAGE_ACCOUNT_URL")

    try:
        from azure.identity.aio import DefaultAzureCredential
        from azure.storage.blob.aio import BlobServiceClient
    except Exception as exc:
        raise SystemExit(
            "Missing dependencies: azure-identity + azure-storage-blob. Install via requirements/uv/poetry."
        ) from exc

    # Ensure the content is NOT a PDF (no %PDF header)
    payload = (b"NOT_A_PDF\n" + os.urandom(max(0, payload_bytes - 10)))[:payload_bytes]

    now = datetime.now(timezone.utc)
    name = f"{prefix}/{now.strftime('%Y/%m/%d')}/corrupted_{now.strftime('%H%M%S')}_{uuid.uuid4().hex[:8]}.pdf"

    credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
    bsc = BlobServiceClient(account_url=account_url, credential=credential)

    try:
        container_client = bsc.get_container_client(container)
        try:
            await container_client.create_container()
        except Exception:
            pass

        blob_client = container_client.get_blob_client(name)
        await blob_client.upload_blob(payload, overwrite=True, content_type="application/pdf")
        return blob_client.url
    finally:
        try:
            await bsc.close()
        except Exception:
            pass
        try:
            await credential.close()
        except Exception:
            pass


async def _trigger_ingest(*, base_url: str, blob_url: str) -> None:
    url = base_url.rstrip("/") + "/webhook/ingest"

    # Minimal Event Grid "BlobCreated"-style event the webhook already supports.
    events = [
        {
            "eventType": "Microsoft.Storage.BlobCreated",
            "data": {"url": blob_url},
        }
    ]

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=events)
        resp.raise_for_status()


async def main() -> int:
    args = _parse_args()

    blob_url = await _upload_corrupted_blob(container=args.container, prefix=args.prefix, payload_bytes=args.bytes)
    await _trigger_ingest(base_url=args.base_url, blob_url=blob_url)

    # Item id used by the app is "<container>/<blob-path>".
    try:
        from urllib.parse import urlparse

        parsed = urlparse(blob_url)
        item_id = parsed.path.lstrip("/")
    except Exception:
        item_id = "<container>/<blob-path>"

    print("OK: Corrupted blob uploaded and ingestion triggered")
    print(f"- blob_url: {blob_url}")
    print(f"- expected item id: {item_id}")
    print("Next: open the UI → ⚠ Errors tab (or open the item by id) to see error_stage=download.")
    return 0


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(main()))
