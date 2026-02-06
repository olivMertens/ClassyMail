from __future__ import annotations

import os


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

# RAG / Chatbot Configuration
# Containers for Chat History and Semantic Caching (as per Azure RAG designs)
COSMOS_CHAT_CONTAINER = os.getenv("AZURE_COSMOS_CHAT_CONTAINER", "chat_history")
COSMOS_CACHE_CONTAINER = os.getenv("AZURE_COSMOS_CACHE_CONTAINER", "vector_cache")

# AI endpoints
MISTRAL_ENDPOINT = os.getenv("MISTRAL_ENDPOINT")  # https://...azure.net
MISTRAL_API_VERSION = os.getenv("MISTRAL_API_VERSION", "2024-05-01-preview")
MISTRAL_DEPLOYMENT = os.getenv("MISTRAL_DEPLOYMENT", "mistral-document-ai-2505")
PHI_ENDPOINT = os.getenv("PHI_ENDPOINT") or os.getenv("AZURE_AI_ENDPOINT")
PHI_DEPLOYMENT = os.getenv("PHI_DEPLOYMENT", "phi-4")
AI_API_VERSION = os.getenv("AZURE_AI_API_VERSION", "2024-08-01-preview")
AI_SCOPE = os.getenv("AZURE_AI_SCOPE", "https://cognitiveservices.azure.com/.default")
AI_API_KEY = os.getenv("AZURE_AI_KEY")

# Fallback model (for long contexts / safety net).
PHI_FALLBACK_ENDPOINT = os.getenv("PHI_FALLBACK_ENDPOINT") or PHI_ENDPOINT
PHI_FALLBACK_DEPLOYMENT = os.getenv("PHI_FALLBACK_DEPLOYMENT", "gpt-4o-mini")

# Anonymization model (used to create fine-tuning datasets without PII).
ANONYMIZER_ENDPOINT = os.getenv("ANONYMIZER_ENDPOINT") or PHI_ENDPOINT
ANONYMIZER_DEPLOYMENT = os.getenv("ANONYMIZER_DEPLOYMENT", "gpt-4o-mini")
ANONYMIZER_API_VERSION = os.getenv("ANONYMIZER_API_VERSION", AI_API_VERSION)
ANONYMIZER_PROMPT_VERSION = os.getenv("ANONYMIZER_PROMPT_VERSION", "v1")
ANONYMIZER_MAX_TOKENS = int(os.getenv("ANONYMIZER_MAX_TOKENS", "6000"))

# Embedding model for Vector Search
EMBEDDING_ENDPOINT = os.getenv("EMBEDDING_ENDPOINT") or PHI_ENDPOINT
EMBEDDING_DEPLOYMENT = os.getenv("EMBEDDING_DEPLOYMENT", "text-embedding-3-small")
EMBEDDING_API_VERSION = os.getenv("EMBEDDING_API_VERSION", AI_API_VERSION)

# Azure AI Language Service for PII Detection (optional, alternative to LLM-based)
LANGUAGE_ENDPOINT = os.getenv("AZURE_LANGUAGE_ENDPOINT")  # https://xxx.cognitiveservices.azure.com/
LANGUAGE_KEY = os.getenv("AZURE_LANGUAGE_KEY")  # Optional key-based auth (prefer MI)


# Vision model for image description (parallel flow with OCR)
VISION_ENDPOINT = os.getenv("VISION_ENDPOINT") or PHI_ENDPOINT
VISION_DEPLOYMENT = os.getenv("VISION_DEPLOYMENT", "gpt-4o-mini")
VISION_API_VERSION = os.getenv("VISION_API_VERSION", AI_API_VERSION)

# Chatbot model
CHAT_ENDPOINT = os.getenv("CHAT_ENDPOINT") or PHI_ENDPOINT
CHAT_DEPLOYMENT = os.getenv("CHAT_DEPLOYMENT", "gpt-5.2-chat")
CHAT_API_VERSION = os.getenv("CHAT_API_VERSION", AI_API_VERSION)

