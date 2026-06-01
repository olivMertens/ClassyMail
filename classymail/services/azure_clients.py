from __future__ import annotations

import asyncio
import os
import logging
from urllib.parse import urlparse

from azure.core.exceptions import AzureError
from azure.identity.aio import DefaultAzureCredential
from azure.servicebus.aio import ServiceBusClient
from azure.servicebus.management import ServiceBusAdministrationClient
from azure.storage.blob.aio import BlobClient, BlobServiceClient
from azure.cosmos.aio import CosmosClient
from azure.cosmos import PartitionKey

from classymail.core import config

logger = logging.getLogger(__name__)
try:
    from fastapi import Depends, HTTPException, Request
except Exception:
    # FastAPI not available in worker context tests
    Request = None
    Depends = None
    HTTPException = None


# Worker concurrency: Configurable via WORKER_CONCURRENCY env var
# Increased from 5 to 30 for better throughput on modern Container Apps (1 vCPU / 2GB RAM)
CONCURRENCY_DEFAULT = int(os.getenv("WORKER_CONCURRENCY", "30"))


class Clients:
    def __init__(self, *, concurrency_limit: int = CONCURRENCY_DEFAULT):
        self.credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
        self.concurrency_limit = asyncio.Semaphore(concurrency_limit)
        self.sb_client: ServiceBusClient | None = None
        self.sb_admin_client: ServiceBusAdministrationClient | None = None
        self.cosmos_client: CosmosClient | None = None
        self.cosmos_container = None
        self.blob_service_client: BlobServiceClient | None = None
        self._cosmos_init_lock = asyncio.Lock()
        self._cosmos_last_health_check: float = 0.0  # monotonic timestamp

        # RAG Containers
        self.cosmos_chat_container = None
        self.cosmos_cache_container = None

        # Shared httpx client (TLS handshake + connection pool reused across calls).
        # Per-call timeouts are still possible via request kwargs.
        import httpx as _httpx

        self.http: _httpx.AsyncClient = _httpx.AsyncClient(
            timeout=_httpx.Timeout(30.0, connect=10.0),
            limits=_httpx.Limits(max_keepalive_connections=20, max_connections=100),
        )

    async def init(self) -> None:
        # Keep startup resilient: avoid network calls here.
        sb_conn_str = os.getenv("AZURE_SERVICE_BUS_CONNECTION_STRING")
        if sb_conn_str:
            self.sb_client = ServiceBusClient.from_connection_string(conn_str=sb_conn_str)
        else:
            self.sb_client = ServiceBusClient(fully_qualified_namespace=config.SERVICE_BUS_FQDN, credential=self.credential)

        self.blob_service_client = BlobServiceClient(account_url=config.BLOB_ACCOUNT_URL, credential=self.credential)
        self.cosmos_client = CosmosClient(
            config.COSMOS_ENDPOINT,
            credential=config.COSMOS_KEY if config.COSMOS_KEY else self.credential,
        )

    async def close(self) -> None:
        if self.sb_client:
            await self.sb_client.close()
        if self.sb_admin_client:
            self.sb_admin_client.close()
        if self.cosmos_client:
            await self.cosmos_client.close()
        if self.blob_service_client:
            await self.blob_service_client.close()
        try:
            await self.http.aclose()
        except Exception:
            pass

    # Rate-limit health checks to avoid burning RUs on every call.
    # ensure_cosmos_container is called 5+ times per /api/emails request
    # (get_cosmos_container, count_by_status x2, count_reviewed_ready, get_average_confidence).
    _HEALTH_CHECK_INTERVAL_S = float(os.getenv("COSMOS_HEALTH_CHECK_INTERVAL_S", "300"))

    async def ensure_cosmos_container(self):
        import time as _time

        # Fast path: container already initialised and health check not due yet
        if self.cosmos_container is not None:
            now = _time.monotonic()
            if (now - self._cosmos_last_health_check) < self._HEALTH_CHECK_INTERVAL_S:
                return  # skip redundant health check

        # Acquire lock to prevent concurrent reconnections (race-condition fix)
        async with self._cosmos_init_lock:
            # Re-check inside lock (another coroutine may have already fixed it)
            if self.cosmos_container is not None:
                now = _time.monotonic()
                if (now - self._cosmos_last_health_check) < self._HEALTH_CHECK_INTERVAL_S:
                    return

                # Health check is due – run inside the lock
                try:
                    await self.cosmos_container.read()
                    self._cosmos_last_health_check = _time.monotonic()
                    return  # still healthy
                except Exception as health_error:
                    logger.warning(
                        "Cosmos health check failed, will reconnect container (keeping client): %s",
                        health_error,
                    )
                    # Only clear the container reference; keep cosmos_client alive
                    # to avoid expensive full-client recreation on transient errors.
                    self.cosmos_container = None

            if not config.COSMOS_ENDPOINT:
                raise RuntimeError("AZURE_COSMOS_ENDPOINT is not set")

            if self.cosmos_client is None:
                self.cosmos_client = CosmosClient(
                    config.COSMOS_ENDPOINT,
                    credential=config.COSMOS_KEY if config.COSMOS_KEY else self.credential,
                )

            db = await self.cosmos_client.create_database_if_not_exists(id=config.COSMOS_DB)

            # Prefer fetching the existing container (Terraform-managed) to avoid
            # BadRequest when create_container_if_not_exists sends a vector-
            # embedding policy that conflicts with the already-created container.
            try:
                self.cosmos_container = db.get_container_client(config.COSMOS_CONTAINER)
                await self.cosmos_container.read()  # verify it exists
                self._cosmos_last_health_check = _time.monotonic()
                logger.info("Cosmos container '%s' found (existing).", config.COSMOS_CONTAINER)
            except Exception:
                # Container doesn't exist yet – create with full vector config
                logger.info("Cosmos container '%s' not found, creating with vector policy.", config.COSMOS_CONTAINER)
                vector_embedding_policy = {
                    "vectorEmbeddings": [
                        {
                            "path": "/vector",
                            "dataType": "float32",
                            "distanceFunction": "cosine",
                            "dimensions": 1536
                        }
                    ]
                }
                indexing_policy = {
                    "indexingMode": "consistent",
                    "automatic": True,
                    "includedPaths": [{"path": "/*"}],
                    "excludedPaths": [{"path": "/_etag/?"}, {"path": "/vector/*"}],
                    "vectorIndexes": [{"path": "/vector", "type": "quantizedFlat"}]
                }
                self.cosmos_container = await db.create_container_if_not_exists(
                    id=config.COSMOS_CONTAINER,
                    partition_key=PartitionKey(path="/id"),
                    vector_embedding_policy=vector_embedding_policy,
                    indexing_policy=indexing_policy
                )
                self._cosmos_last_health_check = _time.monotonic()

    async def ensure_rag_containers(self):
        """
        Initializes the specialized containers for RAG:
        1. Chat History: Stores conversation turns.
        2. Vector Cache: Stores semantic cache of questions/answers to save tokens.
        """
        if self.cosmos_chat_container is not None and self.cosmos_cache_container is not None:
            return

        if not config.COSMOS_ENDPOINT:
            raise RuntimeError("AZURE_COSMOS_ENDPOINT is not set")

        async with self._cosmos_init_lock:
            # Re-check inside lock
            if self.cosmos_chat_container is not None and self.cosmos_cache_container is not None:
                return

            if self.cosmos_client is None:
                self.cosmos_client = CosmosClient(
                    config.COSMOS_ENDPOINT,
                    credential=config.COSMOS_KEY if config.COSMOS_KEY else self.credential,
                )

            db = await self.cosmos_client.create_database_if_not_exists(id=config.COSMOS_DB)

            # 1. Chat History Container (Partition by /id or /sessionId)
            # We use /id similar to the tutorial for simplicity, or /sessionId if we have explicit sessions.
            # Tutorial uses /id.
            self.cosmos_chat_container = await db.create_container_if_not_exists(
                id=config.COSMOS_CHAT_CONTAINER,
                partition_key=PartitionKey(path="/id")
            )

            # 2. Vector Cache Container
            # Needs Vector Policy matching the embedding model (text-embedding-3-small = 1536 dims)
            vector_embedding_policy = {
                "vectorEmbeddings": [
                    {
                        "path": "/vector",
                        "dataType": "float32",
                        "distanceFunction": "cosine",
                        "dimensions": 1536
                    }
                ]
            }

            # Indexing policy: Exclude vectors from standard index, include them in vector index
            indexing_policy = {
                "indexingMode": "consistent",
                "automatic": True,
                "includedPaths": [{"path": "/*"}],
                "excludedPaths": [{"path": "/_etag/?"}, {"path": "/vector/*"}],
                "vectorIndexes": [{"path": "/vector", "type": "quantizedFlat"}]
            }

            self.cosmos_cache_container = await db.create_container_if_not_exists(
                id=config.COSMOS_CACHE_CONTAINER,
                partition_key=PartitionKey(path="/id"),
                vector_embedding_policy=vector_embedding_policy,
                indexing_policy=indexing_policy,
                # Cache can benefit from TTL (Time To Live) to auto-expire old entries if desired.
                # Here we default to -1 (no expiry) but enable the capability.
                default_ttl=-1
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


def get_sb_admin_client(clients: Clients = Depends(get_clients)) -> ServiceBusAdministrationClient:
    """Synchronous admin client for stats/management."""
    if not clients.sb_admin_client:
        if config.SERVICE_BUS_FQDN:
            clients.sb_admin_client = ServiceBusAdministrationClient(
                fully_qualified_namespace=config.SERVICE_BUS_FQDN,
                credential=clients.credential
            )
        elif os.getenv("AZURE_SERVICE_BUS_CONNECTION_STRING"):
             clients.sb_admin_client = ServiceBusAdministrationClient.from_connection_string(
                 os.getenv("AZURE_SERVICE_BUS_CONNECTION_STRING")
             )
        else:
             raise RuntimeError("Cannot initialize SB Admin Client")

    return clients.sb_admin_client


async def get_queue_active_count(queue_name: str, clients: Clients | None = None) -> int:
    clients = clients or get_default_clients()
    try:
        admin_client = get_sb_admin_client(clients)
        # ServiceBusAdministrationClient is synchronous. Run in thread to avoid blocking loop.
        def _get_count():
            props = admin_client.get_queue_runtime_properties(queue_name)
            return props.active_message_count

        return await asyncio.to_thread(_get_count)
    except Exception as e:
        logger.warning(f"Failed to get queue active count: {e}")
        return 0


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
                detail=f"Database unavailable: {str(e)}. Ensure Cosmos DB is provisioned and identity has correct roles (Data Contributor/Custom Role). Check Firewall if IP is blocked.",
            )
        raise


