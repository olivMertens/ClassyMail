from __future__ import annotations

import json
import logging

import httpx
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

from classificationg2s.core import config
from classificationg2s.models import OCRFailed
from classificationg2s.services.azure_clients import auth_headers, Clients
from classificationg2s.services.settings_store import get_categories_prompt_text

logger = logging.getLogger(__name__)

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

    # Schema for Mistral Document AI Annotations
    image_schema = {
        "type": "object",
        "properties": {
            "image_type": {
                "type": "string",
                "description": "The type of the image (e.g. photo, chart, diagram, screenshot, signature, logo, icon, noise). Do NOT use 'document' or 'page'."
            },
            "description": {
                "type": "string",
                "description": "A concise, objective description of the visual content (e.g. 'car with dented bumper', 'water leak on ceiling'). Do NOT describe the text content of the document. Do NOT describe the document itself (e.g. 'a scanned letter'). Only describe distinct visual elements."
            },
            "relevance": {
                "type": "string",
                "description": "Relevance to an insurance claim (High, Medium, Low, Irrelevant)."
            }
        },
        "required": ["image_type", "description", "relevance"]
    }

    # Mistral Document AI uses Chat Completions API with document content
    # https://learn.microsoft.com/en-us/azure/ai-studio/how-to/deploy-models-mistral
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "document": {
                        "type": "document_base64",
                        "document_base64": base64_pdf
                    }
                }
            ]
        }
    ]

    payload = {
        "messages": messages,
        "model": config.MISTRAL_DEPLOYMENT,
        "include_image_base64": False,
        "bbox_annotation_format": {
            "type": "json_schema",
            "json_schema": image_schema
        }
    }

    if not config.MISTRAL_ENDPOINT:
        raise RuntimeError("MISTRAL_ENDPOINT not configured.")

    # Use the standard chat completions endpoint
    url = f"{config.MISTRAL_ENDPOINT.rstrip('/')}/chat/completions?api-version=2024-05-01-preview"

    logger.info(f"[metrics] OCR Request: {url} model={config.MISTRAL_DEPLOYMENT}")

    with tracer.start_as_current_span("mistral_ocr") as span:
        span.set_attribute("gen_ai.system", "mistral")
        span.set_attribute("gen_ai.operation", "chat.completions")
        span.set_attribute("gen_ai.request.model", config.MISTRAL_DEPLOYMENT)
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(url, json=payload, headers=headers)
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as ex:
                logger.error(f"[metrics] OCR Failed: {ex.response.status_code} - {ex.response.text}")
                span.set_status(Status(StatusCode.ERROR))
                span.record_exception(ex)
                raise
            data = resp.json()

            # Extract content from chat completions response
            choices = data.get("choices", [])
            if not choices:
                raise OCRFailed("No choices in response")

            message_content = choices[0].get("message", {}).get("content")
            if not message_content:
                raise OCRFailed("Empty message content")

            # Parse the structured response
            if isinstance(message_content, str):
                try:
                    structured_data = json.loads(message_content)
                except json.JSONDecodeError:
                    # If not JSON, treat as plain markdown
                    structured_data = {"markdown": message_content}
            else:
                structured_data = message_content

            usage_info = data.get("usage", {})
            pages = usage_info.get("pages_processed", 0)

            logger.info(f"[metrics] OCR Success: {pages} pages processed")

            span.set_attribute("gen_ai.usage.pages_processed", pages)
            span.set_attribute("gen_ai.usage.input_tokens", usage_info.get("prompt_tokens", 0))
            span.set_attribute("gen_ai.usage.output_tokens", usage_info.get("completion_tokens", 0))

            content = structured_data.get("markdown") or structured_data.get("content")

            # Extract images/annotations from pages
            annotated_images = []
            if structured_data.get("pages"):
                # Prefer page-level content concatenation if top-level is empty
                if not content:
                    content = "\n\n".join([p.get("markdown", "") for p in structured_data.get("pages", [])])

                # Collect images/annotations from pages
                for page in structured_data.get("pages", []):
                    for img in page.get("images", []):
                        # The annotation fields should be merged into the img object
                        if img.get("description"):
                             annotated_images.append({
                                 "id": img.get("id"),
                                 "page_index": page.get("index", 0),
                                 "image_type": img.get("image_type"),
                                 "description": img.get("description"),
                                 "relevance": img.get("relevance")
                             })

            if not content:
                raise OCRFailed("Empty OCR content")

            return {"markdown": content, "usage": usage_info, "images": annotated_images}


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=1, max=10), retry=retry_if_exception(retryable_httpx))
async def classify_with_phi4(text_markdown: str, *, force_fallback: bool = False, strategy: str = "standard", clients: Clients | None = None) -> dict:
    if not config.PHI_ENDPOINT:
        raise RuntimeError("PHI_ENDPOINT is not set")
    if not config.PHI_FALLBACK_ENDPOINT:
        raise RuntimeError("PHI_FALLBACK_ENDPOINT is not set")

    headers = await auth_headers(clients=clients)

    categories_text = get_categories_prompt_text()

    extra_instructions = ""
    if strategy == "reasoning":
        extra_instructions = "\nIMPORTANT : Adopte une approche 'Step-by-step'. Analyse d'abord le contexte, puis déduis les intentions. Sois très précis sur la justification."
    elif strategy == "vision":
        extra_instructions = "\nNOTE : Le document peut contenir des descriptions d'images. Prends en compte le contexte visuel décrit."

    system_prompt = f"""
Tu es un assistant expert en classification d'emails d'assurance.{extra_instructions}
Ta tâche est d'analyser le contenu de l'email (fourni en markdown) et d'identifier "
- TOUTES les intentions présentes.
- Le sujet principal (Subject).
- L'expéditeur (Sender) si identifiable.

LISTE DES INTENTIONS POSSIBLES :
{categories_text}

RÈGLES DE CLASSIFICATION :
- Un email peut contenir UNE SEULE intention OU PLUSIEURS intentions.
- Si aucune intention ne correspond, retourne une liste vide (detected_intents: []).
- Assigne un score de confiance (0.0 à 1.0) pour CHAQUE intention détectée.

FORMAT DE RÉPONSE ATTENDU (JSON UNIQUEMENT) :
{{
    "detected_intents": [
        {{
            "intent": "Nom de l'intention",
            "confidence": 0.95,
            "justification": "Court extrait du texte justifiant ce choix"
        }}
    ],
    "global_complexity": "Simple|Complexe",
    "subject": "Sujet ou Objet de l'email extrait du texte",
    "sender": "Nom ou Email de l'expéditeur extrait"
}}
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

    logger.info(f"[metrics] Classify Request: {chosen_deployment} strategy={strategy} fallback={use_fallback}")
    logger.info(f"[metrics] Token Estimate: system={system_tokens} user={user_tokens_est} truncated={truncated}")

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

                logger.error(f"[metrics] Classify Failed: {status} - {body}")

                if (
                    (not use_fallback)
                    and status in (400, 413)
                    and ("context" in body.lower() or "token" in body.lower() or "length" in body.lower())
                ):
                    logger.warning("[metrics] Token limit reached! Retrying with fallback model.")
                    return await classify_with_phi4(text_markdown, force_fallback=True)
                raise

            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
            usage = data.get("usage", {})

            logger.info(f"[metrics] Classify Success: {usage.get('total_tokens', 0)} tokens used")
            # Log the first 100 chars of content just to see if it looks like JSON
            logger.info(f"[metrics] Response preview: {content[:100]}...")

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


async def analyze_correction(
    text_markdown: str,
    old_intents: list[dict],
    new_intents: list[dict],
    reason: str,
    clients: Clients | None = None
) -> str | None:
    """
    Uses Phi-4 to analyze the human correction and provide insights for prompt reinforcement.
    """
    if not config.PHI_ENDPOINT or not reason:
        return None

    system_prompt = """
