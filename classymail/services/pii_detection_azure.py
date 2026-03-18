"""
Azure AI Language Service PII Detection

Native Azure AI Language Text Analytics API for PII detection.
Provides 40+ predefined entity categories with high accuracy:
- Names, emails, phones, addresses
- SSN, passport numbers, credit cards
- Medical info, biometric data
- IP addresses, URLs

Uses azure-ai-textanalytics SDK with Managed Identity authentication.
Alternative to LLM-based detection for compliance-sensitive workloads.
"""

from __future__ import annotations

import logging
from typing import List

from azure.ai.textanalytics import TextAnalyticsClient
from azure.core.credentials import AzureKeyCredential
from opentelemetry import trace

from classymail.core import config
from classymail.services.azure_clients import Clients
from classymail.services.pii_detection import PIIDetectionResult

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# Mapping from Azure AI Language entity categories to our PIIDetectionResult fields
CATEGORY_MAPPING = {
    # Names
    "Person": "names",
    "PersonType": "names",

    # Contact info
    "Email": "emails",
    "PhoneNumber": "phones",
    "Address": "addresses",

    # IDs and contracts
    "USSocialSecurityNumber": "contract_ids",
    "USDriversLicenseNumber": "contract_ids",
    "USPassportNumber": "contract_ids",
    "CreditCardNumber": "contract_ids",
    "InternationalBankingAccountNumber": "contract_ids",
    "SWIFTCode": "contract_ids",
    "ABARoutingNumber": "contract_ids",

    # Dates
    "DateTime": "dates",
    "Date": "dates",

    # Other sensitive info
    "IPAddress": "other",
    "URL": "other",
    "Organization": "other",  # Company names can be PII in some contexts
}


def _get_text_analytics_client(clients: Clients | None = None) -> TextAnalyticsClient | None:
    """
    Create Azure AI Language Text Analytics client.

    Uses Managed Identity (preferred) or API key fallback.
    Returns None if endpoint not configured.
    """
    endpoint = config.LANGUAGE_ENDPOINT

    if not endpoint:
        logger.warning("AZURE_LANGUAGE_ENDPOINT not configured. Azure Language PII detection unavailable.")
        return None

    try:
        # Prefer Managed Identity (consistent with architecture)
        if clients and clients.credential:
            return TextAnalyticsClient(
                endpoint=endpoint,
                credential=clients.credential
            )

        # Fallback to API key if provided
        if config.LANGUAGE_KEY:
            credential = AzureKeyCredential(config.LANGUAGE_KEY)
            return TextAnalyticsClient(
                endpoint=endpoint,
                credential=credential
            )

        # No auth available
        logger.error("No authentication method available for Azure Language service (tried MI + API key)")
        return None

    except Exception as e:
        logger.error(f"Failed to create Text Analytics client: {e}")
        return None


async def detect_pii_with_azure_language(
    text_content: str,
    *,
    clients: Clients | None = None,
    language: str = "en",
) -> PIIDetectionResult:
    """
    Detect PII using Azure AI Language Service native API.

    Args:
        text_content: Text to analyze for PII
        clients: Azure clients for Managed Identity authentication
        language: ISO 639-1 language code (en, fr, es, etc.)

    Returns:
        PIIDetectionResult with all detected PII entities

    Features:
        - 40+ predefined entity categories
        - Confidence scores per entity
        - Redacted text generation
        - Multi-language support

    Cost: ~$1 per 1,000 text records (Standard tier)
    Pricing: https://azure.microsoft.com/pricing/details/cognitive-services/language-service/
    """
    if not text_content or len(text_content.strip()) < 10:
        return PIIDetectionResult()

    client = _get_text_analytics_client(clients)
    if not client:
        logger.warning("Azure Language client not available. Returning empty PII result.")
        return PIIDetectionResult()

    with tracer.start_as_current_span("detect_pii_azure_language") as span:
        span.set_attribute("pii.detection.method", "azure_language")
        span.set_attribute("pii.detection.language", language)
        span.set_attribute("gen_ai.system", "azure_language")
        span.set_attribute("gen_ai.operation", "recognize_pii_entities")

        try:
            # Truncate to avoid API limits (5,120 characters per document)
            text_to_analyze = text_content[:5000]

            # Call Azure AI Language PII API
            documents = [text_to_analyze]
            response = client.recognize_pii_entities(documents, language=language)

            # Parse results
            result_docs = [doc for doc in response if not doc.is_error]

            if not result_docs:
                logger.warning("Azure Language PII detection returned no results or errors")
                return PIIDetectionResult()

            # Extract entities from first document
            doc = result_docs[0]

            # Initialize result containers
            names: List[str] = []
            emails: List[str] = []
            phones: List[str] = []
            addresses: List[str] = []
            contract_ids: List[str] = []
            dates: List[str] = []
            other: List[str] = []

            # Map entities to our schema
            for entity in doc.entities:
                entity_text = entity.text
                category = entity.category
                confidence = entity.confidence_score

                # Only include high-confidence entities (>= 0.5)
                if confidence < 0.5:
                    continue

                # Map to our fields
                target_field = CATEGORY_MAPPING.get(category, "other")

                if target_field == "names":
                    names.append(entity_text)
                elif target_field == "emails":
                    emails.append(entity_text)
                elif target_field == "phones":
                    phones.append(entity_text)
                elif target_field == "addresses":
                    addresses.append(entity_text)
                elif target_field == "contract_ids":
                    contract_ids.append(entity_text)
                elif target_field == "dates":
                    dates.append(entity_text)
                else:
                    other.append(f"{category}: {entity_text}")

            # Create result
            result = PIIDetectionResult(
                names=names,
                emails=emails,
                phones=phones,
                addresses=addresses,
                contract_ids=contract_ids,
                dates=dates,
                other=other
            )

            # Add telemetry
            span.set_attribute("pii.detected", result.has_pii)
            span.set_attribute("pii.total_count", result.total_count)
            span.set_attribute("pii.types", ",".join(result.pii_types))
            span.set_attribute("pii.entities_count", len(doc.entities))

            logger.info(
                f"Azure Language PII detection complete: {result.total_count} items found "
                f"({', '.join(result.pii_types) if result.pii_types else 'none'}) "
                f"from {len(doc.entities)} raw entities"
            )

            return result

        except Exception as e:
            logger.error(f"Azure Language PII detection failed: {e}")
            span.record_exception(e)
            return PIIDetectionResult()
