#!/usr/bin/env python3
"""
Azure Content Understanding -- Analyzer Test Script.

Creates a custom CU analyzer and processes a PDF document to validate
the Content Understanding REST API against the ClassyMail insurance schema.

Usage:
    uv run python CU/test_cu_analyzer.py
    uv run python CU/test_cu_analyzer.py --pdf dataset/pdf/sample_001_habitation_1769360840_63600c31.pdf
    uv run python CU/test_cu_analyzer.py --schema CU/analyzer_studio.json --analyzer-id classymail-studio-v1
    uv run python CU/test_cu_analyzer.py --skip-create

Prerequisites:
    - Azure CLI login: az login
    - Or set AZURE_AI_KEY in secrets.env
    - Requires: httpx, azure-identity, python-dotenv (already in project deps)
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CU_API_VERSION = "2025-11-01"
DEFAULT_ENDPOINT = "https://classymail-aifoundry.cognitiveservices.azure.com/"
DEFAULT_ANALYZER_ID = "classymail-insurance-v1"
DEFAULT_SCHEMA_PATH = "CU/analyzer_rest.json"
DEFAULT_PDF_PATH = (
    "dataset/pdf/sample_001_habitation_1769360840_63600c31.pdf"
)

POLL_INTERVAL_S = 3.0
POLL_MAX_WAIT_S = 120.0

logger = logging.getLogger("cu-test")


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

async def get_auth_headers() -> dict[str, str]:
    """
    Get authentication headers for the CU REST API.

    Priority:
      1. AZURE_AI_KEY env var  -> Ocp-Apim-Subscription-Key header
      2. DefaultAzureCredential -> Authorization: Bearer header

    Note: CU uses ``Ocp-Apim-Subscription-Key`` for key auth (not ``api-key``
    like Azure OpenAI).
    """
    api_key = os.getenv("AZURE_AI_KEY")
    if api_key:
        logger.info("Auth: using API key (AZURE_AI_KEY)")
        return {
            "Content-Type": "application/json",
            "Ocp-Apim-Subscription-Key": api_key,
        }

    from azure.identity.aio import DefaultAzureCredential

    logger.info("Auth: using DefaultAzureCredential")
    credential = DefaultAzureCredential(
        exclude_interactive_browser_credential=True
    )
    try:
        scope = os.getenv(
            "AZURE_AI_SCOPE",
            "https://cognitiveservices.azure.com/.default",
        )
        token = await credential.get_token(scope)
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token.token}",
        }
    finally:
        await credential.close()


# ---------------------------------------------------------------------------
# Step 1 -- Create / update analyzer
# ---------------------------------------------------------------------------

async def create_or_update_analyzer(
    client: httpx.AsyncClient,
    endpoint: str,
    analyzer_id: str,
    schema_path: str,
    headers: dict[str, str],
) -> dict:
    """PUT .../contentunderstanding/analyzers/{analyzerId}."""
    url = (
        f"{endpoint.rstrip('/')}/contentunderstanding"
        f"/analyzers/{analyzer_id}"
    )
    params = {"api-version": CU_API_VERSION}

    schema_file = Path(schema_path)
    if not schema_file.exists():
        raise FileNotFoundError(f"Schema not found: {schema_path}")

    body = json.loads(schema_file.read_text(encoding="utf-8"))
    logger.info("PUT %s", url)

    resp = await client.put(url, json=body, headers=headers, params=params)

    if resp.status_code in (200, 201):
        # Analyzer creation is async -- poll the Operation-Location
        op_url = resp.headers.get("Operation-Location")
        if op_url:
            logger.info("Waiting for analyzer provisioning...")
            await _poll_operation(client, op_url, headers)
        return resp.json() if resp.text else {}

    logger.error("PUT failed: HTTP %d -- %s", resp.status_code, resp.text[:500])
    resp.raise_for_status()
    return {}


async def _poll_operation(
    client: httpx.AsyncClient,
    operation_url: str,
    headers: dict[str, str],
) -> None:
    """Poll an Operation-Location URL until succeeded/failed."""
    start = time.monotonic()
    while True:
        elapsed = time.monotonic() - start
        if elapsed > POLL_MAX_WAIT_S:
            raise TimeoutError("Analyzer provisioning timed out")

        resp = await client.get(operation_url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status", "unknown").lower()

        logger.info("  Provisioning: %s (%.0fs)", status, elapsed)

        if status == "succeeded":
            return
        if status == "failed":
            raise RuntimeError(
                f"Provisioning failed: {json.dumps(data.get('error', {}))}"
            )

        await asyncio.sleep(POLL_INTERVAL_S)


# ---------------------------------------------------------------------------
# Step 2 -- Submit document for analysis
# ---------------------------------------------------------------------------

async def analyze_document(
    client: httpx.AsyncClient,
    endpoint: str,
    analyzer_id: str,
    pdf_path: str,
    headers: dict[str, str],
) -> str:
    """
    POST .../analyzers/{analyzerId}:analyze.

    Submits a PDF as base64 inline data. Returns the Operation-Location URL
    to poll for results.
    """
    url = (
        f"{endpoint.rstrip('/')}/contentunderstanding"
        f"/analyzers/{analyzer_id}:analyze"
    )
    params = {"api-version": CU_API_VERSION}

    pdf_file = Path(pdf_path)
    if not pdf_file.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    pdf_bytes = pdf_file.read_bytes()
    pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")
    size_kb = len(pdf_bytes) / 1024

    logger.info(
        "Analyzing '%s' (%.1f KB) with analyzer '%s'",
        pdf_file.name, size_kb, analyzer_id,
    )
    logger.info("POST %s", url)

    body = {
        "inputs": [
            {"url": f"data:application/pdf;base64,{pdf_b64}"}
        ]
    }

    resp = await client.post(url, json=body, headers=headers, params=params)

    if resp.status_code == 202:
        op_url = resp.headers.get("Operation-Location", "")
        logger.info("Submitted (HTTP 202). Operation-Location: %s", op_url)
        return op_url

    # Some CU versions return 200 with inline result
    if resp.status_code == 200:
        op_url = resp.headers.get("Operation-Location", "")
        if op_url:
            return op_url
        # Result returned inline -- write directly
        result_path = Path("CU/last_result.json")
        result_path.write_text(
            json.dumps(resp.json(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Inline result saved to %s", result_path)
        return ""

    logger.error(
        "Analyze failed: HTTP %d -- %s", resp.status_code, resp.text[:500]
    )
    resp.raise_for_status()
    return ""


# ---------------------------------------------------------------------------
# Step 3 -- Poll for results
# ---------------------------------------------------------------------------

async def poll_result(
    client: httpx.AsyncClient,
    operation_url: str,
    headers: dict[str, str],
    poll_interval: float = POLL_INTERVAL_S,
    max_wait: float = POLL_MAX_WAIT_S,
) -> dict:
    """GET the Operation-Location URL until status is succeeded or failed."""
    start = time.monotonic()
    attempt = 0

    while True:
        attempt += 1
        elapsed = time.monotonic() - start

        if elapsed > max_wait:
            raise TimeoutError(
                f"Analysis did not complete within {max_wait:.0f}s "
                f"({attempt} polls)"
            )

        resp = await client.get(operation_url, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        status = data.get("status", "unknown").lower()
        logger.info("  Poll #%d (%.0fs): status=%s", attempt, elapsed, status)

        if status == "succeeded":
            return data
        if status == "failed":
            error = data.get("error", {})
            raise RuntimeError(
                f"Analysis failed: {error.get('code', '?')} -- "
                f"{error.get('message', json.dumps(error))}"
            )

        await asyncio.sleep(poll_interval)


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def display_results(data: dict) -> None:
    """Pretty-print the CU analysis results."""
    result = data.get("result", data)

    print("\n" + "=" * 70)
    print("ANALYSIS RESULTS")
    print("=" * 70)

    analyzer_id = result.get("analyzerId", "?")
    api_version = result.get("apiVersion", "?")
    print(f"  Analyzer: {analyzer_id}  |  API: {api_version}")

    contents = result.get("contents", [])
    for i, content in enumerate(contents):
        print(f"\n--- Content segment {i + 1} ---")

        # Category (if present)
        category = content.get("category")
        if category:
            print(f"  [category]: {category}")

        fields = content.get("fields", {})
        for field_name, field_data in fields.items():
            _print_field(field_name, field_data, indent=2)

    # Usage / billing
    usage = data.get("usage", {})
    if usage:
        print("\n--- Usage (billing) ---")
        for k, v in usage.items():
            if isinstance(v, dict):
                print(f"  {k}:")
                for sk, sv in v.items():
                    print(f"    {sk}: {sv}")
            else:
                print(f"  {k}: {v}")


def _print_field(name: str, field: dict, indent: int = 2) -> None:
    """Print a single CU field recursively."""
    prefix = " " * indent
    ftype = field.get("type", "?")

    if ftype == "array":
        items = field.get("valueArray", [])
        print(f"{prefix}{name}: ({len(items)} items)")
        for j, item in enumerate(items):
            obj = item.get("valueObject", item)
            if isinstance(obj, dict):
                parts = []
                for k, v in obj.items():
                    val = v.get("valueString") or v.get("valueNumber") or v.get("valueDate", "")
                    conf = v.get("confidence")
                    conf_s = f" [{conf:.2f}]" if conf is not None else ""
                    parts.append(f"{k}={val}{conf_s}")
                print(f"{prefix}  [{j}] {', '.join(parts)}")
            else:
                print(f"{prefix}  [{j}] {obj}")
    elif ftype == "object":
        obj = field.get("valueObject", {})
        print(f"{prefix}{name}:")
        for k, v in obj.items():
            _print_field(k, v, indent + 2)
    else:
        val = (
            field.get("valueString")
            or field.get("valueNumber")
            or field.get("valueDate")
            or ""
        )
        conf = field.get("confidence")
        conf_s = f" (confidence: {conf:.2f})" if conf is not None else ""
        src = field.get("source", "")
        src_s = f" [grounding: {src[:60]}...]" if len(str(src)) > 60 else (f" [grounding: {src}]" if src else "")
        print(f"{prefix}{name}: {val}{conf_s}{src_s}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Azure Content Understanding -- Analyzer Test",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  uv run python CU/test_cu_analyzer.py
  uv run python CU/test_cu_analyzer.py --pdf dataset/pdf/sample_005_evt_naturel_1769360863_12d6166d.pdf
  uv run python CU/test_cu_analyzer.py --schema CU/analyzer_studio.json --analyzer-id classymail-studio-v1
  uv run python CU/test_cu_analyzer.py --skip-create
""",
    )

    parser.add_argument(
        "--endpoint",
        default=os.getenv("AZURE_AI_ENDPOINT", DEFAULT_ENDPOINT),
        help="AI Foundry endpoint (default: $AZURE_AI_ENDPOINT)",
    )
    parser.add_argument(
        "--analyzer-id",
        default=DEFAULT_ANALYZER_ID,
        help=f"Analyzer ID (default: {DEFAULT_ANALYZER_ID})",
    )
    parser.add_argument(
        "--schema",
        default=DEFAULT_SCHEMA_PATH,
        help=f"Analyzer JSON schema path (default: {DEFAULT_SCHEMA_PATH})",
    )
    parser.add_argument(
        "--pdf",
        default=DEFAULT_PDF_PATH,
        help="PDF file to analyze",
    )
    parser.add_argument(
        "--skip-create",
        action="store_true",
        help="Skip analyzer creation (use existing)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=POLL_INTERVAL_S,
        help=f"Poll interval in seconds (default: {POLL_INTERVAL_S})",
    )
    parser.add_argument(
        "--max-wait",
        type=float,
        default=POLL_MAX_WAIT_S,
        help=f"Max wait time in seconds (default: {POLL_MAX_WAIT_S})",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
    )

    load_dotenv("secrets.env")

    print("=" * 70)
    print("Azure Content Understanding -- Analyzer Test")
    print("=" * 70)
    print(f"  Endpoint:    {args.endpoint}")
    print(f"  Analyzer:    {args.analyzer_id}")
    print(f"  Schema:      {args.schema}")
    print(f"  PDF:         {args.pdf}")
    print(f"  API version: {CU_API_VERSION}")
    print()

    # -- Authenticate -------------------------------------------------------
    try:
        headers = await get_auth_headers()
        print("[1/4] Authentication: OK")
    except Exception as exc:
        print(f"[1/4] Authentication: FAILED -- {exc}")
        return 1

    async with httpx.AsyncClient(timeout=120) as client:

        # -- Create / update analyzer --------------------------------------
        if not args.skip_create:
            try:
                await create_or_update_analyzer(
                    client, args.endpoint, args.analyzer_id,
                    args.schema, headers,
                )
                print(f"[2/4] Analyzer '{args.analyzer_id}': OK")
            except Exception as exc:
                print(f"[2/4] Analyzer creation: FAILED -- {exc}")
                return 1
        else:
            print("[2/4] Analyzer creation: SKIPPED (--skip-create)")

        # -- Submit document ------------------------------------------------
        try:
            operation_url = await analyze_document(
                client, args.endpoint, args.analyzer_id,
                args.pdf, headers,
            )
            print("[3/4] Document submitted: OK")
        except Exception as exc:
            print(f"[3/4] Document submission: FAILED -- {exc}")
            return 1

        # -- Poll for results -----------------------------------------------
        if not operation_url:
            print("[4/4] Result returned inline (see CU/last_result.json)")
            return 0

        try:
            print(f"[4/4] Polling for results (max {args.max_wait:.0f}s)...")
            data = await poll_result(
                client, operation_url, headers,
                poll_interval=args.poll_interval,
                max_wait=args.max_wait,
            )
            print("[4/4] Analysis complete: OK")

            display_results(data)

            # Save raw result
            result_path = Path("CU/last_result.json")
            result_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            print(f"\nRaw JSON saved to: {result_path}")

        except TimeoutError as exc:
            print(f"[4/4] Analysis: TIMEOUT -- {exc}")
            return 1
        except RuntimeError as exc:
            print(f"[4/4] Analysis: FAILED -- {exc}")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
