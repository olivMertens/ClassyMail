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

            # System prompt with best practices - Optimized for GPT-5 Nano efficiency
            system_prompt = """You are an expert in insurance email classification taxonomies.
Assess the category definition below and provide actionable PROMPT-READY improvements.

ASSESSMENT CRITERIA:
1. Definition: Must use specific keywords (e.g., "bail, quittance" instead of "documents logement").
2. Exclusions: Must be explicit (e.g., "Ne concerne pas X").
3. Structure: Use "DEFINITION" and "EXCLUSIONS" headers.
4. Validation Strategies: Mention standard keywords and visual cues (e.g., "photo", "signature").

RESPONSE FORMAT (JSON ONLY):
{
  "quality_score": "Good|Needs Improvement|Poor",
  "advice": "Concise explanation of what to fix and why.",
  "specific_suggestions": [
     "REWRITE Definition: [New text]",
     "ADD Exclusions: [New text]",
     "ADD Keywords: [List]"
  ]
}

CRITICAL:
- Output JSON ONLY.
- Be CONCISE.
- Do not explain your reasoning process in the output, just the results.
"""

            user_content = f"""**Category Name:** {request.name}
**Slug:** {request.slug}

**Current DEFINITION:**
{request.description or "(empty)"}

**Current EXCLUSIONS:**
{request.exclusions or "(empty)"}

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
