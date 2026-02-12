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

router = APIRouter()
logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class CategoryAssessmentRequest(BaseModel):
    """Category assessment request."""
    name: str = Field(..., description="Category display name")
    slug: str = Field(..., description="Category technical slug")
    description: str | None = Field(default="", description="Category definition (what it IS)")
    exclusions: str | None = Field(default="", description="Category exclusions (what it ISN'T)")
    language: str = Field(default="en", description="Response language: 'en' or 'fr'")


class CategoryAssessmentResponse(BaseModel):
    """Category assessment response."""
    advice: str = Field(..., description="AI-generated advice for improving the category")
    quality_score: str = Field(..., description="Quality assessment (Good/Needs Improvement/Poor)")
    specific_suggestions: list[str] = Field(default_factory=list, description="Specific improvement suggestions")


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
            # Resolve assessment model: settings > env > default (gpt-4.1-nano)
            import os
            settings = load_settings()
            assessment_model = (
                settings.get("ai_assessment_model")
                or os.getenv("ASSESSMENT_MODEL")
                or DEFAULT_ASSESSMENT_MODEL
            )
            endpoint, deployment, api_version = resolve_model_config(assessment_model)
            logger.info("[assessment] Resolved model: endpoint=%s deployment=%s api_version=%s", endpoint, deployment, api_version)

            if not endpoint or not deployment:
                raise HTTPException(
                    status_code=503,
                    detail=f"Assessment model '{assessment_model}' not configured. Set ai_assessment_model in Settings or deploy the model in Azure AI Foundry."
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

            # Bilingual prompt with WHERE/HOW guidance - Language-aware
            is_french = request.language == "fr"

            if is_french:
                system_prompt = """Vous êtes un expert en taxonomies de classification d'emails d'assurance.
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
- "RÉÉCRIRE le champ 'Définition' (remplacer tout le contenu actuel par): DEFINITION Attestation d'habitation: document officiel permettant de confirmer l'adresse. Sont couverts: logement principal, logement étudiant. Mots-clés: bail, quittance, loyer, attestation habitation"
- "AJOUTER à la FIN du champ 'Définition' (après le dernier mot existant): , signature, photo, date de naissance"
- "RÉÉCRIRE le champ 'Exclusions' (remplacer tout le contenu actuel par): EXCLUSIONS - Ne concerne pas les résidences secondaires. - Ne couvre pas les biens non couverts par l'assurance habitation."

IMPORTANT:
- Spécifiez TOUJOURS si c'est dans le champ "Définition" ou "Exclusions"
- Précisez si c'est "RÉÉCRIRE tout le contenu" ou "AJOUTER à la fin"
- Pour "AJOUTER", formatez comme: , mot1, mot2, mot3 (avec virgule initiale)
- Sortie JSON UNIQUEMENT.
"""
            else:
                system_prompt = """You are an expert in insurance email classification taxonomies.
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
- "REWRITE the 'Exclusions' field (replace entire current content with): EXCLUSIONS - Does not concern secondary residences. - Does not cover properties not covered by home insurance."

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
            token_budget = 10000 if is_reasoning_model(deployment) else 2000
            payload = {
                "model": deployment,
                "messages": messages,
                **build_chat_params(deployment, temperature=0.3, max_output_tokens=token_budget),
            }

            # Reasoning models (GPT-5, o1) often do not support 'response_format'={"type": "json_object"}
            if not is_reasoning_model(deployment):
                payload["response_format"] = {"type": "json_object"}

            span.set_attribute("gen_ai.system", "azure_openai")
            span.set_attribute("gen_ai.request.model", deployment)

            logger.info("[assessment] Calling LLM for category '%s' (model=%s, reasoning=%s)",
                        name, deployment, is_reasoning_model(deployment))

            # Reasoning models need longer timeout; classic models respond in 2-5s
            timeout_s = 90 if is_reasoning_model(deployment) else 30
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

                return CategoryAssessmentResponse(
                    advice=result.get("advice", "Assessment completed."),
                    quality_score=result.get("quality_score", "Unknown"),
                    specific_suggestions=result.get("specific_suggestions", [])
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
