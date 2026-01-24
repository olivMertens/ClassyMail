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
import hashlib
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

# Fallback model (for long contexts / safety net).
# In Azure OpenAI compatible endpoints, the "model" field is the deployment name.
PHI_FALLBACK_ENDPOINT = os.getenv("PHI_FALLBACK_ENDPOINT") or PHI_ENDPOINT
PHI_FALLBACK_DEPLOYMENT = os.getenv("PHI_FALLBACK_DEPLOYMENT", "gpt-4o-mini")

# Anonymization model (used to create fine-tuning datasets without PII).
ANONYMIZER_ENDPOINT = os.getenv("ANONYMIZER_ENDPOINT") or PHI_ENDPOINT
ANONYMIZER_DEPLOYMENT = os.getenv("ANONYMIZER_DEPLOYMENT", "gpt-4o")
ANONYMIZER_API_VERSION = os.getenv("ANONYMIZER_API_VERSION", AI_API_VERSION)
ANONYMIZER_PROMPT_VERSION = os.getenv("ANONYMIZER_PROMPT_VERSION", "v1")
ANONYMIZER_MAX_TOKENS = int(os.getenv("ANONYMIZER_MAX_TOKENS", "6000"))

# Context sizing (best-effort). Adjust to match your deployments.
PHI_PRIMARY_MAX_INPUT_TOKENS = int(os.getenv("PHI_PRIMARY_MAX_INPUT_TOKENS", "8000"))
PHI_FALLBACK_MAX_INPUT_TOKENS = int(os.getenv("PHI_FALLBACK_MAX_INPUT_TOKENS", "120000"))
PHI_RESERVED_OUTPUT_TOKENS = int(os.getenv("PHI_RESERVED_OUTPUT_TOKENS", "1000"))

PHI4_COST_PER_1K_INPUT = float(os.getenv("PHI4_COST_PER_1K_INPUT", "0.000107"))
PHI4_COST_PER_1K_OUTPUT = float(os.getenv("PHI4_COST_PER_1K_OUTPUT", "0.00043"))
MISTRAL_OCR_COST_PER_1K_PAGES = float(os.getenv("MISTRAL_OCR_COST_PER_1K_PAGES", "1.0"))  # $1 per 1K pages (approx)

# Pricing for fallback model is tenant/region specific. Keep as config (default 0).
FALLBACK_COST_PER_1K_INPUT = float(os.getenv("FALLBACK_COST_PER_1K_INPUT", "0"))
FALLBACK_COST_PER_1K_OUTPUT = float(os.getenv("FALLBACK_COST_PER_1K_OUTPUT", "0"))

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


ANONYMIZER_SYSTEM_PROMPT = """### ROLE ###
You are an advanced Data Privacy and Anonymization Engine. Your purpose is to sanitize email content formatted in Markdown.

### OBJECTIVE ###
Rewrite the user's provided email content to remove all Personally Identifiable Information (PII) and sensitive contextual data, while STRICTLY preserving the original Markdown syntax, styling, and structure.

### ANONYMIZATION RULES (PII) ###
1. **Direct PII:** Replace all names, phone numbers, email addresses, IP addresses, and physical addresses with generic placeholders (e.g., `[Name]`, `[Phone]`, `[Email]`, `[Address]`).
2. **Contextual PII:** Generalize specific details that could indirectly identify a person or company (e.g., change "The project with Google" to "The project with [Client]"; change "My wife Sarah" to "My spouse").
3. **Dates:** Generalize specific dates to months or quarters unless the specific date is crucial for generic context (e.g., change "July 12th, 2024" to `[Date]` or "July 2024").
4. **Numbers:** Mask financial figures or sensitive metrics if they are specific enough to identify the transaction (e.g., "$1,234,550.00" -> `[Amount]`).

### MARKDOWN PRESERVATION RULES ###
1. **Structure:** Do NOT alter headers (`#`), lists (`-`, `1.`), blockquotes (`>`), or code blocks (```).
2. **Links:** - Preserve the Markdown link syntax `[text](url)`.
   - If the *text* contains PII, anonymize it: `[John's Profile]` -> `[[Name]'s Profile]`.
   - If the *URL* contains PII (e.g., `linkedin.com/in/johndoe`), replace the URL with a safe placeholder like `#` or `http://example.com/profile`.
   - NEVER remove the link syntax itself.
3. **Tables:** Keep all table rows and columns intact (`|`). Anonymize the content *inside* the cells, but do not break the alignment.

### OUTPUT FORMAT ###
Return ONLY the anonymized Markdown text. Do not add conversational filler like "Here is the anonymized version.""".strip()


