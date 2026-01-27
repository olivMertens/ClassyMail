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
try:
    from fastapi import Depends, HTTPException, Request
except Exception:
    # FastAPI not available in worker context tests
    Request = None
    Depends = None
    HTTPException = None


CONCURRENCY_DEFAULT = 5


class Clients:
    def __init__(self, *, concurrency_limit: int = CONCURRENCY_DEFAULT):
        self.credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
        self.concurrency_limit = asyncio.Semaphore(concurrency_limit)
        self.sb_client: ServiceBusClient | None = None
        self.cosmos_client: CosmosClient | None = None
        self.cosmos_container = None
        self.blob_service_client: BlobServiceClient | None = None
        self._cosmos_init_lock = asyncio.Lock()

    async def init(self) -> None:
        # Keep startup resilient: avoid network calls here.
        self.sb_client = ServiceBusClient(fully_qualified_namespace=config.SERVICE_BUS_FQDN, credential=self.credential)
        self.blob_service_client = BlobServiceClient(account_url=config.BLOB_ACCOUNT_URL, credential=self.credential)
        self.cosmos_client = CosmosClient(
            config.COSMOS_ENDPOINT,
            credential=self.credential if not config.COSMOS_KEY else None,
            key=config.COSMOS_KEY,
        )

    async def close(self) -> None:
        if self.sb_client:
            await self.sb_client.close()
        if self.cosmos_client:
            await self.cosmos_client.close()
        if self.blob_service_client:
            await self.blob_service_client.close()

    async def ensure_cosmos_container(self):
        if self.cosmos_container is not None:
            return
        if not config.COSMOS_ENDPOINT:
            raise RuntimeError("AZURE_COSMOS_ENDPOINT is not set")

        async with self._cosmos_init_lock:
            if self.cosmos_container is not None:
                return

            if self.cosmos_client is None:
                self.cosmos_client = CosmosClient(
                    config.COSMOS_ENDPOINT,
                    credential=self.credential if not config.COSMOS_KEY else None,
                    key=config.COSMOS_KEY,
                )

            db = await self.cosmos_client.create_database_if_not_exists(id=config.COSMOS_DB)
            self.cosmos_container = await db.create_container_if_not_exists(
                id=config.COSMOS_CONTAINER,
                partition_key=PartitionKey(path="/id"),
            )
_DEFAULT_CLIENTS: Clients | None = None


def set_default_clients(clients: Clients) -> None:
    global _DEFAULT_CLIENTS
    _DEFAULT_CLIENTS = clients


def get_default_clients() -> Clients:
    if _DEFAULT_CLIENTS is None:
        raise RuntimeError("Clients not initialized")
    return _DEFAULT_CLIENTS


# FastAPI dependencies
def get_clients(request: Request) -> Clients:
    clients = getattr(request.app.state, "clients", None)
    if clients is None:
        if HTTPException:
            raise HTTPException(status_code=503, detail="Clients not initialized")
        raise RuntimeError("Clients not initialized")
    return clients


async def get_sb_client(clients: Clients = Depends(get_clients)) -> ServiceBusClient:
    if not clients.sb_client:
        if HTTPException:
            raise HTTPException(status_code=503, detail="Service Bus client not initialized")
        raise RuntimeError("Service Bus client not initialized")
    return clients.sb_client


async def get_blob_service_client(clients: Clients = Depends(get_clients)) -> BlobServiceClient:
    if not clients.blob_service_client:
        if HTTPException:
            raise HTTPException(status_code=503, detail="Blob service client not initialized")
        raise RuntimeError("Blob service client not initialized")
    return clients.blob_service_client


async def get_cosmos_container(clients: Clients = Depends(get_clients)):
    try:
        await clients.ensure_cosmos_container()
        return clients.cosmos_container
    except Exception as e:
        if HTTPException:
            raise HTTPException(
                status_code=503,
                detail=f"Database unavailable: {str(e)}. Ensure Cosmos DB is provisioned and identity has 'Cosmos DB Built-in Data Contributor' role.",
            )
        raise


def get_concurrency_limit(clients: Clients = Depends(get_clients)) -> asyncio.Semaphore:
    return clients.concurrency_limit


async def auth_headers(clients: Clients | None = None) -> dict:
    clients = clients or get_default_clients()
    token = await clients.credential.get_token(config.AI_SCOPE)
    return {"Authorization": f"Bearer {token.token}"}


def blob_id_from_url(blob_url: str) -> str:
    parsed = urlparse(blob_url)
    # Cosmos DB IDs cannot contain '/', so we replace with '-'
    # e.g., pdf-inputs/doc.pdf -> pdf-inputs-doc.pdf
    return parsed.path.lstrip("/").replace("/", "-")


async def download_blob_as_base64(blob_url: str, return_bytes: bool = False, clients: Clients | None = None) -> str | tuple[str, bytes]:
    clients = clients or get_default_clients()
    blob_client = BlobClient.from_blob_url(blob_url, credential=clients.credential)
    stream = await blob_client.download_blob()
    data = await stream.readall()
    if not data.startswith(b"%PDF"):
        raise ValueError("Corrupted PDF: missing PDF header")
    import base64

    b64 = base64.b64encode(data).decode()
    return (b64, data) if return_bytes else b64


async def build_sas_url(blob_url: str, expiry_minutes: int = 60, clients: Clients | None = None) -> Optional[str]:
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


async def readiness_checks(
    *,
    clients: Clients | None = None,
    deep: bool = False,
) -> tuple[bool, dict[str, str]]:
    clients = clients or get_default_clients()
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

    # Shallow readiness is intended for platform probes (e.g., Azure Container Apps).
    # It verifies basic configuration and initialization without making network calls.
    if not deep:
        if clients.sb_client is None:
            failures["servicebus"] = "client not initialized"
        if clients.blob_service_client is None:
            failures["storage"] = "client not initialized"
        if clients.cosmos_client is None:
            failures["cosmos"] = "client not initialized"
        return (len(failures) == 0), failures

    async def _check_credential(timeout_s: float = 3.0) -> None:
        async def _inner():
            await clients.credential.get_token(config.AI_SCOPE)

        await asyncio.wait_for(_inner(), timeout=timeout_s)

    async def _check_servicebus(timeout_s: float = 3.0) -> None:
        if not clients.sb_client:
            raise RuntimeError("Service Bus client not initialized")

        async def _inner():
            sender = clients.sb_client.get_queue_sender(queue_name=config.SERVICE_BUS_QUEUE)
            async with sender:
                return

        await asyncio.wait_for(_inner(), timeout=timeout_s)

    async def _check_storage(timeout_s: float = 3.0) -> None:
        if not clients.blob_service_client:
            raise RuntimeError("Blob service client not initialized")

        async def _inner():
            container_client = clients.blob_service_client.get_container_client(config.BLOB_CONTAINER_INPUT)
            await container_client.get_container_properties()

        await asyncio.wait_for(_inner(), timeout=timeout_s)

    async def _check_cosmos(timeout_s: float = 5.0) -> None:
        async def _inner():
            await clients.ensure_cosmos_container()

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
