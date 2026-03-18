from __future__ import annotations

import hashlib
import re

import httpx
from opentelemetry import trace

from classymail.core import config
from classymail.core.llm_compat import build_chat_params, extract_message_content
from classymail.services.azure_clients import auth_headers, Clients


tracer = trace.get_tracer(__name__)


ANONYMIZER_SYSTEM_PROMPT = """### ROLE ###
You are an advanced Data Privacy and Anonymization Engine. Your purpose is to sanitize email content formatted in Markdown.

### OBJECTIVE ###
Rewrite the user's provided email content to remove all Personally Identifiable Information (PII) and sensitive contextual data, while STRICTLY preserving the original Markdown syntax, styling, and structure.

### ANONYMIZATION RULES (PII) ###
1. **Direct PII:** Replace all names, phone numbers, email addresses, IP addresses, and physical addresses with generic placeholders (e.g., `[Name]`, `[Phone]`, `[Email]`, `[Address]`).
2. **Contextual PII:** Generalize specific details that could indirectly identify a person or company (e.g., change \"The project with Google\" to \"The project with [Client]\"; change \"My wife Sarah\" to \"My spouse\").
3. **Dates:** Generalize specific dates to months or quarters unless the specific date is crucial for generic context (e.g., change \"July 12th, 2024\" to `[Date]` or \"July 2024\").
4. **Numbers:** Mask financial figures or sensitive metrics if they are specific enough to identify the transaction (e.g., \"$1,234,550.00\" -> `[Amount]`).

### MARKDOWN PRESERVATION RULES ###
1. **Structure:** Do NOT alter headers (`#`), lists (`-`, `1.`), blockquotes (`>`), or code blocks (```).
2. **Links:** - Preserve the Markdown link syntax `[text](url)`.
   - If the *text* contains PII, anonymize it: `[John's Profile]` -> `[[Name]'s Profile]`.
   - If the *URL* contains PII (e.g., `linkedin.com/in/johndoe`), replace the URL with a safe placeholder like `#` or `http://example.com/profile`.
   - NEVER remove the link syntax itself.
3. **Tables:** Keep all table rows and columns intact (`|`). Anonymize the content *inside* the cells, but do not break the alignment.

### OUTPUT FORMAT ###
Return ONLY the anonymized Markdown text. Do not add conversational filler like "Here is the anonymized version."
""".strip()


def basic_pii_scrub(text: str) -> str:
    if not text:
        return text

    text = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[Email]", text)
    text = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[IP]", text)
    text = re.sub(r"\b(?:\+?\d[\d\s().-]{7,}\d)\b", "[Phone]", text)
    text = re.sub(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b", "[IBAN]", text)
    return text


async def anonymize_markdown_for_finetune(markdown: str, clients: Clients | None = None) -> dict:
    if not config.ANONYMIZER_ENDPOINT:
        raise RuntimeError("ANONYMIZER_ENDPOINT is not set")

    headers = await auth_headers(clients=clients)
    user_content = basic_pii_scrub(markdown or "")

    payload = {
        "model": config.ANONYMIZER_DEPLOYMENT,
        "messages": [
            {"role": "system", "content": ANONYMIZER_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        **build_chat_params(config.ANONYMIZER_DEPLOYMENT, temperature=0, max_output_tokens=config.ANONYMIZER_MAX_TOKENS),
    }

    url = (
        f"{config.ANONYMIZER_ENDPOINT}/openai/deployments/{config.ANONYMIZER_DEPLOYMENT}/chat/completions"
        f"?api-version={config.ANONYMIZER_API_VERSION}"
    )

    with tracer.start_as_current_span("anonymize_markdown") as span:
        span.set_attribute("gen_ai.system", "azure_openai")
        span.set_attribute("gen_ai.operation", "chat.completions")
        span.set_attribute("gen_ai.request.model", config.ANONYMIZER_DEPLOYMENT)
        span.set_attribute("app.anonymizer.prompt_version", config.ANONYMIZER_PROMPT_VERSION)

        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        content = extract_message_content(data.get("choices", [{}])[0].get("message", {})) or ""
        usage = data.get("usage")
        if usage:
            span.set_attribute("gen_ai.usage.input_tokens", usage.get("prompt_tokens", 0))
            span.set_attribute("gen_ai.usage.output_tokens", usage.get("completion_tokens", 0))
            span.set_attribute("gen_ai.usage.total_tokens", usage.get("total_tokens", 0))

        return {
            "anonymized_markdown": content,
            "usage": usage,
            "model": config.ANONYMIZER_DEPLOYMENT,
            "prompt_version": config.ANONYMIZER_PROMPT_VERSION,
            "hash": hashlib.sha256((content or "").encode("utf-8")).hexdigest(),
        }
