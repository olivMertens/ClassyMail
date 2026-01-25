from __future__ import annotations

import json

import httpx
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

from classificationg2s.core import config
from classificationg2s.models import OCRFailed
from classificationg2s.services.azure_clients import auth_headers, Clients


tracer = trace.get_tracer(__name__)


def retryable_httpx(exc: Exception) -> bool:
    return (
        isinstance(exc, httpx.HTTPStatusError)
        and exc.response is not None
        and exc.response.status_code in (429, 500, 502, 503, 504)
    )


def estimate_tokens_rough(text: str) -> int:
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


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=1, max=10), retry=retry_if_exception(retryable_httpx))
async def ocr_with_mistral(base64_pdf: str, clients: Clients | None = None) -> dict:
    headers = await auth_headers(clients=clients)
    payload = {
        "model": config.MISTRAL_DEPLOYMENT,
        "document": {
            "type": "document_base64",
            "document_base64": base64_pdf,
        },
    }

    if config.MISTRAL_MODE.lower() == "maas":
        url = f"{config.MISTRAL_ENDPOINT}/v1/ocr"
    else:
        url = f"{config.MISTRAL_ENDPOINT}/models/{config.MISTRAL_DEPLOYMENT}:ocr"

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


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=1, max=10), retry=retry_if_exception(retryable_httpx))
async def classify_with_phi4(text_markdown: str, *, force_fallback: bool = False, clients: Clients | None = None) -> dict:
    if not config.PHI_ENDPOINT:
        raise RuntimeError("PHI_ENDPOINT is not set")
    if not config.PHI_FALLBACK_ENDPOINT:
        raise RuntimeError("PHI_FALLBACK_ENDPOINT is not set")

    headers = await auth_headers(clients=clients)

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

    max_user_primary = max(
        500,
        config.PHI_PRIMARY_MAX_INPUT_TOKENS - config.PHI_RESERVED_OUTPUT_TOKENS - system_tokens - overhead_tokens,
    )
    max_user_fallback = max(
        500,
        config.PHI_FALLBACK_MAX_INPUT_TOKENS - config.PHI_RESERVED_OUTPUT_TOKENS - system_tokens - overhead_tokens,
    )

    use_fallback = force_fallback or (user_tokens_est > max_user_primary)
    chosen_endpoint = config.PHI_FALLBACK_ENDPOINT if use_fallback else config.PHI_ENDPOINT
    chosen_deployment = config.PHI_FALLBACK_DEPLOYMENT if use_fallback else config.PHI_DEPLOYMENT
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
        "max_tokens": config.PHI_RESERVED_OUTPUT_TOKENS,
    }

    url = f"{chosen_endpoint}/openai/deployments/{chosen_deployment}/chat/completions?api-version={config.AI_API_VERSION}"

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
                if (
                    (not use_fallback)
                    and status in (400, 413)
                    and ("context" in body.lower() or "token" in body.lower() or "length" in body.lower())
                ):
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
    import logging

    try:
        data = agent_response if isinstance(agent_response, dict) else json.loads(agent_response)
        intents = data.get("detected_intents", [])
        needs_review = False
        if not intents:
            needs_review = True
        for item in intents:
            if item.get("confidence", 0) < 0.9:
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
