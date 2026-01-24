"""
FastAPI Backend for email classification pipeline.

Features:
- Webhook ingestion from Event Grid -> enqueue to Service Bus.
- Background worker pulls Service Bus, OCR via Mistral (MaaS) and classify via Phi-4 (MaaS).
- Cosmos DB storage with status, score, markdown, and blob URL.
- REST API for listing, searching, and validating items.
- CSV export helper to merge results.
"""

import asyncio
import base64
import json
import os
import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from urllib.parse import urlparse

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace import Status, StatusCode
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from fastapi import Body, FastAPI, HTTPException, Query, Request, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from azure.identity.aio import DefaultAzureCredential
from azure.servicebus.aio import ServiceBusClient
from azure.servicebus import ServiceBusMessage
from azure.storage.blob.aio import BlobClient, BlobServiceClient
from azure.storage.blob import generate_blob_sas, BlobSasPermissions
from azure.cosmos.aio import CosmosClient
from azure.cosmos import PartitionKey

# ---------------------------------------------------------------------------
# Configuration via env vars
# ---------------------------------------------------------------------------
SERVICE_BUS_FQDN = os.getenv("AZURE_SERVICE_BUS_FQDN")  # e.g., myns.servicebus.windows.net
SERVICE_BUS_QUEUE = os.getenv("AZURE_SERVICE_BUS_QUEUE", "pdf-processing-queue")
BLOB_ACCOUNT_URL = os.getenv("AZURE_STORAGE_ACCOUNT_URL")  # https://account.blob.core.windows.net
BLOB_CONTAINER_INPUT = os.getenv("AZURE_STORAGE_CONTAINER", "pdf-inputs")
COSMOS_ENDPOINT = os.getenv("AZURE_COSMOS_ENDPOINT")
COSMOS_KEY = os.getenv("AZURE_COSMOS_KEY")  # optional if using MSI
COSMOS_DB = os.getenv("AZURE_COSMOS_DB", "emailsdb")
COSMOS_CONTAINER = os.getenv("AZURE_COSMOS_CONTAINER", "emails")

# AI endpoints
MISTRAL_ENDPOINT = os.getenv("MISTRAL_ENDPOINT")  # https://...azure.net
MISTRAL_MODE = os.getenv("MISTRAL_MODE", "maas")  # maas|inference
MISTRAL_DEPLOYMENT = os.getenv("MISTRAL_DEPLOYMENT", "mistral-ocr-2505")
PHI_ENDPOINT = os.getenv("PHI_ENDPOINT") or os.getenv("AZURE_AI_ENDPOINT")
PHI_DEPLOYMENT = os.getenv("PHI_DEPLOYMENT", "phi-4")
AI_API_VERSION = os.getenv("AZURE_AI_API_VERSION", "2024-08-01-preview")
AI_SCOPE = os.getenv("AZURE_AI_SCOPE", "https://cognitiveservices.azure.com/.default")

PHI4_COST_PER_1K_INPUT = float(os.getenv("PHI4_COST_PER_1K_INPUT", "0.000107"))
PHI4_COST_PER_1K_OUTPUT = float(os.getenv("PHI4_COST_PER_1K_OUTPUT", "0.00043"))
MISTRAL_OCR_COST_PER_1K_PAGES = float(os.getenv("MISTRAL_OCR_COST_PER_1K_PAGES", "1.0"))  # $1 per 1K pages (approx)

CONCURRENCY_LIMIT = asyncio.Semaphore(5)
credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
tracer = trace.get_tracer(__name__)

app = FastAPI()
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")
app.state.cost_overrides = {}

# Globals initialized at startup
sb_client: ServiceBusClient | None = None
cosmos_client: CosmosClient | None = None
cosmos_container = None
blob_service_client: BlobServiceClient | None = None


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class ClassificationIntent(BaseModel):
    intent: str
    confidence: float
    justification: Optional[str] = None


class ClassificationResult(BaseModel):
    detected_intents: List[ClassificationIntent]
    global_complexity: Optional[str] = None
    needs_review: bool = False
    raw_response: Optional[dict] = None


class EmailRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    file_url: str
    status: str
    markdown: Optional[str] = None
    classification: Optional[ClassificationResult] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error: Optional[str] = None
    usage: Optional[dict] = None


