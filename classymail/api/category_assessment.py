"""Category Assessment API - AI-powered category definition advice."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel, Field

from classymail.core.llm_compat import build_chat_params, extract_message_content, is_reasoning_model
from classymail.services.azure_clients import auth_headers, Clients
from classymail.services.llm_pipeline import resolve_model_config
from classymail.services.settings_store import load_settings

# Default assessment model: gpt-4.1-nano is 10-20x faster than gpt-5-nano
# for structured evaluation tasks (no reasoning overhead needed).
# Override via Settings > ai_assessment_model or env ASSESSMENT_MODEL.
DEFAULT_ASSESSMENT_MODEL = "gpt-4.1-nano"

# UI language names for non-FR/EN prompt suffix
LANGUAGE_NAMES: dict[str, str] = {
    "fr": "français",
    "en": "English",
    "de": "Deutsch",
    "es": "español",
    "it": "italiano",
}

router = APIRouter()
logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


def _parse_suggestion(text: str) -> dict[str, str]:
    """Parse a freeform suggestion string into structured {action, field, content}.

    Handles all supported UI languages (FR, EN, DE, ES, IT) action keywords so
    that the frontend Apply button works regardless of the model or language.

    Returns a dict with:
      - action: "rewrite" | "add"
      - field:  "definition" | "exclusions"
      - content: the text to apply to the category field
    """
    t = text.strip()

    # Detect action: multilingual REWRITE or ADD
    is_add = bool(re.match(
        r"^(?:AJOUTER|ADD\b|HINZUF[UÜ]GEN|A[NÑ]ADIR|AGGIUNGERE)",
        t, re.I,
    ))
    # Default to rewrite if not explicitly ADD
    action = "add" if is_add else "rewrite"

    # Detect field: Definition or Exclusions (multilingual field names)
    is_exclusions = bool(re.search(
        r"['\"]?(?:Exclusions?|Ausschl[uü]sse?|Esclusioni)['\"]?",
        t, re.I,
    ))
    field = "exclusions" if is_exclusions else "definition"

    # Extract content after "): " (preferred) or first ": "
    content = ""
    paren_match = re.search(r"\)\s*:\s*(.+)$", t, re.S)
    if paren_match:
        content = paren_match.group(1).strip()
    else:
        colon_match = re.search(r":\s*(.+)$", t, re.S)
        if colon_match:
            content = colon_match.group(1).strip()

    # Strip leading DEFINITION/EXCLUSIONS labels (multilingual)
    content = re.sub(r"^DEFINITION\s+", "", content, flags=re.I)
    content = re.sub(r"^DEFINICI[OÓ]N\s+", "", content, flags=re.I)
    content = re.sub(r"^DEFINIZIONE\s+", "", content, flags=re.I)
    content = re.sub(r"^EXCLUSIONS?\s*[-–]\s*", "", content, flags=re.I)
    content = re.sub(r"^AUSSCHL[UÜ]SSE?\s*[-–]\s*", "", content, flags=re.I)
    content = re.sub(r"^ESCLUSIONI\s*[-–]\s*", "", content, flags=re.I)

    return {"action": action, "field": field, "content": content}


class CategoryAssessmentRequest(BaseModel):
    """Category assessment request."""
    name: str = Field(..., description="Category display name")
    slug: str = Field(..., description="Category technical slug")
    description: str | None = Field(default="", description="Category definition (what it IS)")
    exclusions: str | None = Field(default="", description="Category exclusions (what it ISN'T)")
    language: str = Field(default="en", description="Response language: 'en' or 'fr'")
    model: str | None = Field(default=None, description="Override assessment model (e.g. 'gpt-5-nano', 'phi4')")


class SuggestionParsed(BaseModel):
    """Server-parsed suggestion with structured action/field/content."""
    action: str = Field(..., description="Action: 'rewrite' or 'add'")
    field: str = Field(..., description="Target field: 'definition' or 'exclusions'")
    content: str = Field(..., description="Content to apply to the field")


class CategoryAssessmentResponse(BaseModel):
    """Category assessment response."""
    advice: str = Field(..., description="AI-generated advice for improving the category")
    quality_score: str = Field(..., description="Quality assessment (Good/Needs Improvement/Poor)")
    specific_suggestions: list[str] = Field(default_factory=list, description="Specific improvement suggestions (display text)")
    parsed_suggestions: list[SuggestionParsed] = Field(default_factory=list, description="Parsed suggestions with action/field/content for Apply button")


@router.post("/api/admin/assess-category", response_model=CategoryAssessmentResponse)
async def assess_category(request: CategoryAssessmentRequest) -> dict[str, Any]:
    """
    AI-powered category definition assessment.

    Uses a fast non-reasoning model by default (gpt-4.1-nano) for quick
    structured evaluation. Configurable via settings.ai_assessment_model.
    """
    with tracer.start_as_current_span("assess_category") as span:
        # Normalize None → empty string for safety
        description = (request.description or "").strip()
        exclusions = (request.exclusions or "").strip()
        name = request.name.strip()
        slug = request.slug.strip()

        span.set_attribute("category.name", name)
        span.set_attribute("category.slug", slug)

        try:
            # Resolve assessment model: request > settings > env > default (gpt-4.1-nano)
            import os
            settings = load_settings()
            assessment_model = (
                request.model
                or settings.get("ai_assessment_model")
                or os.getenv("ASSESSMENT_MODEL")
                or DEFAULT_ASSESSMENT_MODEL
            )
            endpoint, deployment, api_version = resolve_model_config(assessment_model)
            logger.info("[assessment] Resolved model: endpoint=%s deployment=%s api_version=%s", endpoint, deployment, api_version)

            if not endpoint or not deployment:
                raise HTTPException(
                    status_code=503,
                    detail=f"Assessment model '{assessment_model}' not configured. Set ai_assessment_model in Settings or deploy the model in Microsoft AI Foundry."
                )

            clients = Clients()
            try:
                headers = await auth_headers(clients=clients)
            except Exception as auth_err:
                err_type = type(auth_err).__name__
                err_msg = str(auth_err) or "(no details)"
                logger.error("[assessment] Authentication failed: %s: %s", err_type, err_msg)
                raise HTTPException(
                    status_code=401,
                    detail=f"Azure authentication failed ({err_type}): {err_msg[:200]}"
                )
            url = f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
            logger.debug("[assessment] Request URL: %s", url)

            # Multilingual prompt with WHERE/HOW guidance
            lang = request.language or "en"
            is_french = lang == "fr"

            if is_french:
                system_prompt = """Vous êtes un expert en taxonomies de classification d'emails d'service.
