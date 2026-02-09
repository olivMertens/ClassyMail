"""
Email Preprocessing Service for Client G2S

LLM-based intelligent email content extraction:
- Extract subject from markdown-formatted emails
- Extract last conversation (ignore history, signatures, boilerplate)
- Prepare content for classification with configurable options

Respects email_preprocessing settings from settings_store.
"""

from __future__ import annotations

import logging
import re
from typing import Tuple

import httpx
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from classymail.core import config
from classymail.core.llm_compat import build_chat_params, extract_message_content
from classymail.services.azure_clients import auth_headers, Clients
from classymail.services.settings_store import load_settings

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


def extract_subject_from_markdown(text_markdown: str) -> str:
    """
    Extract email subject from markdown-formatted email content.
    Looks for common patterns like 'Subject:' or extracts first heading.

    Args:
        text_markdown: Markdown-formatted email text

    Returns:
        Extracted subject line or empty string
    """
    if not text_markdown:
        return ""

    # Try to find explicit subject line
    subject_match = re.search(r'^(?:Subject|Objet|Sujet):\s*(.+)$', text_markdown, re.MULTILINE | re.IGNORECASE)
    if subject_match:
        return subject_match.group(1).strip()

    # Try to find first heading
    heading_match = re.search(r'^#\s+(.+)$', text_markdown, re.MULTILINE)
    if heading_match:
        return heading_match.group(1).strip()

    # Try to find first line if it looks like a subject (short, no special chars)
    first_line = text_markdown.split('\n')[0].strip()
    if first_line and len(first_line) < 100 and not first_line.startswith(('>', '-', '*', '[')):
        return first_line

    return ""


async def extract_last_conversation_with_llm(
    text_markdown: str,
    *,
    clients: Clients | None = None,
    model: str | None = None,
) -> str:
    """
    Use LLM to extract the last meaningful conversation from an email thread.

    Removes:
    - Email history/quoted replies
    - Signatures and footers
    - Legal disclaimers and boilerplate
    - Automatic replies tags

    Args:
        text_markdown: Full email content in markdown
        clients: Azure clients for authentication

    Returns:
        Cleaned email content containing only the last conversation
    """
    if not text_markdown or len(text_markdown.strip()) < 10:
        return text_markdown

    # Resolve model dynamically from settings or config
    deployment = model or config.PHI_DEPLOYMENT
    endpoint = config.PHI_ENDPOINT

    if not endpoint or not deployment:
        logger.warning("No LLM endpoint available for preprocessing. Returning original content.")
        return text_markdown

    system_prompt = """You are an email preprocessing expert.
Your task is to extract ONLY the last meaningful conversation from an email thread.

REMOVE:
- All quoted replies (lines starting with '>', 'On ... wrote:', etc.)
- Email signatures (contact info, disclaimers, legal notices)
- Automatic reply tags and boilerplate text
- Thread history and previous messages
- Footer disclaimers and confidentiality notices

KEEP:
- The actual message content from the most recent sender
- Any attachments mentions relevant to this message
- Important context that is NOT historical

Return ONLY the cleaned text content, preserving the original language.
If the entire email is just boilerplate/signature with no real content, return "NO_CONTENT"."""

    user_content = f"""Extract the last conversation from this email:

---
{text_markdown[:8000]}  # Limit to avoid token overflow
---

Return only the cleaned content."""

    headers = await auth_headers(clients=clients)
    url = f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/chat/completions?api-version={config.AI_API_VERSION}"

    payload = {
        "model": deployment,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        **build_chat_params(deployment, temperature=0.0, max_output_tokens=3000),
    }

    with tracer.start_as_current_span("extract_last_conversation") as span:
        span.set_attribute("gen_ai.system", "azure_openai")
        span.set_attribute("gen_ai.operation", "preprocess.conversation")
        span.set_attribute("gen_ai.request.model", deployment)

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()

                # Extract response
                extracted = (extract_message_content(data.get("choices", [{}])[0].get("message", {})) or "").strip()

                # Check if LLM detected no real content
                if extracted.upper() == "NO_CONTENT":
                    logger.warning("LLM detected no meaningful content in email")
                    return ""

                span.set_status(Status(StatusCode.OK))
                return extracted

        except Exception as e:
            logger.error(f"LLM preprocessing failed: {e}")
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            # Fallback: return original content
            return text_markdown


async def preprocess_email_content(
    text_markdown: str,
    *,
    clients: Clients | None = None,
    override_settings: dict | None = None,
) -> Tuple[str, dict]:
    """
    Preprocess email content based on settings before classification.

    Args:
        text_markdown: Original email content in markdown
        clients: Azure clients for authentication
        override_settings: Optional settings override (for testing)

    Returns:
        Tuple of (processed_content, preprocessing_metadata)

    Example metadata:
        {
            "preprocessing_enabled": True,
            "subject_included": True,
            "conversation_extracted": True,
            "original_length": 5000,
            "processed_length": 1200,
            "subject": "Re: Claim #12345"
        }
    """
    settings = override_settings or load_settings()
    preprocessing_config = settings.get("email_preprocessing", {})

    metadata = {
        "preprocessing_enabled": preprocessing_config.get("enabled", True),
        "subject_included": False,
        "conversation_extracted": False,
        "original_length": len(text_markdown),
        "processed_length": 0,
        "subject": ""
    }

    # If preprocessing is disabled, return original content
    if not preprocessing_config.get("enabled", True):
        metadata["processed_length"] = len(text_markdown)
        return text_markdown, metadata

    processed_content = text_markdown

    # Extract subject if configured
    subject = ""
    if preprocessing_config.get("include_subject", True):
        subject = extract_subject_from_markdown(text_markdown)
        metadata["subject"] = subject
        metadata["subject_included"] = True

    # Extract last conversation if configured
    if preprocessing_config.get("extract_last_conversation", True):
        with tracer.start_as_current_span("preprocess_email") as span:
            span.set_attribute("preprocessing.extract_conversation", True)
            processed_content = await extract_last_conversation_with_llm(
                text_markdown,
                clients=clients
            )
            metadata["conversation_extracted"] = True

    # Combine subject with content if both are available
    if subject and processed_content:
        final_content = f"Subject: {subject}\n\n{processed_content}"
    elif subject:
        final_content = subject
    else:
        final_content = processed_content or text_markdown

    metadata["processed_length"] = len(final_content)

    logger.info(
        f"Preprocessing complete: {metadata['original_length']} -> {metadata['processed_length']} chars "
        f"(subject: {bool(subject)}, extracted: {metadata['conversation_extracted']})"
    )

    return final_content, metadata