class EmailListResponse(BaseModel):
    items: List[EmailRecord]
    total: int
    review_required: int
    processed: int
    continuation_token: Optional[str] = None


# ---------------------------------------------------------------------------
# Startup / Shutdown
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def on_startup():
    global sb_client, cosmos_client, cosmos_container, blob_service_client
    if not trace.get_tracer_provider() or isinstance(trace.get_tracer_provider(), trace.NoOpTracerProvider):
        provider = TracerProvider(resource=Resource.create({"service.name": "classificationg2s-api"}))
        otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        if otlp_endpoint:
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app)
        HTTPXClientInstrumentor().instrument()

    sb_client = ServiceBusClient(fully_qualified_namespace=SERVICE_BUS_FQDN, credential=credential)
    blob_service_client = BlobServiceClient(account_url=BLOB_ACCOUNT_URL, credential=credential)
    cosmos_client = CosmosClient(COSMOS_ENDPOINT, credential=credential if not COSMOS_KEY else None, key=COSMOS_KEY)
    db = await cosmos_client.create_database_if_not_exists(id=COSMOS_DB)
    cosmos_container = await db.create_container_if_not_exists(id=COSMOS_CONTAINER, partition_key=PartitionKey(path="/id"))
    # Start worker
    app.state.worker_task = asyncio.create_task(worker_loop())


@app.on_event("shutdown")
async def on_shutdown():
    if task := getattr(app.state, "worker_task", None):
        task.cancel()
    if sb_client:
        await sb_client.close()
    if cosmos_client:
        await cosmos_client.close()
    if blob_service_client:
        await blob_service_client.close()


# ---------------------------------------------------------------------------
# Webhook Ingestion (Event Grid)
# ---------------------------------------------------------------------------
@app.post("/webhook/ingest")
async def webhook_ingest(events: list = Body(...)):
    # Handle Event Grid validation
    for ev in events:
        if ev.get("eventType") == "Microsoft.EventGrid.SubscriptionValidationEvent":
            return {"validationResponse": ev["data"]["validationCode"]}

    # Enqueue blob created events
    async with sb_client:
        sender = sb_client.get_queue_sender(queue_name=SERVICE_BUS_QUEUE)
        async with sender:
            for ev in events:
                if ev.get("eventType") == "Microsoft.Storage.BlobCreated":
                    blob_url = ev.get("data", {}).get("url")
                    if not blob_url:
                        continue
                    msg = ServiceBusMessage(json.dumps({"blob_url": blob_url}))
                    await sender.send_messages(msg)
    return {"status": "enqueued", "count": len(events)}


# ---------------------------------------------------------------------------
# Worker Loop
# ---------------------------------------------------------------------------
async def worker_loop():
    while True:
        try:
            async with sb_client.get_queue_receiver(queue_name=SERVICE_BUS_QUEUE, max_wait_time=5) as receiver:
                async for msg in receiver:
                    async with CONCURRENCY_LIMIT:
                        await handle_queue_message(receiver, msg)
        except asyncio.CancelledError:
            break
        except Exception as ex:
            print(f"[worker] Error: {ex}")
            await asyncio.sleep(2)


async def handle_queue_message(receiver, msg):
    body_bytes = b"".join([b for b in msg.body])
    try:
        payload = json.loads(body_bytes.decode())
    except Exception:
        payload = {"blob_url": None, "raw": body_bytes.decode(errors="ignore")}

    blob_url = payload.get("blob_url")
    if not blob_url:
        await receiver.dead_letter_message(msg, reason="No blob_url in message")
        return

    try:
        result = await run_classification_pipeline(blob_url)
        await save_to_cosmos(result)
        await receiver.complete_message(msg)
    except OCRFailed as ex:
        print(f"[worker] OCR failed for {blob_url}: {ex}")
        await receiver.dead_letter_message(msg, reason="OCRFailed", error_description=str(ex))
    except Exception as ex:
        print(f"[worker] Processing failed for {blob_url}: {ex}")
        await receiver.abandon_message(msg)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