Évaluez la définition de catégorie ci-dessous et fournissez des améliorations ACTIONNABLES.

CRITÈRES D'ÉVALUATION:
1. Définition: Doit utiliser des mots-clés spécifiques (ex: "bail, quittance" au lieu de "documents logement").
2. Exclusions: Doivent être explicites (ex: "Ne concerne pas X").
3. Structure: Utiliser les en-têtes "DEFINITION" et "EXCLUSIONS".
4. Indices de Validation: Mentionner les mots-clés standards et indices visuels (ex: "photo", "signature").

FORMAT DE RÉPONSE (JSON UNIQUEMENT):
{
  "quality_score": "Good|Needs Improvement|Poor",
  "advice": "Explication concise de ce qu'il faut corriger et pourquoi.",
  "specific_suggestions": [
     "RÉÉCRIRE le champ 'Définition' (remplacer tout le contenu actuel par): DEFINITION [nouveau texte complet]",
     "RÉÉCRIRE le champ 'Exclusions' (remplacer tout le contenu actuel par): EXCLUSIONS - Ne concerne pas...",
     "AJOUTER à la FIN du champ 'Définition' (après le dernier mot-clé existant): [mots-clés séparés par virgules]"
  ]
}

EXEMPLES DE SUGGESTIONS ULTRA-PRÉCISES:
- "RÉÉCRIRE le champ 'Définition' (remplacer tout le contenu actuel par): DEFINITION Attestation d'habitation: document officiel permettant de confirmer l'adresse. Sont couverts: logement principal, logement étudiant. Mots-clés: bail, quittance, loyer, billing inquiry"
- "AJOUTER à la FIN du champ 'Définition' (après le dernier mot existant): , signature, photo, date de naissance"
- "RÉÉCRIRE le champ 'Exclusions' (remplacer tout le contenu actuel par): EXCLUSIONS - Ne concerne pas les résidences secondaires. - Ne couvre pas les biens non couverts par l'home service."