Tu es un expert en amélioration de classification automatique.
Un utilisateur humain a corrigé la classification d'un email faite par une IA.
Ta tâche est d'analyser la correction et le commentaire de l'utilisateur pour générer une "Leçon Apprise" concise.
Cette leçon servira à améliorer le prompt système futur.

FORMAT DE SORTIE :
Une seule phrase ou un court paragraphe expliquant la nuance manquée par l'IA.
Exemple : "L'IA a manqué l'intention 'Résiliation' car le terme utilisé était 'clôture de compte' dans le contexte d'un décès."
"""

    user_content = f"""
EMAIL :
{text_markdown[:2000]}... (tronqué)

CLASSIFICATION IA (Précédente) :
{json.dumps(old_intents, ensure_ascii=False)}

CLASSIFICATION HUMAINE (Corrigée) :
{json.dumps(new_intents, ensure_ascii=False)}

RAISON DE L'UTILISATEUR :
{reason}

Analyse cette correction.
    """

    headers = await auth_headers(clients=clients)
    payload = {
        "model": config.PHI_DEPLOYMENT,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.3,
        "max_tokens": 150,
    }

    url = f"{config.PHI_ENDPOINT}/openai/deployments/{config.PHI_DEPLOYMENT}/chat/completions?api-version={config.AI_API_VERSION}"

    try:
        async with httpx.AsyncClient(timeout=10) as client: # Fast timeout for UI responsiveness
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
    except Exception:
        pass

    return None