def _basic_pii_scrub(text: str) -> str:
    """Cheap local scrubbing to reduce obvious PII before LLM anonymization.

    This does NOT guarantee full anonymization; the LLM step is the authoritative pass.
    """
    if not text:
        return text

    # Emails
    text = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[Email]", text)
    # IPv4
    text = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[IP]", text)
    # Phone-ish (very rough)
    text = re.sub(r"\b(?:\+?\d[\d\s().-]{7,}\d)\b", "[Phone]", text)
    # IBAN-ish
    text = re.sub(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b", "[IBAN]", text)
    return text


async def _ensure_cosmos_container():
    global cosmos_client, cosmos_container
    if cosmos_container is not None:
        return
    if not COSMOS_ENDPOINT:
        raise RuntimeError("AZURE_COSMOS_ENDPOINT is not set")
    cosmos_client = CosmosClient(COSMOS_ENDPOINT, credential=credential if not COSMOS_KEY else None, key=COSMOS_KEY)
    db = await cosmos_client.create_database_if_not_exists(id=COSMOS_DB)
    cosmos_container = await db.create_container_if_not_exists(id=COSMOS_CONTAINER, partition_key=PartitionKey(path="/id"))


async def anonymize_markdown_for_finetune(markdown: str) -> dict:
    """Anonymize Markdown using a model (default gpt-4o).

    Returns: {"anonymized_markdown": str, "usage": dict|None, "model": str}
    """
    if not ANONYMIZER_ENDPOINT:
        raise RuntimeError("ANONYMIZER_ENDPOINT is not set")

    headers = await auth_headers()
    user_content = _basic_pii_scrub(markdown or "")

    payload = {
        "model": ANONYMIZER_DEPLOYMENT,
        "messages": [
            {"role": "system", "content": ANONYMIZER_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0,
        "max_tokens": ANONYMIZER_MAX_TOKENS,
    }

    url = f"{ANONYMIZER_ENDPOINT}/openai/deployments/{ANONYMIZER_DEPLOYMENT}/chat/completions?api-version={ANONYMIZER_API_VERSION}"

    with tracer.start_as_current_span("anonymize_markdown") as span:
        span.set_attribute("gen_ai.system", "azure_openai")
        span.set_attribute("gen_ai.operation", "chat.completions")
        span.set_attribute("gen_ai.request.model", ANONYMIZER_DEPLOYMENT)
        span.set_attribute("app.anonymizer.prompt_version", ANONYMIZER_PROMPT_VERSION)

        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage = data.get("usage")
        if usage:
            span.set_attribute("gen_ai.usage.input_tokens", usage.get("prompt_tokens", 0))
            span.set_attribute("gen_ai.usage.output_tokens", usage.get("completion_tokens", 0))
            span.set_attribute("gen_ai.usage.total_tokens", usage.get("total_tokens", 0))

        return {
            "anonymized_markdown": content,
            "usage": usage,
            "model": ANONYMIZER_DEPLOYMENT,
            "prompt_version": ANONYMIZER_PROMPT_VERSION,
        }


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
    finetune_reviewed_ready: int = 0
    finetune_min_required: int = 50
    finetune_ready: bool = False
    continuation_token: Optional[str] = None


# ---------------------------------------------------------------------------
# Startup / Shutdown
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def on_startup():
    global sb_client, cosmos_client, cosmos_container, blob_service_client
    missing_env: list[str] = []
    if not SERVICE_BUS_FQDN:
        missing_env.append("AZURE_SERVICE_BUS_FQDN")
    if not BLOB_ACCOUNT_URL:
        missing_env.append("AZURE_STORAGE_ACCOUNT_URL")
    if not COSMOS_ENDPOINT:
        missing_env.append("AZURE_COSMOS_ENDPOINT")
    if not MISTRAL_ENDPOINT:
        missing_env.append("MISTRAL_ENDPOINT")
    if not PHI_ENDPOINT:
        missing_env.append("PHI_ENDPOINT (or AZURE_AI_ENDPOINT)")
    if missing_env:
        raise RuntimeError(
            "Missing required environment variables: "
            + ", ".join(missing_env)
            + ". Load secrets.env first (see docs/LOCAL_RUN.md)."
        )

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
    llm_usage = classification_raw.get("usage") if isinstance(classification_raw, dict) else None
    fallback_used = bool(classification_raw.get("fallback_used")) if isinstance(classification_raw, dict) else False
    llm_cost = compute_cost_llm(llm_usage, fallback_used=fallback_used)
    usage = {
        # Backward compatible keys (existing UI/exports expect "phi4")
        "phi4": llm_usage,
        "phi4_cost_usd": llm_cost,
        "phi4_model": classification_raw.get("model") if isinstance(classification_raw, dict) else PHI_DEPLOYMENT,
        "phi4_fallback_used": fallback_used,
        "phi4_context_truncated": bool(classification_raw.get("context_truncated")) if isinstance(classification_raw, dict) else False,
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


def compute_cost_llm(usage: Optional[dict], fallback_used: bool) -> Optional[float]:
    if not usage:
        return None
    prompt = usage.get("prompt_tokens") or usage.get("input_tokens") or usage.get("inputTokens") or 0
    completion = usage.get("completion_tokens") or usage.get("output_tokens") or usage.get("outputTokens") or 0
    overrides = getattr(app.state, "cost_overrides", {}) if hasattr(app, "state") else {}
    if fallback_used:
        cin = overrides.get("fallback_input_per_1k", FALLBACK_COST_PER_1K_INPUT)
        cout = overrides.get("fallback_output_per_1k", FALLBACK_COST_PER_1K_OUTPUT)
    else:
        cin = overrides.get("phi4_input_per_1k", PHI4_COST_PER_1K_INPUT)
        cout = overrides.get("phi4_output_per_1k", PHI4_COST_PER_1K_OUTPUT)
    return (prompt / 1000.0) * cin + (completion / 1000.0) * cout


def estimate_tokens_rough(text: str) -> int:
    # Best-effort heuristic: ~4 chars per token for Latin scripts.
    if not text:
        return 0
    return max(1, len(text) // 4)


def clamp_text_to_token_budget(text: str, max_tokens: int) -> tuple[str, bool]:
    if not text or max_tokens <= 0:
        return "", bool(text)
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


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
async def classify_with_phi4(text_markdown: str, *, force_fallback: bool = False) -> dict:
    if not PHI_ENDPOINT:
        raise RuntimeError("PHI_ENDPOINT is not set")
    if not PHI_FALLBACK_ENDPOINT:
        raise RuntimeError("PHI_FALLBACK_ENDPOINT is not set")

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

    system_tokens = estimate_tokens_rough(system_prompt)
    overhead_tokens = 200
    user_tokens_est = estimate_tokens_rough(text_markdown or "")

    max_user_primary = max(500, PHI_PRIMARY_MAX_INPUT_TOKENS - PHI_RESERVED_OUTPUT_TOKENS - system_tokens - overhead_tokens)
    max_user_fallback = max(500, PHI_FALLBACK_MAX_INPUT_TOKENS - PHI_RESERVED_OUTPUT_TOKENS - system_tokens - overhead_tokens)

    use_fallback = force_fallback or (user_tokens_est > max_user_primary)
    chosen_endpoint = PHI_FALLBACK_ENDPOINT if use_fallback else PHI_ENDPOINT
    chosen_deployment = PHI_FALLBACK_DEPLOYMENT if use_fallback else PHI_DEPLOYMENT
    user_budget = max_user_fallback if use_fallback else max_user_primary
    user_content, truncated = clamp_text_to_token_budget(text_markdown or "", user_budget)

    payload = {
        "model": chosen_deployment,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.1,
        "max_tokens": PHI_RESERVED_OUTPUT_TOKENS,
    }
    url = f"{chosen_endpoint}/openai/deployments/{chosen_deployment}/chat/completions?api-version={AI_API_VERSION}"

    with tracer.start_as_current_span("phi4_classify") as span:
        span.set_attribute("gen_ai.system", "azure_openai")
        span.set_attribute("gen_ai.operation", "chat.completions")
        span.set_attribute("gen_ai.request.model", chosen_deployment)
        span.set_attribute("app.fallback_used", bool(use_fallback))
        span.set_attribute("app.context_truncated", bool(truncated))
        span.set_attribute("app.estimated.user_tokens", int(user_tokens_est))
        span.set_attribute("app.user_budget_tokens", int(user_budget))

        async with httpx.AsyncClient(timeout=60) as client:
            try:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
            except httpx.HTTPStatusError as ex:
                status = ex.response.status_code if ex.response is not None else None
                body = ex.response.text if ex.response is not None else ""
                # If the primary fails due to size/context, try once with fallback.
                if (not use_fallback) and status in (400, 413) and ("context" in body.lower() or "token" in body.lower() or "length" in body.lower()):
                    return await classify_with_phi4(text_markdown, force_fallback=True)
                raise

            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
            usage = data.get("usage", {})
            span.set_attribute("gen_ai.usage.input_tokens", usage.get("prompt_tokens", 0))
            span.set_attribute("gen_ai.usage.output_tokens", usage.get("completion_tokens", 0))
            span.set_attribute("gen_ai.usage.total_tokens", usage.get("total_tokens", 0))

            payload_dict = json.loads(content)
            payload_dict["usage"] = usage
            payload_dict["model"] = chosen_deployment
            payload_dict["fallback_used"] = bool(use_fallback)
            payload_dict["context_truncated"] = bool(truncated)
            payload_dict["estimated_user_tokens"] = int(user_tokens_est)
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
    finetune_min_required = int(os.getenv("FINETUNE_MIN_EXAMPLES", "50"))
    finetune_reviewed_ready = await count_reviewed_ready_items()
    return EmailListResponse(
        items=items,
        total=total,
        review_required=review_count,
        processed=processed_count,
        finetune_reviewed_ready=finetune_reviewed_ready,
        finetune_min_required=finetune_min_required,
        finetune_ready=finetune_reviewed_ready >= finetune_min_required,
        continuation_token=next_token,
    )


async def count_by_status(status: str) -> int:
    query = "SELECT VALUE COUNT(1) FROM c WHERE c.status=@status"
    it = cosmos_container.query_items(query, parameters=[{"name": "@status", "value": status}], enable_cross_partition_query=True)
    async for v in it:
        return v
    return 0


async def count_reviewed_ready_items() -> int:
    """Count items eligible for fine-tuning export.

    Eligibility rules match the exporter defaults:
    - PROCESSED
    - classification.needs_review = false
    - reviewed = true
    - detected_intents is non-empty
    """
    query = (
        "SELECT VALUE COUNT(1) FROM c "
        "WHERE c.status='PROCESSED' "
        "AND IS_DEFINED(c.classification) "
        "AND c.classification.needs_review = false "
        "AND (IS_DEFINED(c.reviewed) AND c.reviewed = true) "
        "AND IS_DEFINED(c.classification.detected_intents) "
        "AND ARRAY_LENGTH(c.classification.detected_intents) > 0"
    )
    it = cosmos_container.query_items(query, enable_cross_partition_query=True)
    async for v in it:
        return v
    return 0


@app.get("/api/stats")
async def get_stats():
    processed_count = await count_by_status("PROCESSED")
    review_count = await count_by_status("REVIEW_REQUIRED")
    total = processed_count + review_count
    finetune_min_required = int(os.getenv("FINETUNE_MIN_EXAMPLES", "50"))
    finetune_reviewed_ready = await count_reviewed_ready_items()
    return {
        "processed": processed_count,
        "review_required": review_count,
        "total": total,
        "progress": (processed_count / total) if total else 0,
        "finetune_reviewed_ready": finetune_reviewed_ready,
        "finetune_min_required": finetune_min_required,
        "finetune_ready": finetune_reviewed_ready >= finetune_min_required,
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
            if payload.get("global_complexity"):
                item["classification"]["global_complexity"] = payload.get("global_complexity")
            item["status"] = "PROCESSED"
            item["updated_at"] = datetime.now(timezone.utc).isoformat()
            item["reviewed"] = True
            item["reviewed_at"] = datetime.now(timezone.utc).isoformat()
        await cosmos_container.upsert_item(item)
        return EmailRecord(**item)
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex))


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

    await _ensure_cosmos_container()

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


async def export_cosmos_to_finetune_jsonl(
    path: str = "./data/fine_tune.jsonl",
    anonymize: bool = True,
    include_unreviewed: bool = False,
    max_examples: Optional[int] = None,
    taxonomy_version: str = "v1",
):
    """Export reviewed examples to JSONL for fine-tuning.

    Pipeline:
    1) Select PROCESSED + classification.needs_review=false (optionally only reviewed=true)
    2) Anonymize OCR markdown (LLM anonymizer) to remove PII
    3) Write chat-style JSONL: system + user(anonymized markdown) + assistant(target JSON)
    """
    await _ensure_cosmos_container()
    os.makedirs(os.path.dirname(path), exist_ok=True)

    where = ["c.status = 'PROCESSED'", "IS_DEFINED(c.classification)", "c.classification.needs_review = false"]
    if not include_unreviewed:
        where.append("(IS_DEFINED(c.reviewed) AND c.reviewed = true)")
    query = "SELECT c.id, c.markdown, c.classification, c.updated_at FROM c WHERE " + " AND ".join(where)
    it = cosmos_container.query_items(query, enable_cross_partition_query=True)

    system_prompt = os.getenv(
        "FINETUNE_SYSTEM_PROMPT",
        "You classify insurance emails into intents and output strict JSON only.",
    )

    written = 0
    with open(path, "w", encoding="utf-8") as f:
        async for item in it:
            if max_examples is not None and written >= max_examples:
                break

            classification = item.get("classification") or {}
            intents = classification.get("detected_intents") or []
            if not intents:
                # Skip empty labels by default (they often represent missing taxonomy coverage).
                continue

            raw_markdown = item.get("markdown") or ""
            anonymization_meta = None
            user_markdown = raw_markdown

            if anonymize:
                try:
                    anon = await anonymize_markdown_for_finetune(raw_markdown)
                    user_markdown = anon.get("anonymized_markdown") or ""
                    anonymization_meta = {
                        "model": anon.get("model"),
                        "prompt_version": anon.get("prompt_version"),
                        "usage": anon.get("usage"),
                    }
                except Exception as ex:
                    # If anonymization fails, skip the example (safer than exporting raw PII).
                    continue

            target = {
                "detected_intents": intents,
            }
            if classification.get("global_complexity"):
                target["global_complexity"] = classification.get("global_complexity")

            assistant_content = json.dumps(target, ensure_ascii=False)
            example = {
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_markdown},
                    {"role": "assistant", "content": assistant_content},
                ],
                "metadata": {
                    "example_id": item.get("id"),
                    "taxonomy_version": taxonomy_version,
                    "source": "human_review",
                    "updated_at": item.get("updated_at"),
                    "anonymized": bool(anonymize),
                    "anonymization": anonymization_meta,
                    "hash": hashlib.sha256((user_markdown + assistant_content).encode("utf-8")).hexdigest(),
                },
            }
            f.write(json.dumps(example, ensure_ascii=False) + "\n")
            written += 1

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


@app.get("/api/emails/export-finetune-jsonl")
async def export_emails_finetune_jsonl(
    anonymize: bool = Query(True),
    include_unreviewed: bool = Query(False),
    max_examples: Optional[int] = Query(None, ge=1),
    taxonomy_version: str = Query("v1"),
    include_metadata: bool = Query(False),
    min_required: Optional[int] = Query(None, ge=1),
):
    """Stream fine-tuning JSONL (chat format) to the client.

    By default this exports only reviewed examples (reviewed=true) and anonymizes markdown.
    The dataset is gated by a minimum example threshold to encourage quality.
    """

    finetune_min_required = min_required or int(os.getenv("FINETUNE_MIN_EXAMPLES", "50"))
    finetune_reviewed_ready = await count_reviewed_ready_items()
    if not include_unreviewed and finetune_reviewed_ready < finetune_min_required:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Not enough reviewed examples to export fine-tuning dataset.",
                "reviewed_ready": finetune_reviewed_ready,
                "min_required": finetune_min_required,
            },
        )

    system_prompt = os.getenv(
        "FINETUNE_SYSTEM_PROMPT",
        "You classify insurance emails into intents and output strict JSON only.",
    )

    async def jsonl_iter():
        # Emit UTF-8 BOM (required by Foundry fine-tuning dataset validation)
        yield "\ufeff"

        where = ["c.status = 'PROCESSED'", "IS_DEFINED(c.classification)", "c.classification.needs_review = false"]
        if not include_unreviewed:
            where.append("(IS_DEFINED(c.reviewed) AND c.reviewed = true)")
        query = "SELECT c.id, c.markdown, c.classification, c.updated_at FROM c WHERE " + " AND ".join(where)
        it = cosmos_container.query_items(query, enable_cross_partition_query=True)

        written = 0
        async for item in it:
            if max_examples is not None and written >= max_examples:
                break

            classification = item.get("classification") or {}
            intents = classification.get("detected_intents") or []
            if not intents:
                continue

            raw_markdown = item.get("markdown") or ""
            anonymization_meta = None
            user_markdown = raw_markdown

            if anonymize:
                try:
                    anon = await anonymize_markdown_for_finetune(raw_markdown)
                    user_markdown = anon.get("anonymized_markdown") or ""
                    anonymization_meta = {
                        "model": anon.get("model"),
                        "prompt_version": anon.get("prompt_version"),
                        "usage": anon.get("usage"),
                    }
                except Exception:
                    # Safer than exporting raw PII
                    continue

            target = {"detected_intents": intents}
            if classification.get("global_complexity"):
                target["global_complexity"] = classification.get("global_complexity")

            assistant_content = json.dumps(target, ensure_ascii=False)
            example = {
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_markdown},
                    {"role": "assistant", "content": assistant_content},
                ]
            }
            if include_metadata:
                example["metadata"] = {
                    "example_id": item.get("id"),
                    "taxonomy_version": taxonomy_version,
                    "source": "human_review",
                    "updated_at": item.get("updated_at"),
                    "anonymized": bool(anonymize),
                    "anonymization": anonymization_meta,
                    "hash": hashlib.sha256((user_markdown + assistant_content).encode("utf-8")).hexdigest(),
                }

            yield json.dumps(example, ensure_ascii=False) + "\n"
            written += 1

    filename = f"fine_tune_{taxonomy_version}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.jsonl"
    return StreamingResponse(
        jsonl_iter(),
        media_type="application/jsonl",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


if __name__ == "__main__":
    # Optional CLI: uvicorn main:app --reload
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--export-csv", help="Export Cosmos data to CSV at path", nargs="?")
    parser.add_argument("--export-finetune-jsonl", help="Export fine-tuning JSONL at path", nargs="?")
    parser.add_argument("--no-anonymize", action="store_true", help="Export fine-tuning JSONL without LLM anonymization (NOT recommended)")
    parser.add_argument("--include-unreviewed", action="store_true", help="Include items without reviewed=true")
    parser.add_argument("--max-examples", type=int, default=None, help="Limit number of exported examples")
    parser.add_argument("--taxonomy-version", type=str, default="v1", help="Taxonomy version tag")
    args = parser.parse_args()
    if args.export_csv:
        asyncio.run(export_cosmos_to_csv(args.export_csv))
    elif args.export_finetune_jsonl:
        asyncio.run(
            export_cosmos_to_finetune_jsonl(
                path=args.export_finetune_jsonl,
                anonymize=not args.no_anonymize,
                include_unreviewed=bool(args.include_unreviewed),
                max_examples=args.max_examples,
                taxonomy_version=args.taxonomy_version,
            )
        )
    else:
        import uvicorn
        uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=True)