"""Category Assessment API - AI-powered category definition advice using GPT-5 Nano."""

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

from classymail.core import config
from classymail.core.llm_compat import build_chat_params, is_reasoning_model
from classymail.services.azure_clients import auth_headers, Clients
from classymail.services.llm_pipeline import resolve_model_config

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
    AI-powered category definition assessment using GPT-5 Nano.

    Analyzes category name, description, and exclusions against best practices
    and provides actionable advice for improvement.
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
            # Use GPT-5 Nano for assessment
            endpoint, deployment = resolve_model_config("gpt-5-nano")

            if not endpoint or not deployment:
                raise HTTPException(
                    status_code=503,
                    detail="GPT-5 Nano model not configured. Please configure in Settings."
                )

            clients = Clients()
            headers = await auth_headers(clients=clients)
            url = f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/chat/completions?api-version={config.AI_API_VERSION}"

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
            # GPT-5 Nano (Reasoning) budget adjusted to 10k (safe but not excessive).
            payload = {
                "model": deployment,
                "messages": messages,
                **build_chat_params(deployment, temperature=0.3, max_output_tokens=10000),
            }

            # Reasoning models (GPT-5, o1) often do not support 'response_format'={"type": "json_object"}
            if not is_reasoning_model(deployment):
                payload["response_format"] = {"type": "json_object"}

            span.set_attribute("gen_ai.system", "azure_openai")
            span.set_attribute("gen_ai.request.model", deployment)

            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()

                choices = data.get("choices", [])
                if not choices:
                    logger.error(f"[assessment] Invalid AI response: No choices returned. Data: {data}")
                    raise HTTPException(status_code=502, detail="AI Model returned no Content Choices.")

                message = choices[0].get("message", {})
                content = message.get("content")

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
            logger.error(f"[assessment] HTTP error: {e.response.status_code} - {e.response.text[:500]}")
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"LLM assessment failed: {e.response.text[:200]}"
            )
        except json.JSONDecodeError as e:
            logger.error(f"[assessment] JSON parse error: {e} | Raw Content Snippet: {content[:500] if 'content' in locals() and content else 'None'}")
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise HTTPException(
                status_code=500,
                detail=f"Failed to parse LLM response: {str(e)[:100]}"
            )
        except Exception as e:
            logger.error(f"[assessment] Unexpected error: {e}")
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            if isinstance(e, HTTPException):
                raise e
            raise HTTPException(
                status_code=500,
                detail=f"Assessment failed: {str(e)}"
            )
