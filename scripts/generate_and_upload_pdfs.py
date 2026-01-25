"""Generate PDFs via existing generator and upload to Azure Blob.

This matches the ingestion convention used by the API: blobs are written under
`uploads/YYYY/MM/DD/...`.

Prereqs:
- Generate env file from your deployed RG:
  `pwsh scripts/write_secrets_env.ps1 -ResourceGroup <rg> -Force`
- Auth: DefaultAzureCredential (e.g., `az login` locally)

Usage (generate + upload directly to Blob):
  uv run python scripts/generate_and_upload_pdfs.py --count 20 --out dataset/pdf --use-aoai

If Storage is private from your machine, upload via the deployed API instead:
  uv run python scripts/generate_and_upload_pdfs.py --only-upload --out dataset/pdf --upload-via-api
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import httpx
from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob.aio import BlobServiceClient


def load_env_from_file(path: str = "secrets.env", *, override: bool = False) -> None:
    """Minimal env loader for KEY=VALUE lines (ignores comments/blank lines)."""
    p = Path(path)
    if not p.exists():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if not key or value is None:
            continue
        if override or key not in os.environ:
            os.environ[key] = value


async def upload_files(
    files: Iterable[Path], *, container: str, prefix: str = "uploads", account_url: str | None = None
) -> list[str]:
    account_url = account_url or os.getenv("AZURE_STORAGE_ACCOUNT_URL")
    if not account_url:
        raise SystemExit("Missing AZURE_STORAGE_ACCOUNT_URL")

    credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
    bsc = BlobServiceClient(account_url=account_url, credential=credential)
    try:
        container_client = bsc.get_container_client(container)
        try:
            await container_client.create_container()
        except Exception:
            # container exists OR data-plane blocked
            pass

        now = datetime.now(timezone.utc)
        date_prefix = now.strftime("%Y/%m/%d")

        uploaded: list[str] = []
        for fpath in files:
            name = fpath.name
            blob_name = f"{prefix}/{date_prefix}/{name}"
            blob_client = container_client.get_blob_client(blob_name)
            await blob_client.upload_blob(fpath.read_bytes(), overwrite=True, content_type="application/pdf")
            uploaded.append(f"{account_url.rstrip('/')}/{container}/{blob_name}")
        return uploaded
    finally:
        try:
            await bsc.close()
        finally:
            await credential.close()


async def upload_via_api(files: list[Path], *, api_base_url: str) -> list[str]:
    api_base_url = api_base_url.rstrip("/")
    url = f"{api_base_url}/api/upload"

    uploaded: list[str] = []
    async with httpx.AsyncClient(timeout=120) as client:
        # API accepts up to 10 PDFs per request.
        for i in range(0, len(files), 10):
            chunk = files[i : i + 10]
            handles = []
            multipart = []
            try:
                for fpath in chunk:
                    fh = open(fpath, "rb")
                    handles.append(fh)
                    multipart.append(("files", (fpath.name, fh, "application/pdf")))
                resp = await client.post(url, files=multipart)
                resp.raise_for_status()
                payload = resp.json()
                for item in payload.get("results", []):
                    if item.get("status") == "uploaded" and item.get("blob_url"):
                        uploaded.append(item["blob_url"])
            finally:
                for fh in handles:
                    try:
                        fh.close()
                    except Exception:
                        pass
    return uploaded


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate PDF files and upload to Azure Blob")
    parser.add_argument("--count", type=int, default=20, help="Number of PDFs to generate (default: 20)")
    parser.add_argument("--out", type=str, default="dataset/pdf", help="Output folder for PDFs (also input when --only-upload)")
    parser.add_argument(
        "--container",
        type=str,
        default=os.getenv("AZURE_STORAGE_CONTAINER", "pdf-inputs"),
        help="Blob container (default env AZURE_STORAGE_CONTAINER or pdf-inputs)",
    )
    parser.add_argument("--prefix", type=str, default="uploads", help="Blob prefix inside container (default: uploads)")
    parser.add_argument("--use-aoai", action="store_true", help="Use Azure OpenAI for richer email bodies")
    parser.add_argument(
        "--aoai-deployment",
        type=str,
        default=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini"),
        help="Azure OpenAI deployment name (default: gpt-4o-mini)",
    )
    parser.add_argument("--include-corrupted", type=int, default=0, help="Generate N corrupted PDFs alongside valid ones")
    parser.add_argument("--only-upload", action="store_true", help="Skip generation; upload existing PDFs from --out")
    parser.add_argument("--env-file", type=str, default="secrets.env", help="Path to env file to load (default: secrets.env)")
    parser.add_argument(
        "--upload-via-api",
        action="store_true",
        help="Upload through the app /api/upload endpoint (useful if Storage is private from your machine)",
    )
    parser.add_argument(
        "--api-base-url",
        type=str,
        default=os.getenv("API_BASE_URL") or os.getenv("BASE_URL"),
        help="Base URL for the app (e.g. https://<aca-fqdn>). Defaults to env API_BASE_URL/BASE_URL.",
    )
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    return parser.parse_args()


async def run() -> int:
    load_env_from_file()  # load defaults from secrets.env before parsing
    args = parse_args()
    if args.env_file and args.env_file != "secrets.env":
        load_env_from_file(args.env_file, override=True)
    out_dir = Path(args.out)

    if not args.only_upload:
        # Generate PDFs using existing generator (subprocess because it parses argv)
        gen_script = Path(__file__).resolve().parent / "generate_dummy_pdfs.py"
        gen_args = [str(gen_script), "--count", str(args.count), "--out", str(out_dir)]
        if args.use_aoai:
            gen_args += ["--use-aoai", "--aoai-deployment", args.aoai_deployment]
        if args.seed is not None:
            gen_args += ["--seed", str(args.seed)]

        proc = await asyncio.create_subprocess_exec(sys.executable, *gen_args)
        exit_code = await proc.wait()
        if exit_code:
            return exit_code

    # Optionally add corrupted PDFs locally (simple non-PDF bytes)
    for i in range(args.include_corrupted):
        corrupted = out_dir / f"corrupted_{i+1:02d}.pdf"
        corrupted.write_bytes(b"NOT_A_PDF\n" + os.urandom(512))

    pdf_files = sorted(list(out_dir.glob("*.pdf")) + list(out_dir.glob("*.PDF")))
    if not pdf_files:
        raise SystemExit(f"No PDFs found in {out_dir}")

    if args.upload_via_api:
        if not args.api_base_url:
            raise SystemExit("Missing --api-base-url (or env API_BASE_URL) for --upload-via-api")
        uploaded = await upload_via_api(pdf_files, api_base_url=args.api_base_url)
    else:
        uploaded = await upload_files(pdf_files, container=args.container, prefix=args.prefix)
    print("Uploaded blobs:")
    for u in uploaded:
        print(f"- {u}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