async def run_classification_pipeline(blob_url: str) -> EmailRecord:
    pdf_b64, pdf_bytes = await download_blob_as_base64(blob_url, return_bytes=True)
    ocr_result = await ocr_with_mistral(pdf_b64)
    markdown = ocr_result.get("markdown")
    classification_raw = await classify_with_phi4(markdown)
    processed = process_agent_response(classification_raw)
    status = "REVIEW_REQUIRED" if processed.get("needs_review") else "PROCESSED"
    # Truncate markdown to avoid large docs in Cosmos
    markdown_trunc = markdown[:30000] if markdown else None
    mistral_usage = ocr_result.get("usage") or {}
    pages = mistral_usage.get("pages_processed") or mistral_usage.get("pages") or estimate_pdf_pages(pdf_bytes)
    usage = {
        "phi4": classification_raw.get("usage") if isinstance(classification_raw, dict) else None,
        "phi4_cost_usd": compute_cost_phi4(classification_raw.get("usage") if isinstance(classification_raw, dict) else None),
        "mistral": {
            "estimated_pages": pages,
            "cost_usd": compute_cost_mistral(pages),
        },
    }

    return EmailRecord(
        id=blob_id_from_url(blob_url),
        file_url=blob_url,
        markdown=markdown_trunc,
        classification=ClassificationResult(**{
            "detected_intents": processed.get("intents", []),
            "global_complexity": processed.get("raw_response", {}).get("global_complexity") if processed.get("raw_response") else None,
            "needs_review": processed.get("needs_review", False),
            "raw_response": processed.get("raw_response"),
        }),
        status=status,
        usage=usage,
    )


def estimate_pdf_pages(pdf_bytes: bytes) -> int:
    try:
        return max(pdf_bytes.count(b"/Type /Page"), 1)
    except Exception:
        return 1


def compute_cost_phi4(usage: Optional[dict]) -> Optional[float]:
    if not usage:
        return None
    prompt = usage.get("prompt_tokens") or usage.get("input_tokens") or usage.get("inputTokens") or 0
    completion = usage.get("completion_tokens") or usage.get("output_tokens") or usage.get("outputTokens") or 0
    total = prompt + completion
    overrides = getattr(app.state, "cost_overrides", {}) if hasattr(app, "state") else {}
    cin = overrides.get("phi4_input_per_1k", PHI4_COST_PER_1K_INPUT)
    cout = overrides.get("phi4_output_per_1k", PHI4_COST_PER_1K_OUTPUT)
    return (prompt / 1000.0) * cin + (completion / 1000.0) * cout


def compute_cost_mistral(pages: int) -> float:
    overrides = getattr(app.state, "cost_overrides", {}) if hasattr(app, "state") else {}
    cost_per_1k_pages = overrides.get("mistral_per_1k_pages", MISTRAL_OCR_COST_PER_1K_PAGES)
    return (pages / 1000.0) * cost_per_1k_pages


async def download_blob_as_base64(blob_url: str, return_bytes: bool = False) -> str | tuple[str, bytes]:
    blob_client = BlobClient.from_blob_url(blob_url, credential=credential)
    stream = await blob_client.download_blob()
    data = await stream.readall()
    if not data.startswith(b"%PDF"):
        raise ValueError("Corrupted PDF: missing PDF header")
    b64 = base64.b64encode(data).decode()
    return (b64, data) if return_bytes else b64


async def auth_headers() -> dict:
    token = await credential.get_token(AI_SCOPE)
    return {"Authorization": f"Bearer {token.token}"}


class OCRFailed(Exception):
    pass


