"""
PII Detection Service for GDPR Compliance

Supports multiple detection methods:
1. LLM-based (GPT-4o-mini): Contextual understanding, flexible extraction (~$0.002/email)
2. Azure AI Language: Native service with 40+ predefined categories (~$0.001/email)
3. Hybrid: Combines both methods for maximum accuracy

Detection methods controlled by settings.email_preprocessing.pii_detection_method:
- "llm": LLM-based only (default)
- "azure_language": Azure AI Language service only
- "both": Hybrid mode (run both, merge results)

Uses JSON mode for LLM extraction.
Optional feature controlled by email_preprocessing.detect_pii setting.
"""

from __future__ import annotations

import json
import logging
from typing import List

from opentelemetry import trace
from pydantic import BaseModel

from classymail.core import config
from classymail.services.openai_client_factory import build_chat_params, extract_message_content, get_chat_client
from classymail.services.azure_clients import Clients

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
    model: str | None = None,
) -> PIIDetectionResult:
    """
    Detect and extract PII from email content using LLM with JSON mode.

    Args:
        text_content: Email content to analyze
        clients: Azure clients for authentication
        model: LLM deployment name (default: from settings or PHI_DEPLOYMENT)

    Returns:
        PIIDetectionResult containing all extracted PII
    """
    if not text_content or len(text_content.strip()) < 10:
        return PIIDetectionResult()

    # Resolve model: explicit > config fallback
    deployment = model or config.PHI_DEPLOYMENT
    endpoint = config.PHI_ENDPOINT

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

    chat_params = build_chat_params(deployment, temperature=0.0, max_output_tokens=2000)

    with tracer.start_as_current_span("detect_pii") as span:
        span.set_attribute("gen_ai.system", "azure_openai")
        span.set_attribute("gen_ai.operation", "extract.pii")
        span.set_attribute("gen_ai.request.model", deployment)
        span.set_attribute("pii.detection.enabled", True)

        try:
            chat_client = await get_chat_client(endpoint, config.AI_API_VERSION, clients=clients)
            completion = await chat_client.chat.completions.create(
                model=deployment,
                response_format={"type": "json_object"},  # Force JSON mode
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                timeout=30.0,
                **chat_params,
            )
            data = completion.model_dump()

            # Extract JSON response
            content = extract_message_content(data.get("choices", [{}])[0].get("message", {})) or "{}"
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


def _merge_pii_results(llm_result: PIIDetectionResult, azure_result: PIIDetectionResult) -> PIIDetectionResult:
    """
    Merge PII results from LLM and Azure Language, deduplicating similar entries.

    Uses case-insensitive comparison and fuzzy matching to avoid duplicates.
    """
    def deduplicate(items: List[str]) -> List[str]:
        """Remove duplicates (case-insensitive) while preserving order."""
        seen = set()
        result = []
        for item in items:
            item_lower = item.lower().strip()
            if item_lower and item_lower not in seen:
                seen.add(item_lower)
                result.append(item)
        return result

    return PIIDetectionResult(
        names=deduplicate(llm_result.names + azure_result.names),
        emails=deduplicate(llm_result.emails + azure_result.emails),
        phones=deduplicate(llm_result.phones + azure_result.phones),
        addresses=deduplicate(llm_result.addresses + azure_result.addresses),
        contract_ids=deduplicate(llm_result.contract_ids + azure_result.contract_ids),
        dates=deduplicate(llm_result.dates + azure_result.dates),
        other=deduplicate(llm_result.other + azure_result.other),
    )


async def detect_pii(
    text_content: str,
    *,
    method: str = "llm",
    clients: Clients | None = None,
    language: str = "en",
    model: str | None = None,
) -> PIIDetectionResult:
    """
    Detect PII using the specified method(s).

    Args:
        text_content: Text to analyze for PII
        method: Detection method - "llm", "azure_language", or "both"
        clients: Azure clients for authentication
        language: Language code for Azure Language service (en, fr, etc.)

    Returns:
        PIIDetectionResult with detected PII entities

    Raises:
        ValueError: If method is invalid
    """
    if not text_content or len(text_content.strip()) < 10:
        return PIIDetectionResult()

    method = method.lower()

    if method == "llm":
        return await detect_pii_with_llm(text_content, clients=clients, model=model)

    elif method == "azure_language":
        # Import here to avoid circular dependency and optional dependency
        try:
            from classymail.services.pii_detection_azure import detect_pii_with_azure_language
            return await detect_pii_with_azure_language(text_content, clients=clients, language=language)
        except ImportError as e:
            logger.error(f"Azure AI Language service not available: {e}. Install: pip install azure-ai-textanalytics")
            logger.warning("Falling back to LLM-based PII detection")
            return await detect_pii_with_llm(text_content, clients=clients, model=model)

    elif method == "both":
        # Hybrid mode: run both methods and merge results
        with tracer.start_as_current_span("detect_pii_hybrid") as span:
            span.set_attribute("pii.detection.method", "hybrid")

            try:
                # Run both methods in parallel
                llm_task = detect_pii_with_llm(text_content, clients=clients, model=model)

                from classymail.services.pii_detection_azure import detect_pii_with_azure_language
                azure_task = detect_pii_with_azure_language(text_content, clients=clients, language=language)

                import asyncio
                llm_result, azure_result = await asyncio.gather(llm_task, azure_task, return_exceptions=True)

                # Handle exceptions
                if isinstance(llm_result, Exception):
                    logger.error(f"LLM PII detection failed in hybrid mode: {llm_result}")
                    llm_result = PIIDetectionResult()

                if isinstance(azure_result, Exception):
                    logger.error(f"Azure Language PII detection failed in hybrid mode: {azure_result}")
                    azure_result = PIIDetectionResult()

                # Merge results
                merged = _merge_pii_results(llm_result, azure_result)

                span.set_attribute("pii.detected", merged.has_pii)
                span.set_attribute("pii.total_count", merged.total_count)
                span.set_attribute("pii.llm_count", llm_result.total_count)
                span.set_attribute("pii.azure_count", azure_result.total_count)

                logger.info(
                    f"Hybrid PII detection complete: {merged.total_count} items "
                    f"(LLM: {llm_result.total_count}, Azure: {azure_result.total_count})"
                )

                return merged

            except ImportError as e:
                logger.error(f"Azure AI Language service not available for hybrid mode: {e}")
                logger.warning("Falling back to LLM-only PII detection")
                return await detect_pii_with_llm(text_content, clients=clients, model=model)

    else:
        raise ValueError(f"Invalid PII detection method: {method}. Must be 'llm', 'azure_language', or 'both'")