IMPORTANT:
- Spécifiez TOUJOURS si c'est dans le champ "Définition" ou "Exclusions"
- Précisez si c'est "RÉÉCRIRE tout le contenu" ou "AJOUTER à la fin"
- Pour "AJOUTER", formatez comme: , mot1, mot2, mot3 (avec virgule initiale)
- Sortie JSON UNIQUEMENT.
"""
            else:
                system_prompt = """You are an expert in email classification taxonomies.
Assess the category definition below and provide actionable PROMPT-READY improvements.

ASSESSMENT CRITERIA:
1. Definition: Must use specific keywords (e.g., "bail, quittance" instead of "documents logement").
2. Exclusions: Must be explicit (e.g., "Does not concern X").
3. Structure: Use "DEFINITION" and "EXCLUSIONS" headers.
4. Validation Cues: Mention standard keywords and visual cues (e.g., "photo", "signature").

RESPONSE FORMAT (JSON ONLY):
{
  "quality_score": "Good|Needs Improvement|Poor",
  "advice": "Concise explanation of what to fix and why.",
  "specific_suggestions": [
     "REWRITE the 'Definition' field (replace entire current content with): DEFINITION [complete new text]",
     "REWRITE the 'Exclusions' field (replace entire current content with): EXCLUSIONS - Does not concern...",
     "ADD to the END of 'Definition' field (after last existing keyword): [keywords separated by commas]"
  ]
}

EXAMPLES OF ULTRA-PRECISE SUGGESTIONS:
- "REWRITE the 'Definition' field (replace entire current content with): DEFINITION Housing certificate: official document confirming address and housing status. Covers: main residence, student housing. Keywords: lease, receipt, rent, housing certificate"
- "ADD to the END of 'Definition' field (after last existing word): , signature, photo, date of birth"
- "REWRITE the 'Exclusions' field (replace entire current content with): EXCLUSIONS - Does not concern secondary residences. - Does not cover properties not covered by home business."

IMPORTANT:
- ALWAYS specify if it's in "Definition" or "Exclusions" field
- Clarify if it's "REWRITE entire content" or "ADD to the end"
- For "ADD", format as: , word1, word2, word3 (with initial comma)
- Output JSON ONLY.
"""

            user_content = f"""**Category Name:** {name}
**Slug:** {slug}

**Current DEFINITION:**
{description or "(empty)"}

**Current EXCLUSIONS:**
{exclusions or "(empty)"}