def _retryable_httpx(exc: Exception) -> bool:
    return isinstance(exc, httpx.HTTPStatusError) and exc.response is not None and exc.response.status_code in (429, 500, 502, 503, 504)


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=1, max=10), retry=retry_if_exception(_retryable_httpx))
async def ocr_with_mistral(base64_pdf: str) -> dict:
    """Call Mistral OCR (MaaS) to extract markdown from PDF (document_base64)."""
    headers = await auth_headers()
    payload = {
        "model": MISTRAL_DEPLOYMENT,
        "document": {
            "type": "document_base64",
            "document_base64": base64_pdf,
        }
    }
    if MISTRAL_MODE.lower() == "maas":
        url = f"{MISTRAL_ENDPOINT}/v1/ocr"
    else:
        url = f"{MISTRAL_ENDPOINT}/models/{MISTRAL_DEPLOYMENT}:ocr"
    with tracer.start_as_current_span("mistral_ocr") as span:
        span.set_attribute("gen_ai.system", "mistral")
        span.set_attribute("gen_ai.operation", "ocr")
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=payload, headers=headers)
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as ex:
                span.set_status(Status(StatusCode.ERROR))
                span.record_exception(ex)
                raise
            data = resp.json()
            usage_info = data.get("usage_info") or {}
            pages = usage_info.get("pages_processed") or usage_info.get("pages") or 0
            span.set_attribute("gen_ai.usage.pages_processed", pages)
            content = data.get("markdown") or data.get("content")
            if not content and data.get("pages"):
                content = "\n\n".join([p.get("markdown", "") for p in data.get("pages", [])])
            if not content:
                raise OCRFailed("Empty OCR content")
            return {"markdown": content, "usage": usage_info}


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=1, max=10), retry=retry_if_exception(_retryable_httpx))
async def classify_with_phi4(text_markdown: str) -> dict:
    headers = await auth_headers()
    system_prompt = """ 
Tu es un assistant expert en classification d'emails d'assurance.
Ta tâche est d'analyser le contenu de l'email (fourni en markdown) et d'identifier TOUTES les intentions présentes.

LISTE DES INTENTIONS POSSIBLES :
1. Attestation habitation
2. Attestation scolaire
3. Relevé de compte
4. Dommages électriques
5. Événements naturels

RÈGLES DE CLASSIFICATION :
- Un email peut contenir PLUSIEURS intentions.
- Si aucune intention ne correspond, retourne une liste vide.
- Assigne un score de confiance (0.0 à 1.0) pour CHAQUE intention détectée.

FORMAT DE RÉPONSE ATTENDU (JSON UNIQUEMENT) :
{
    "detected_intents": [
        {
            "intent": "Nom de l'intention",
            "confidence": 0.95,
            "justification": "Court extrait du texte justifiant ce choix"
        }
    ],
    "global_complexity": "Simple|Complexe"
}
"""
    payload = {
        "model": PHI_DEPLOYMENT,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text_markdown[:30000]},
        ],
        "temperature": 0.1,
    }
    url = f"{PHI_ENDPOINT}/openai/deployments/{PHI_DEPLOYMENT}/chat/completions?api-version={AI_API_VERSION}" 
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
        usage = data.get("usage", {})
        span.set_attribute("gen_ai.usage.input_tokens", usage.get("prompt_tokens", 0))
        span.set_attribute("gen_ai.usage.output_tokens", usage.get("completion_tokens", 0))
        span.set_attribute("gen_ai.usage.total_tokens", usage.get("total_tokens", 0))
        payload_dict = json.loads(content)
        payload_dict["usage"] = usage
        return payload_dict


def process_agent_response(agent_response: dict) -> dict:
    """Process multi-intent response and decide if review is needed."""
    import logging
    try:
        data = agent_response if isinstance(agent_response, dict) else json.loads(agent_response)
        intents = data.get("detected_intents", [])
        needs_review = False
        if not intents:
            needs_review = True
        for item in intents:
            if item.get('confidence', 0) < 0.9:
                needs_review = True
                break
        if len(intents) > 3:
            needs_review = True
        return {
            "intents": intents,
            "needs_review": needs_review,
            "raw_response": data,
        }
    except json.JSONDecodeError:
        logging.error("Agent returned invalid JSON")
        return {"needs_review": True, "error": "Invalid JSON"}


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
async def save_to_cosmos(record: EmailRecord):
    record.updated_at = datetime.now(timezone.utc)
    await cosmos_container.upsert_item(record.model_dump())


def blob_id_from_url(blob_url: str) -> str:
    parsed = urlparse(blob_url)
    # ID = "<container>/<blob-path>" for easy lookup in Storage
    return parsed.path.lstrip("/")


async def build_sas_url(blob_url: str, expiry_minutes: int = 60) -> Optional[str]:
    # If account key provided, generate SAS; otherwise return original URL
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


