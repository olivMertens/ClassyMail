"""
PII Detection Service for GDPR Compliance

LLM-based detection and extraction of Personal Identifiable Information (PII):
- Names (first name, last name, full names)
- Email addresses
- Phone numbers
- Physical addresses
- Contract/policy IDs
- Dates (birth dates, contract dates)
- Other sensitive identifiers

Uses JSON mode for structured extraction.
Optional feature controlled by email_preprocessing.detect_pii setting.
"""

from __future__ import annotations

import json
import logging
from typing import List

import httpx
from opentelemetry import trace
from pydantic import BaseModel

from classymail.core import config
from classymail.services.azure_clients import auth_headers, Clients

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class PIIDetectionResult(BaseModel):
    """Structured PII detection result."""
    names: List[str] = []
    emails: List[str] = []
    phones: List[str] = []
    addresses: List[str] = []
    contract_ids: List[str] = []
    dates: List[str] = []
    other: List[str] = []  # Other sensitive info

    @property
    def has_pii(self) -> bool:
        """Check if any PII was detected."""
        return any([
            self.names, self.emails, self.phones,
            self.addresses, self.contract_ids, self.dates, self.other
        ])

    @property
    def pii_types(self) -> List[str]:
        """Get list of PII types found."""
        types = []
        if self.names:
            types.append("names")
        if self.emails:
            types.append("emails")
        if self.phones:
            types.append("phones")
        if self.addresses:
            types.append("addresses")
        if self.contract_ids:
            types.append("contract_ids")
        if self.dates:
            types.append("dates")
        if self.other:
            types.append("other")
        return types

    @property
    def total_count(self) -> int:
        """Total count of PII items detected."""
        return (
            len(self.names) + len(self.emails) + len(self.phones) +
            len(self.addresses) + len(self.contract_ids) +
            len(self.dates) + len(self.other)
        )


async def detect_pii_with_llm(
    text_content: str,
    *,
    clients: Clients | None = None,
) ->PIIDetectionResult:
    """
    Detect and extract PII from email content using LLM with JSON mode.

    Args:
        text_content: Email content to analyze
        clients: Azure clients for authentication

    Returns:
        PIIDetectionResult containing all extracted PII

    Cost: ~$0.002 per email (using GPT-4o-mini)
    """
    if not text_content or len(text_content.strip()) < 10:
        return PIIDetectionResult()

    # Use GPT-4o-mini for PII detection (cost-effective)
    deployment = "gpt-4o-mini"
    endpoint = config.AI_ENDPOINT

    if not endpoint or not deployment:
        logger.warning("No LLM endpoint available for PII detection. Returning empty result.")
        return PIIDetectionResult()

    system_prompt = """You are a GDPR compliance expert specialized in detecting Personal Identifiable Information (PII).

Your task is to extract ALL PII from the provided text and return it in JSON format.

Extract the following categories:
- **names**: Full names, first names, last names of real people (NOT company names)
- **emails**: Email addresses
- **phones**: Phone numbers (any format)
- **addresses**: Physical addresses (street, city, postal code)
- **contract_ids**: Contract numbers, policy numbers, claim IDs, reference numbers
- **dates**: Dates that could identify a person (birth dates, contract dates, event dates)
- **other**: Any other sensitive identifiers (SSN, passport numbers, etc.)

IMPORTANT:
- Extract ALL occurrences, even if repeated
- Preserve original format (don't normalize)
- Return empty arrays for categories with no data
- Be thorough - missing PII is a GDPR violation risk

Example JSON output:
{
  "names": ["Jean Dupont", "Marie Martin"],
  "emails": ["jean.dupont@example.com"],
  "phones": ["+33 6 12 34 56 78", "06.12.34.56.78"],
  "addresses": ["15 Rue de la Paix, 75001 Paris"],
  "contract_ids": ["POL-2024-001234", "CLAIM-5678"],
  "dates": ["1985-03-15", "2024-01-20"],
  "other": []
}"""

    user_content = f"""Extract ALL PII from this email content:

---
{text_content[:6000]}  # Limit to avoid token overflow while capturing most PII
---

Return the PII in JSON format as specified."""

    headers = await auth_headers(clients=clients)
    url = f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/chat/completions?api-version={config.AI_API_VERSION}"

    payload = {
        "model": deployment,
        "response_format": {"type": "json_object"},  # Force JSON mode
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.0,  # Deterministic extraction
        "max_tokens": 2000,  # Sufficient for comprehensive PII list
    }

    with tracer.start_as_current_span("detect_pii") as span:
        span.set_attribute("gen_ai.system", "azure_openai")
        span.set_attribute("gen_ai.operation", "extract.pii")
        span.set_attribute("gen_ai.request.model", deployment)
        span.set_attribute("pii.detection.enabled", True)

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()

                # Extract JSON response
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                pii_data = json.loads(content)

                # Parse into Pydantic model
                result = PIIDetectionResult(**pii_data)

                # Add metrics to span
                span.set_attribute("pii.detected", result.has_pii)
                span.set_attribute("pii.total_count", result.total_count)
                span.set_attribute("pii.types", ",".join(result.pii_types))

                logger.info(
                    f"PII detection complete: {result.total_count} items found "
                    f"({', '.join(result.pii_types) if result.pii_types else 'none'})"
                )

                return result

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse PII JSON response: {e}")
            span.record_exception(e)
            return PIIDetectionResult()
        except Exception as e:
            logger.error(f"PII detection failed: {e}")
            span.record_exception(e)
            return PIIDetectionResult()
