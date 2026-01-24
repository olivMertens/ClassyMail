from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlparse

from azure.core.exceptions import AzureError
from azure.identity.aio import DefaultAzureCredential
from azure.servicebus.aio import ServiceBusClient
from azure.storage.blob.aio import BlobClient, BlobServiceClient
from azure.storage.blob import generate_blob_sas, BlobSasPermissions
from azure.cosmos.aio import CosmosClient
from azure.cosmos import PartitionKey

from classificationg2s.core import config


CONCURRENCY_LIMIT = asyncio.Semaphore(5)
credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)

sb_client: ServiceBusClient | None = None
cosmos_client: CosmosClient | None = None
cosmos_container = None
blob_service_client: BlobServiceClient | None = None

_cosmos_init_lock = asyncio.Lock()


def init_clients() -> None:
    global sb_client, cosmos_client, blob_service_client

    sb_client = ServiceBusClient(fully_qualified_namespace=config.SERVICE_BUS_FQDN, credential=credential)
    blob_service_client = BlobServiceClient(account_url=config.BLOB_ACCOUNT_URL, credential=credential)

    # Keep startup resilient: do not do network calls here.
    cosmos_client = CosmosClient(
        config.COSMOS_ENDPOINT,
        credential=credential if not config.COSMOS_KEY else None,
        key=config.COSMOS_KEY,
    )


async def close_clients() -> None:
    global sb_client, cosmos_client, blob_service_client

    if sb_client:
        await sb_client.close()
    if cosmos_client:
        await cosmos_client.close()
    if blob_service_client:
        await blob_service_client.close()


async def ensure_cosmos_container() -> None:
    global cosmos_client, cosmos_container

    if cosmos_container is not None:
        return
    if not config.COSMOS_ENDPOINT:
        raise RuntimeError("AZURE_COSMOS_ENDPOINT is not set")

    async with _cosmos_init_lock:
        if cosmos_container is not None:
            return

        if cosmos_client is None:
            cosmos_client = CosmosClient(
                config.COSMOS_ENDPOINT,
                credential=credential if not config.COSMOS_KEY else None,
                key=config.COSMOS_KEY,
            )

        db = await cosmos_client.create_database_if_not_exists(id=config.COSMOS_DB)
        cosmos_container = await db.create_container_if_not_exists(
            id=config.COSMOS_CONTAINER,
            partition_key=PartitionKey(path="/id"),
        )


async def auth_headers() -> dict:
    token = await credential.get_token(config.AI_SCOPE)
    return {"Authorization": f"Bearer {token.token}"}


def blob_id_from_url(blob_url: str) -> str:
    parsed = urlparse(blob_url)
    return parsed.path.lstrip("/")


async def download_blob_as_base64(blob_url: str, return_bytes: bool = False) -> str | tuple[str, bytes]:
    blob_client = BlobClient.from_blob_url(blob_url, credential=credential)
    stream = await blob_client.download_blob()
    data = await stream.readall()
    if not data.startswith(b"%PDF"):
        raise ValueError("Corrupted PDF: missing PDF header")
    import base64

    b64 = base64.b64encode(data).decode()
    return (b64, data) if return_bytes else b64


async def build_sas_url(blob_url: str, expiry_minutes: int = 60) -> Optional[str]:
    account_key = os.getenv("AZURE_STORAGE_ACCOUNT_KEY")
    try:
        parsed = urlparse(blob_url)
        account = parsed.netloc.split(".")[0]
        container, *rest = parsed.path.lstrip("/").split("/")
        blob_name = "/".join(rest)
        if not account_key:
            return blob_url
        sas = generate_blob_sas(
            account_name=account,
            account_key=account_key,
            container_name=container,
            blob_name=blob_name,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.utcnow() + timedelta(minutes=expiry_minutes),
        )
        return f"https://{account}.blob.core.windows.net/{container}/{blob_name}?{sas}"
    except Exception:
        return None


async def readiness_checks() -> tuple[bool, dict[str, str]]:
    failures: dict[str, str] = {}

    missing_env: list[str] = []
    if not config.SERVICE_BUS_FQDN:
        missing_env.append("AZURE_SERVICE_BUS_FQDN")
    if not config.BLOB_ACCOUNT_URL:
        missing_env.append("AZURE_STORAGE_ACCOUNT_URL")
    if not config.COSMOS_ENDPOINT:
        missing_env.append("AZURE_COSMOS_ENDPOINT")
    if not config.MISTRAL_ENDPOINT:
        missing_env.append("MISTRAL_ENDPOINT")
    if not config.PHI_ENDPOINT:
        missing_env.append("PHI_ENDPOINT (or AZURE_AI_ENDPOINT)")
    if missing_env:
        failures["config"] = "Missing env vars: " + ", ".join(missing_env)
        return False, failures

    async def _check_credential(timeout_s: float = 3.0) -> None:
        async def _inner():
            await credential.get_token(config.AI_SCOPE)

        await asyncio.wait_for(_inner(), timeout=timeout_s)

    async def _check_servicebus(timeout_s: float = 3.0) -> None:
        if not sb_client:
            raise RuntimeError("Service Bus client not initialized")

        async def _inner():
            sender = sb_client.get_queue_sender(queue_name=config.SERVICE_BUS_QUEUE)
            async with sender:
                return

        await asyncio.wait_for(_inner(), timeout=timeout_s)

    async def _check_storage(timeout_s: float = 3.0) -> None:
        if not blob_service_client:
            raise RuntimeError("Blob service client not initialized")

        async def _inner():
            container_client = blob_service_client.get_container_client(config.BLOB_CONTAINER_INPUT)
            await container_client.get_container_properties()

        await asyncio.wait_for(_inner(), timeout=timeout_s)

    async def _check_cosmos(timeout_s: float = 5.0) -> None:
        async def _inner():
            await ensure_cosmos_container()

        await asyncio.wait_for(_inner(), timeout=timeout_s)

    checks = {
        "credential": _check_credential(),
        "servicebus": _check_servicebus(),
        "storage": _check_storage(),
        "cosmos": _check_cosmos(),
    }
    results = await asyncio.gather(*checks.values(), return_exceptions=True)
    for name, result in zip(checks.keys(), results):
        if isinstance(result, Exception):
            if isinstance(result, asyncio.TimeoutError):
                failures[name] = "timeout"
            elif isinstance(result, AzureError):
                failures[name] = f"azure_error: {type(result).__name__}"
            else:
                failures[name] = f"error: {type(result).__name__}"

    return (len(failures) == 0), failures