# ---------------------------------------------------------------------------
# APIs
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index():
    path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    with open(path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/api/emails", response_model=EmailListResponse)
async def list_emails(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str = Query("all", regex="^(all|REVIEW_REQUIRED|PROCESSED)$"),
    search: Optional[str] = Query(None),
    continuation_token: Optional[str] = Query(None),
):
    filters = []
    params = {}
    if status != "all":
        filters.append("c.status = @status")
        params["@status"] = status
    if search:
        filters.append("CONTAINS(c.markdown, @search)")
        params["@search"] = search
    where = " AND ".join(filters)
    query = "SELECT * FROM c"
    if where:
        query += f" WHERE {where}"
    query += " ORDER BY c._ts DESC"
    # OFFSET / LIMIT for simple paging (non-optimal for very large datasets)
    offset = (page - 1) * page_size
    query += " OFFSET @offset LIMIT @limit"
    params["@offset"] = offset
    params["@limit"] = page_size
    items_iter = cosmos_container.query_items(query, parameters=[{"name": k, "value": v} for k, v in params.items()], enable_cross_partition_query=True)
    items = [EmailRecord(**item) async for item in items_iter]
    next_token = None

    # stats
    processed_count = await count_by_status("PROCESSED")
    review_count = await count_by_status("REVIEW_REQUIRED")
    total = processed_count + review_count
    return EmailListResponse(items=items, total=total, review_required=review_count, processed=processed_count, continuation_token=next_token)


async def count_by_status(status: str) -> int:
    query = "SELECT VALUE COUNT(1) FROM c WHERE c.status=@status"
    it = cosmos_container.query_items(query, parameters=[{"name": "@status", "value": status}], enable_cross_partition_query=True)
    async for v in it:
        return v
    return 0


@app.get("/api/stats")
async def get_stats():
    processed_count = await count_by_status("PROCESSED")
    review_count = await count_by_status("REVIEW_REQUIRED")
    total = processed_count + review_count
    return {
        "processed": processed_count,
        "review_required": review_count,
        "total": total,
        "progress": (processed_count / total) if total else 0,
    }


@app.get("/api/settings")
async def get_settings():
    return getattr(app.state, "cost_overrides", {})


@app.post("/api/settings")
async def set_settings(payload: dict):
    # Accept overrides: phi4_input_per_1k, phi4_output_per_1k, mistral_per_1k_pages
    app.state.cost_overrides = payload or {}
    return app.state.cost_overrides


@app.get("/api/emails/{item_id}", response_model=EmailRecord)
async def get_email(item_id: str):
    try:
        item = await cosmos_container.read_item(item=item_id, partition_key=item_id)
        sas_url = await build_sas_url(item.get("file_url"))
        if sas_url:
            item["file_url_sas"] = sas_url
        return EmailRecord(**item)
    except Exception:
        raise HTTPException(status_code=404, detail="Not found")


@app.patch("/api/emails/{item_id}", response_model=EmailRecord)
async def patch_email(item_id: str, payload: dict):
    try:
        item = await cosmos_container.read_item(item=item_id, partition_key=item_id)
        if intents := payload.get("intents"):
            item["classification"] = {
                "detected_intents": intents,
                "needs_review": False,
            }
            item["status"] = "PROCESSED"
            item["updated_at"] = datetime.now(timezone.utc).isoformat()
        await cosmos_container.upsert_item(item)
        return EmailRecord(**item)
    @app.post("/api/emails/{item_id}/reprocess")
    async def reprocess_email(item_id: str):
        """Re-enqueue a single email for classification."""
        try:
            item = await cosmos_container.read_item(item=item_id, partition_key=item_id)
            blob_url = item.get("file_url")
            if not blob_url:
                raise HTTPException(status_code=400, detail="file_url missing")
            async with sb_client:
                sender = sb_client.get_queue_sender(queue_name=SERVICE_BUS_QUEUE)
                async with sender:
                    await sender.send_messages(ServiceBusMessage(json.dumps({"blob_url": blob_url})))
            return {"status": "enqueued", "blob_url": blob_url}
        except Exception as ex:
            raise HTTPException(status_code=400, detail=str(ex))
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex))


# ---------------------------------------------------------------------------
# Upload endpoint (POC batch upload via UI)
# ---------------------------------------------------------------------------

MAX_UPLOAD_SIZE = int(os.getenv("UPLOAD_MAX_BYTES", 10 * 1024 * 1024))  # 10MB