def get_concurrency_limit(clients: Clients = Depends(get_clients)) -> asyncio.Semaphore:
    return clients.concurrency_limit


async def auth_headers(clients: Clients | None = None, model_type: str = "openai") -> dict:
    # Consistency with ChatAgent: Use API Key if configured (e.g. invalid managed identity context)
    api_key = getattr(config, "AI_API_KEY", None)
    if api_key:
        if model_type == "mistral":
            # Per user script: Mistral on Azure MaaS often expects Authorization: Bearer {key}
            return {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }
        return {
            "Content-Type": "application/json",
            "api-key": api_key
        }

    clients = clients or get_default_clients()
    token = await clients.credential.get_token(config.AI_SCOPE)
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token.token}"
    }


def blob_id_from_url(blob_url: str) -> str:
    parsed = urlparse(blob_url)
    # Cosmos DB IDs cannot contain '/', so we replace with '-'
    # e.g., pdf-inputs/doc.pdf -> pdf-inputs-doc.pdf
    return parsed.path.lstrip("/").replace("/", "-")


async def download_blob_as_base64(blob_url: str, return_bytes: bool = False, clients: Clients | None = None) -> str | tuple[str, bytes]:
    clients = clients or get_default_clients()
    try:
        blob_client = BlobClient.from_blob_url(blob_url, credential=clients.credential)
        parsed = urlparse(blob_url)
        container = parsed.path.lstrip('/').split('/')[0] if parsed.path else ''
        blob_name = '/'.join(parsed.path.lstrip('/').split('/')[1:]) if parsed.path else ''
        stream = await blob_client.download_blob()
        data = await stream.readall()
        if not data.startswith(b"%PDF"):
            raise ValueError("Corrupted PDF: missing PDF header")
    except Exception as ex:
        logger.error(f"download_blob_as_base64 failed: {blob_url} container={container} blob={blob_name} :: {ex}")
        raise

    import base64

    b64 = base64.b64encode(data).decode()
    return (b64, data) if return_bytes else b64


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

    async def _check_ai(timeout_s: float = 5.0) -> None:
        async def _inner():
            # Token acquisition is already covered by credential check, but AI endpoint availability is not.
            # We perform a lightweight HEAD request to the AI endpoint if available.
            if not config.MISTRAL_ENDPOINT and not config.PHI_ENDPOINT:
                return
            import httpx

            endpoint = config.MISTRAL_ENDPOINT or config.PHI_ENDPOINT
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                resp = await client.get(endpoint, timeout=timeout_s)
                resp.raise_for_status()

        await asyncio.wait_for(_inner(), timeout=timeout_s)

    async def _check_storage_public(timeout_s: float = 3.0) -> None:
        async def _inner():
            # Check if public access is configured for the container
            # This requires either:
            # 1. Container public access level set to "Container" or "Blob"
            # 2. Or use authenticated client with "Storage Blob Data Reader" role
            #
            # Try authenticated access first (more reliable in production)
            if clients.blob_service_client:
                container_client = clients.blob_service_client.get_container_client(config.BLOB_CONTAINER_INPUT)
                # Check if container exists and is accessible
                await container_client.get_container_properties()
                return
            else:
                # Fallback: try anonymous access (requires public container)
                from azure.storage.blob.aio import ContainerClient
                url = f"{config.BLOB_ACCOUNT_URL}/{config.BLOB_CONTAINER_INPUT}".replace("//", "/").replace("https:/", "https://")
                async with ContainerClient.from_container_url(url) as cc:
                    await cc.get_container_properties()

        await asyncio.wait_for(_inner(), timeout=timeout_s)

    checks = {
        "credential": _check_credential(),
        "servicebus": _check_servicebus(),
        "storage": _check_storage(),
        "storage_public": _check_storage_public(),
        "cosmos": _check_cosmos(),
        "ai": _check_ai(),
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