Assess quality and provide rewrites."""

            # For non-FR/EN locales, append language instruction so the
            # model responds in the user's language while keeping the
            # same suggestion format.
            if lang not in ("fr", "en"):
                lang_name = LANGUAGE_NAMES.get(lang, lang)
                user_content += (
                    f"\n\nIMPORTANT: Respond entirely in {lang_name}. "
                    "Keep the same suggestion format (start each suggestion with "
                    "the equivalent of REWRITE or ADD in the target language, "
                    "followed by 'Definition' or 'Exclusions' field name)."
                )

            # Prepare content based on model capabilities
            if is_reasoning_model(deployment):
                # Reasoning models (e.g., GPT-5, o1) often restrict 'system' messages.
                # Combine instructions into the user prompt for compatibility.
                messages = [
                    {"role": "user", "content": f"{system_prompt}\n\n---\n\n{user_content}"}
                ]
            else:
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ]

            # Detect model family for correct API parameters
            # Classic models: 2000 tokens is plenty for structured JSON advice.
            # Reasoning models: keep 10k budget for thinking overhead.
            # SLMs (Phi-4): need more tokens (3000) as they tend to be more verbose.
            _d_lower = deployment.lower()
            _is_slm = any(s in _d_lower for s in ("phi", "mistral", "llama"))
            if is_reasoning_model(deployment):
                token_budget = 10000
            elif _is_slm:
                token_budget = 3000
            else:
                token_budget = 2000
            payload = {
                "model": deployment,
                "messages": messages,
                **build_chat_params(deployment, temperature=0.3, max_output_tokens=token_budget),
            }

            # response_format=json_object: supported by OpenAI models, but some
            # SLMs (Phi-4 on Microsoft AI Foundry) may not support it.  Skip for SLMs
            # to avoid 4xx errors; the JSON cleanup logic handles raw output.
            if not is_reasoning_model(deployment) and not _is_slm:
                payload["response_format"] = {"type": "json_object"}

            span.set_attribute("gen_ai.system", "azure_openai")
            span.set_attribute("gen_ai.request.model", deployment)

            logger.info("[assessment] Calling LLM for category '%s' (model=%s, reasoning=%s)",
                        name, deployment, is_reasoning_model(deployment))

            # Timeout per model family:
            # - Reasoning models (o1/o3/o4/gpt-5): 120s (thinking overhead)
            # - SLMs (phi-4, mistral): 90s (smaller GPU, slower inference)
            # - Fast classic models (gpt-4.1-nano, gpt-4o-mini): 30s
            if is_reasoning_model(deployment):
                timeout_s = 120
            elif _is_slm:
                timeout_s = 90
            else:
                timeout_s = 30
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()

                choices = data.get("choices", [])
                if not choices:
                    logger.error(f"[assessment] Invalid AI response: No choices returned. Data: {data}")
                    raise HTTPException(status_code=502, detail="AI Model returned no Content Choices.")

                message = choices[0].get("message", {})
                content = extract_message_content(message)

                if not content:
                    logger.error(f"[assessment] Invalid AI response: Empty content. Finish reason: {choices[0].get('finish_reason')}. Data: {data}")
                    detail_msg = f"AI Model returned empty content (Finish Reason: {choices[0].get('finish_reason', 'unknown')})."
                    if choices[0].get('finish_reason') == 'length':
                        detail_msg += " The model exhausted its token limit (10k) while reasoning. The prompt has been optimized to reduce overhead."
                    raise HTTPException(status_code=502, detail=detail_msg)

                # Parse JSON response – cleanup potential markdown or whitespace
                cleaned = content.strip()
                # Check for code fence first as it's cleaner
                fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", cleaned, re.DOTALL)
                if fence_match:
                    cleaned = fence_match.group(1).strip()
                elif re.search(r"^\{.*\}$", cleaned, re.DOTALL):
                     pass # Already looks like JSON
                else:
                     # Try finding outermost JSON object
                     json_match = re.search(r"(\{.*\})", cleaned, re.DOTALL)
                     if json_match:
                         cleaned = json_match.group(1).strip()

                try:
                    result = json.loads(cleaned)
                except json.JSONDecodeError:
                    # Retry with raw content just in case extraction failed but it was valid
                    try:
                        result = json.loads(content)
                    except json.JSONDecodeError:
                         raise # Re-raise original error to be caught below

                span.set_status(Status(StatusCode.OK))
                logger.info(f"[assessment] Category '{request.name}' assessed with score: {result.get('quality_score', 'Unknown')}")

                suggestions_raw = result.get("specific_suggestions", [])
                # Ensure all suggestions are strings
                suggestions = [str(s) if not isinstance(s, str) else s for s in suggestions_raw]
                # Parse each suggestion server-side for robust multilingual Apply
                parsed = [_parse_suggestion(s) for s in suggestions]

                return CategoryAssessmentResponse(
                    advice=result.get("advice", "Assessment completed."),
                    quality_score=result.get("quality_score", "Unknown"),
                    specific_suggestions=suggestions,
                    parsed_suggestions=[
                        SuggestionParsed(**p) for p in parsed
                    ],
                )

        except httpx.HTTPStatusError as e:
            err_body = e.response.text[:500] if e.response.text else "(empty body)"
            logger.error("[assessment] HTTP %s from LLM: %s", e.response.status_code, err_body)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"LLM assessment failed (HTTP {e.response.status_code}): {err_body[:200]}"
            )
        except json.JSONDecodeError as e:
            raw_snippet = content[:500] if 'content' in locals() and content else 'None'
            logger.error("[assessment] JSON parse error: %s | Raw: %s", e, raw_snippet)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise HTTPException(
                status_code=500,
                detail=f"Failed to parse LLM response as JSON: {str(e)[:100]}"
            )
        except HTTPException:
            raise  # Already formatted, propagate as-is
        except Exception as e:
            err_type = type(e).__name__
            err_msg = str(e) or "(no details)"
            logger.error("[assessment] %s: %s", err_type, err_msg, exc_info=True)
            span.set_status(Status(StatusCode.ERROR, f"{err_type}: {err_msg}"))
            span.record_exception(e)
            raise HTTPException(
                status_code=500,
                detail=f"Assessment failed ({err_type}): {err_msg[:200]}"
            )