@app.post("/api/upload")
async def upload_pdfs(files: list[UploadFile] = File(...)):
    if len(files) > 10:
        raise HTTPException(status_code=400, detail="Max 10 fichiers")
    today = datetime.now(timezone.utc).strftime("%Y/%m/%d")
    container = BLOB_CONTAINER_INPUT
    results = []
    container_client = blob_service_client.get_container_client(container)
    try:
        await container_client.create_container()
    except Exception:
        pass
    for f in files:
        status = "uploaded"
        error = None
        if not f.filename.lower().endswith(".pdf") or f.content_type not in ("application/pdf", "application/octet-stream"):
            status, error = "error", "invalid_type"
        else:
            f.file.seek(0, 2)
            size = f.file.tell()
            f.file.seek(0)
            if size > MAX_UPLOAD_SIZE:
                status, error = "error", "too_large"
        if status == "error":
            results.append({"name": f.filename, "status": status, "error": error})
            continue
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", f.filename)
        safe_name = safe_name[-120:]  # avoid excessively long names
        unique_name = f"{uuid.uuid4()}-{safe_name}"
        blob_name = f"uploads/{today}/{unique_name}"
        blob_client = container_client.get_blob_client(blob_name)
        await blob_client.upload_blob(f.file, overwrite=True, content_type="application/pdf")
        results.append({"name": f.filename, "status": status, "blob_url": blob_client.url})
    return {"results": results, "count": len([r for r in results if r["status"] == "uploaded"])}


# ---------------------------------------------------------------------------
# CSV Export Helper
# ---------------------------------------------------------------------------
async def export_cosmos_to_csv(path: str = "./data/output.csv"):
    import csv

    query = "SELECT c.id, c.file_url, c.status, c.confidence, c.classification, c.markdown FROM c"
    it = cosmos_container.query_items(query, enable_cross_partition_query=True)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "file_url", "status", "intents", "needs_review", "global_complexity", "phi4_cost_usd", "mistral_cost_usd"])
        async for item in it:
            classification = item.get("classification") or {}
            intents = classification.get("detected_intents") or []
            intents_str = "|".join([f"{i.get('intent')}:{i.get('confidence')}" for i in intents])
            writer.writerow([
                item.get("id"),
                item.get("file_url"),
                item.get("status"),
                intents_str,
                classification.get("needs_review", False),
                classification.get("global_complexity"),
                (item.get("usage") or {}).get("phi4_cost_usd"),
                (item.get("usage") or {}).get("mistral", {}).get("cost_usd") if isinstance((item.get("usage") or {}).get("mistral"), dict) else None,
            ])
    return path


@app.get("/api/emails/export")
async def export_emails_csv():
    """Stream CSV export to the client."""
    import csv
    import io

    async def row_iter():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["id", "file_url", "status", "intents", "needs_review", "global_complexity", "phi4_cost_usd", "mistral_cost_usd"])
        yield buffer.getvalue(); buffer.seek(0); buffer.truncate(0)
        query = "SELECT c.id, c.file_url, c.status, c.classification FROM c"
        it = cosmos_container.query_items(query, enable_cross_partition_query=True)
        async for item in it:
            classification = item.get("classification") or {}
            intents = classification.get("detected_intents") or []
            intents_str = "|".join([f"{i.get('intent')}:{i.get('confidence')}" for i in intents])
            writer.writerow([
                item.get("id"),
                item.get("file_url"),
                item.get("status"),
                intents_str,
                classification.get("needs_review", False),
                classification.get("global_complexity"),
                (item.get("usage") or {}).get("phi4_cost_usd"),
                (item.get("usage") or {}).get("mistral", {}).get("cost_usd") if isinstance((item.get("usage") or {}).get("mistral"), dict) else None,
            ])
            yield buffer.getvalue(); buffer.seek(0); buffer.truncate(0)

    return StreamingResponse(row_iter(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=emails.csv"})


if __name__ == "__main__":
    # Optional CLI: uvicorn main:app --reload
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--export-csv", help="Export Cosmos data to CSV at path", nargs="?")
    args = parser.parse_args()
    if args.export_csv:
        asyncio.run(export_cosmos_to_csv(args.export_csv))
    else:
        import uvicorn
        uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=True)