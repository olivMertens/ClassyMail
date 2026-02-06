"""Category Assessment API - AI-powered category definition advice using GPT-5 Nano."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel, Field

from classymail.core import config
from classymail.services.azure_clients import auth_headers, Clients
from classymail.services.llm_pipeline import resolve_model_config

router = APIRouter()
logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class CategoryAssessmentRequest(BaseModel):
    """Category assessment request."""
    name: str = Field(..., description="Category display name")
    slug: str = Field(..., description="Category technical slug")
    description: str = Field(default="", description="Category definition (what it IS)")
    exclusions: str = Field(default="", description="Category exclusions (what it ISN'T)")


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
        span.set_attribute("category.name", request.name)
        span.set_attribute("category.slug", request.slug)

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

            # System prompt with best practices
            system_prompt = """You are a classification taxonomy expert specialized in insurance and customer service categories, with deep expertise in LLM prompt engineering.

Your task is to assess category definitions for email classification systems and provide professional, actionable advice formatted for direct integration into LLM prompts.

ASSESSMENT CRITERIA (LLM-Optimized Best Practices):

1. **Definition (What it IS) - LLM Comprehension:**
   - ✅ GOOD: "Documents certifiant la résidence ou l'assurance habitation : bail, attestation locataire, quittance loyer, police d'assurance logement, justificatif de domicile"
   - ❌ AVOID: "Documents d'habitation" (too vague, LLM needs concrete examples)
   - WHY: LLMs match patterns. Concrete keywords = better classification accuracy
   - FORMAT: Use semicolons for separation, list 5-8 specific terms

2. **Exclusions (What it ISN'T) - Boundary Precision:**
   - ✅ GOOD: "Ne concerne pas les attestations professionnelles ou véhicules"
   - ❌ AVOID: "Autres documents exclus" (too generic)
   - WHY: Explicit negatives prevent false positives in ambiguous cases
   - FORMAT: "Ne concerne pas X, Y, Z. Ne pas inclure A quand B."

3. **Prompt-Ready Structure:**
   - Use DEFINITION/EXCLUSIONS format (system understands this structure)
   - Start definitions with action verbs or document types
   - Keep sentences declarative, not interrogative
   - Avoid emojis, markdown formatting (breaks prompt parsing)

4. **LLM Processing Efficiency:**
   - 50-200 words optimal for DEFINITION (too short = ambiguous, too long = diluted signal)
   - 20-100 words for EXCLUSIONS (focus on top 3 confusion points)
   - Front-load most distinctive keywords in first 2 sentences

5. **Multi-Strategy Validation:**
   - Standard (text): needs keyword density
   - Reasoning (CoT): needs logical structure ("when X, then classify as Y")
   - Vision: needs visual cue mentions ("photo de", "signature", "tampon")

YOUR ADVICE MUST INCLUDE:
- Concrete rewriting examples: "Replace [current text] with [improved text]"
- Explain WHY each change helps LLM comprehension
- Provide ready-to-use text snippets the user can copy-paste
- Flag missing elements (keywords, edge cases, visual cues)

RESPONSE FORMAT (JSON):
{
  "quality_score": "Good|Needs Improvement|Poor",
  "advice": "Professional assessment explaining WHAT to change and WHY it improves LLM performance. Include 1-2 concrete rewriting examples with before/after comparisons.",
  "specific_suggestions": [
    "REWRITE Definition: Replace 'X' with 'Y: [concrete example]' because [LLM reason]",
    "ADD Exclusions: Include 'Ne concerne pas [specific case]' to prevent confusion with [overlapping category]",
    "ENHANCE Keywords: Add visual cues like 'photo', 'signature' for Vision strategy",
    "OPTIMIZE Length: Current definition is [too short/too long], target 50-200 words"
  ]
}

CRITICAL: Each suggestion must be actionable (user can implement immediately) and pedagogical (user understands WHY it works for LLMs)."""

            user_content = f"""Assess this category definition for an insurance email classification system optimized for LLM prompt comprehension:

**Category Name:** {request.name}
**Technical Slug:** {request.slug}

**Current DEFINITION (What it IS):**
{request.description or "(empty - CRITICAL ISSUE)"}

**Current EXCLUSIONS (What it ISN'T):**
{request.exclusions or "(empty - missing boundary specification)"}

**Your Task:**
1. Rate quality: Good / Needs Improvement / Poor
2. Provide actionable advice with concrete rewriting examples
3. Explain WHY each suggestion improves LLM classification accuracy
4. Format all text snippets as copy-paste ready for direct use in prompts
5. Consider Standard (text), Reasoning (CoT), and Vision (image) strategies

Focus on: keyword density, boundary precision, prompt structure, and LLM comprehension patterns."""

            payload = {
                "model": deployment,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                "temperature": 0.3,  # Low temperature for consistent advice
                "max_tokens": 1500,
                "response_format": {"type": "json_object"}
            }

            span.set_attribute("gen_ai.system", "azure_openai")
            span.set_attribute("gen_ai.request.model", deployment)

            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()

                content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")

                # Parse JSON response
                import json
                result = json.loads(content)

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
            logger.error(f"[assessment] JSON parse error: {e}")
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise HTTPException(
                status_code=500,
                detail="Failed to parse LLM response"
            )
        except Exception as e:
            logger.error(f"[assessment] Unexpected error: {e}")
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise HTTPException(
                status_code=500,
                detail=f"Assessment failed: {str(e)}"
            )