# Data Zone / Data Residency (EU Central, Global, etc)
# Used to validate endpoints are in preferred region for compliance
AZURE_PREFERRED_DATA_ZONE = os.getenv("AZURE_PREFERRED_DATA_ZONE", "eu-central")  # eu-central, eastus, etc
AZURE_REGION = os.getenv("AZURE_REGION", "swedencentral")  # Container App region for observability

# Cosmos query guardrail
COSMOS_QUERY_MAX_LIMIT = int(os.getenv("COSMOS_QUERY_MAX_LIMIT", "100"))

# Context sizing (best-effort). Adjust to match your deployments.
PHI_PRIMARY_MAX_INPUT_TOKENS = int(os.getenv("PHI_PRIMARY_MAX_INPUT_TOKENS", "8000"))
PHI_FALLBACK_MAX_INPUT_TOKENS = int(os.getenv("PHI_FALLBACK_MAX_INPUT_TOKENS", "120000"))
PHI_RESERVED_OUTPUT_TOKENS = int(os.getenv("PHI_RESERVED_OUTPUT_TOKENS", "1000"))

PHI4_COST_PER_1K_INPUT = float(os.getenv("PHI4_COST_PER_1K_INPUT", "0.000107"))
PHI4_COST_PER_1K_OUTPUT = float(os.getenv("PHI4_COST_PER_1K_OUTPUT", "0.00043"))
MISTRAL_OCR_COST_PER_1K_PAGES = float(os.getenv("MISTRAL_OCR_COST_PER_1K_PAGES", "1.0"))
MISTRAL_OCR_MAX_ATTEMPTS = int(os.getenv("MISTRAL_OCR_MAX_ATTEMPTS", "3"))
REVIEW_CONFIDENCE_THRESHOLD = float(os.getenv("REVIEW_CONFIDENCE_THRESHOLD", "0.85"))

# Pricing for fallback model is tenant/region specific. Keep as config (default 0).
FALLBACK_COST_PER_1K_INPUT = float(os.getenv("FALLBACK_COST_PER_1K_INPUT", "0"))
FALLBACK_COST_PER_1K_OUTPUT = float(os.getenv("FALLBACK_COST_PER_1K_OUTPUT", "0"))

# Log Analytics Workspace ID for querying logs
LOG_ANALYTICS_WORKSPACE_ID = os.getenv("LOG_ANALYTICS_WORKSPACE_ID")

# Upload
MAX_UPLOAD_SIZE = int(os.getenv("UPLOAD_MAX_BYTES", 10 * 1024 * 1024))  # 10MB

# UI Configuration (Feature Flags)
UI_SHOW_INFO_MODAL = os.getenv("UI_SHOW_INFO_MODAL", "true").lower() == "true"
UI_SHOW_DEVELOPER_TAB = os.getenv("UI_SHOW_DEVELOPER_TAB", "true").lower() == "true"

# Organization / Branding
ORGANIZATION_NAME = os.getenv("ORGANIZATION_NAME", "ClassyMail")

# Worker Configuration
WORKER_CONCURRENCY = int(os.getenv("WORKER_CONCURRENCY", "30"))  # Concurrent message processing tasks
WORKER_LOCK_RENEWAL_DURATION = int(os.getenv("WORKER_LOCK_RENEWAL_DURATION", "3600"))  # 1 hour for long documents

# Rate limits (RPM/TPM) per model
MISTRAL_RPM = int(os.getenv("MISTRAL_RPM", "30"))
MISTRAL_TPM = int(os.getenv("MISTRAL_TPM", "60000"))
PHI_RPM = int(os.getenv("PHI_RPM", "60"))
PHI_TPM = int(os.getenv("PHI_TPM", "80000"))
CHAT_RPM = int(os.getenv("CHAT_RPM", "60"))
CHAT_TPM = int(os.getenv("CHAT_TPM", "80000"))

# Environment Configuration
AZURE_ENV = os.getenv("AZURE_ENV", "development")  # production, staging, development
