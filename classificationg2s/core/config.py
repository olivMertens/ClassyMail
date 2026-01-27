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

# AI endpoints
MISTRAL_ENDPOINT = os.getenv("MISTRAL_ENDPOINT")  # https://...azure.net
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
ANONYMIZER_DEPLOYMENT = os.getenv("ANONYMIZER_DEPLOYMENT", "gpt-4o")
ANONYMIZER_API_VERSION = os.getenv("ANONYMIZER_API_VERSION", AI_API_VERSION)
ANONYMIZER_PROMPT_VERSION = os.getenv("ANONYMIZER_PROMPT_VERSION", "v1")
ANONYMIZER_MAX_TOKENS = int(os.getenv("ANONYMIZER_MAX_TOKENS", "6000"))

# Vision model for image description (parallel flow with OCR)
VISION_ENDPOINT = os.getenv("VISION_ENDPOINT") or PHI_ENDPOINT
VISION_DEPLOYMENT = os.getenv("VISION_DEPLOYMENT", "gpt-4o")
VISION_API_VERSION = os.getenv("VISION_API_VERSION", AI_API_VERSION)

# Chatbot model
CHAT_ENDPOINT = os.getenv("CHAT_ENDPOINT") or PHI_ENDPOINT
CHAT_DEPLOYMENT = os.getenv("CHAT_DEPLOYMENT", "gpt-5.2-chat")
CHAT_API_VERSION = os.getenv("CHAT_API_VERSION", AI_API_VERSION)

# Cosmos query guardrail
COSMOS_QUERY_MAX_LIMIT = int(os.getenv("COSMOS_QUERY_MAX_LIMIT", "20"))

# Context sizing (best-effort). Adjust to match your deployments.
PHI_PRIMARY_MAX_INPUT_TOKENS = int(os.getenv("PHI_PRIMARY_MAX_INPUT_TOKENS", "8000"))
PHI_FALLBACK_MAX_INPUT_TOKENS = int(os.getenv("PHI_FALLBACK_MAX_INPUT_TOKENS", "120000"))
PHI_RESERVED_OUTPUT_TOKENS = int(os.getenv("PHI_RESERVED_OUTPUT_TOKENS", "1000"))

PHI4_COST_PER_1K_INPUT = float(os.getenv("PHI4_COST_PER_1K_INPUT", "0.000107"))
PHI4_COST_PER_1K_OUTPUT = float(os.getenv("PHI4_COST_PER_1K_OUTPUT", "0.00043"))
MISTRAL_OCR_COST_PER_1K_PAGES = float(os.getenv("MISTRAL_OCR_COST_PER_1K_PAGES", "1.0"))

# Pricing for fallback model is tenant/region specific. Keep as config (default 0).
FALLBACK_COST_PER_1K_INPUT = float(os.getenv("FALLBACK_COST_PER_1K_INPUT", "0"))
FALLBACK_COST_PER_1K_OUTPUT = float(os.getenv("FALLBACK_COST_PER_1K_OUTPUT", "0"))

# Upload
MAX_UPLOAD_SIZE = int(os.getenv("UPLOAD_MAX_BYTES", 10 * 1024 * 1024))  # 10MB
