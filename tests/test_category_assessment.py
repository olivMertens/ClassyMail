"""
Tests for AI-powered category assessment API endpoint.

Tests cover GPT-5 Nano category assessment, JSON parsing, error handling,
and interaction with Azure OpenAI.
"""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

from classymail.api.category_assessment import assess_category, CategoryAssessmentRequest


@pytest.mark.asyncio
async def test_assess_category_success():
    """Test successful category assessment with valid response."""
    request = CategoryAssessmentRequest(
        name="Documents Logement",
        slug="documents_logement",
        description="Documents relatifs au logement",
        exclusions="Ne concerne pas les factures"
    )

    # Mock resolve_model_config
    with patch("classymail.api.category_assessment.resolve_model_config") as mock_resolve, \
         patch("classymail.api.category_assessment.Clients"), \
         patch("classymail.api.category_assessment.auth_headers") as mock_auth_headers:

        mock_resolve.return_value = ("https://test.openai.azure.com", "gpt-5-nano")
        mock_auth_headers.return_value = {"Authorization": "Bearer test-token"}

        # Mock httpx response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "quality_score": "Needs Improvement",
                            "advice": "Use specific keywords like 'bail, quittance' instead of generic terms.",
                            "specific_suggestions": [
                                "REWRITE Definition: Documents de logement incluant bail, quittance de loyer",
                                "ADD Exclusions: Ne concerne pas les factures d'énergie",
                                "ADD Keywords: bail, quittance, logement"
                            ]
                        })
                    },
                    "finish_reason": "stop"
                }
            ]
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await assess_category(request)

            assert result.quality_score == "Needs Improvement"
            assert "specific keywords" in result.advice.lower()
            assert len(result.specific_suggestions) == 3
            assert any("REWRITE" in s for s in result.specific_suggestions)


@pytest.mark.asyncio
async def test_assess_category_good_quality():
    """Test assessment of a well-defined category."""
    request = CategoryAssessmentRequest(
        name="Bail et Quittances",
        slug="bail_quittances",
        description="DEFINITION: Documents contractuels de location incluant bail, quittance de loyer, avis d'échéance.",
        exclusions="EXCLUSIONS: Ne concerne pas les factures d'énergie, taxes foncières, ou travaux."
    )

    with patch("classymail.api.category_assessment.resolve_model_config") as mock_resolve, \
         patch("classymail.api.category_assessment.Clients"), \
         patch("classymail.api.category_assessment.auth_headers") as mock_auth_headers:

        mock_resolve.return_value = ("https://test.openai.azure.com", "gpt-5-nano")
        mock_auth_headers.return_value = {"Authorization": "Bearer test-token"}

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "quality_score": "Good",
                            "advice": "Category definition is clear with specific keywords and well-defined exclusions.",
                            "specific_suggestions": []
                        })
                    },
                    "finish_reason": "stop"
                }
            ]
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await assess_category(request)

            assert result.quality_score == "Good"
            assert len(result.specific_suggestions) == 0


@pytest.mark.asyncio
async def test_assess_category_empty_fields():
    """Test assessment of category with empty description and exclusions."""
    request = CategoryAssessmentRequest(
        name="Nouvelle Categorie",
        slug="nouvelle_categorie",
        description="",
        exclusions=""
    )

    with patch("classymail.api.category_assessment.resolve_model_config") as mock_resolve, \
         patch("classymail.api.category_assessment.Clients"), \
         patch("classymail.api.category_assessment.auth_headers") as mock_auth_headers:

        mock_resolve.return_value = ("https://test.openai.azure.com", "gpt-5-nano")
        mock_auth_headers.return_value = {"Authorization": "Bearer test-token"}

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "quality_score": "Poor",
                            "advice": "Category lacks definition and exclusions. Add specific keywords and examples.",
                            "specific_suggestions": [
                                "ADD Definition: Specify what documents or types this category includes",
                                "ADD Exclusions: Clarify what this category does NOT cover",
                                "ADD Keywords: List specific terms to search for"
                            ]
                        })
                    },
                    "finish_reason": "stop"
                }
            ]
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await assess_category(request)

            assert result.quality_score == "Poor"
            assert len(result.specific_suggestions) == 3


@pytest.mark.asyncio
async def test_assess_category_model_not_configured():
    """Test error when GPT-5 Nano is not configured."""
    from fastapi import HTTPException

    request = CategoryAssessmentRequest(
        name="Test Category",
        slug="test_category",
        description="Test description",
        exclusions=""
    )

    with patch("classymail.api.category_assessment.resolve_model_config") as mock_resolve:
        mock_resolve.return_value = (None, None)

        with pytest.raises(HTTPException) as exc_info:
            await assess_category(request)

        assert exc_info.value.status_code == 503
        assert "not configured" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_assess_category_http_error():
    """Test handling of HTTP errors from Azure OpenAI."""
    from fastapi import HTTPException

    request = CategoryAssessmentRequest(
        name="Test Category",
        slug="test_category",
        description="Test",
        exclusions=""
    )

    with patch("classymail.api.category_assessment.resolve_model_config") as mock_resolve, \
         patch("classymail.api.category_assessment.Clients"), \
         patch("classymail.api.category_assessment.auth_headers") as mock_auth_headers:

        mock_resolve.return_value = ("https://test.openai.azure.com", "gpt-5-nano")
        mock_auth_headers.return_value = {"Authorization": "Bearer test-token"}

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 429
            mock_response.text = "Rate limit exceeded"
            mock_client.post = AsyncMock(side_effect=httpx.HTTPStatusError(
                "Rate limit",
                request=MagicMock(),
                response=mock_response
            ))
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with pytest.raises(HTTPException) as exc_info:
                await assess_category(request)

            assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_assess_category_json_parse_error():
    """Test handling of invalid JSON response from model."""
    from fastapi import HTTPException

    request = CategoryAssessmentRequest(
        name="Test Category",
        slug="test_category",
        description="Test",
        exclusions=""
    )

    with patch("classymail.api.category_assessment.resolve_model_config") as mock_resolve, \
         patch("classymail.api.category_assessment.Clients"), \
         patch("classymail.api.category_assessment.auth_headers") as mock_auth_headers:

        mock_resolve.return_value = ("https://test.openai.azure.com", "gpt-5-nano")
        mock_auth_headers.return_value = {"Authorization": "Bearer test-token"}

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "This is not valid JSON"
                    },
                    "finish_reason": "stop"
                }
            ]
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with pytest.raises(HTTPException) as exc_info:
                await assess_category(request)

            assert exc_info.value.status_code == 500
            assert "parse" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_assess_category_no_choices():
    """Test handling of response with no choices."""
    from fastapi import HTTPException

    request = CategoryAssessmentRequest(
        name="Test Category",
        slug="test_category",
        description="Test",
        exclusions=""
    )

    with patch("classymail.api.category_assessment.resolve_model_config") as mock_resolve, \
         patch("classymail.api.category_assessment.Clients"), \
         patch("classymail.api.category_assessment.auth_headers") as mock_auth_headers:

        mock_resolve.return_value = ("https://test.openai.azure.com", "gpt-5-nano")
        mock_auth_headers.return_value = {"Authorization": "Bearer test-token"}

        mock_response = MagicMock()
        mock_response.json.return_value = {"choices": []}

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with pytest.raises(HTTPException) as exc_info:
                await assess_category(request)

            assert exc_info.value.status_code == 502
            assert "no" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_assess_category_empty_content():
    """Test handling of response with empty content."""
    from fastapi import HTTPException

    request = CategoryAssessmentRequest(
        name="Test Category",
        slug="test_category",
        description="Test",
        exclusions=""
    )

    with patch("classymail.api.category_assessment.resolve_model_config") as mock_resolve, \
         patch("classymail.api.category_assessment.Clients"), \
         patch("classymail.api.category_assessment.auth_headers") as mock_auth_headers:

        mock_resolve.return_value = ("https://test.openai.azure.com", "gpt-5-nano")
        mock_auth_headers.return_value = {"Authorization": "Bearer test-token"}

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {"content": ""},
                    "finish_reason": "length"
                }
            ]
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with pytest.raises(HTTPException) as exc_info:
                await assess_category(request)

            assert exc_info.value.status_code == 502
            assert "empty" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_assess_category_json_with_code_fence():
    """Test parsing JSON response wrapped in markdown code fence."""
    request = CategoryAssessmentRequest(
        name="Test Category",
        slug="test_category",
        description="Test",
        exclusions=""
    )

    with patch("classymail.api.category_assessment.resolve_model_config") as mock_resolve, \
         patch("classymail.api.category_assessment.Clients"), \
         patch("classymail.api.category_assessment.auth_headers") as mock_auth_headers:

        mock_resolve.return_value = ("https://test.openai.azure.com", "gpt-5-nano")
        mock_auth_headers.return_value = {"Authorization": "Bearer test-token"}

        # JSON wrapped in code fence
        json_content = {
            "quality_score": "Good",
            "advice": "Well structured",
            "specific_suggestions": []
        }
        wrapped_content = f"```json\n{json.dumps(json_content)}\n```"

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {"content": wrapped_content},
                    "finish_reason": "stop"
                }
            ]
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await assess_category(request)

            assert result.quality_score == "Good"
            assert result.advice == "Well structured"


@pytest.mark.asyncio
async def test_assess_category_reasoning_model():
    """Test category assessment with reasoning model (o1/GPT-5)."""
    request = CategoryAssessmentRequest(
        name="Test Category",
        slug="test_category",
        description="Test description",
        exclusions=""
    )

    with patch("classymail.api.category_assessment.resolve_model_config") as mock_resolve, \
         patch("classymail.api.category_assessment.Clients"), \
         patch("classymail.api.category_assessment.auth_headers") as mock_auth_headers, \
         patch("classymail.api.category_assessment.is_reasoning_model") as mock_is_reasoning:

        mock_resolve.return_value = ("https://test.openai.azure.com", "o1-preview")
        mock_auth_headers.return_value = {"Authorization": "Bearer test-token"}
        mock_is_reasoning.return_value = True

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "quality_score": "Good",
                            "advice": "Category is well-defined",
                            "specific_suggestions": []
                        })
                    },
                    "finish_reason": "stop"
                }
            ]
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await assess_category(request)

            assert result.quality_score == "Good"
            # Verify that reasoning model uses single user message
            call_args = mock_client.post.call_args
            payload = call_args.kwargs.get("json", call_args.args[1] if len(call_args.args) > 1 else {})
            assert len(payload["messages"]) == 1
            assert payload["messages"][0]["role"] == "user"


@pytest.mark.asyncio
async def test_assess_category_standard_model():
    """Test category assessment with standard chat model."""
    request = CategoryAssessmentRequest(
        name="Test Category",
        slug="test_category",
        description="Test description",
        exclusions=""
    )

    with patch("classymail.api.category_assessment.resolve_model_config") as mock_resolve, \
         patch("classymail.api.category_assessment.Clients"), \
         patch("classymail.api.category_assessment.auth_headers") as mock_auth_headers, \
         patch("classymail.api.category_assessment.is_reasoning_model") as mock_is_reasoning:

        mock_resolve.return_value = ("https://test.openai.azure.com", "gpt-4o")
        mock_auth_headers.return_value = {"Authorization": "Bearer test-token"}
        mock_is_reasoning.return_value = False

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "quality_score": "Good",
                            "advice": "Category is well-defined",
                            "specific_suggestions": []
                        })
                    },
                    "finish_reason": "stop"
                }
            ]
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await assess_category(request)

            assert result.quality_score == "Good"
            # Verify that standard model uses system + user messages
            call_args = mock_client.post.call_args
            payload = call_args.kwargs.get("json", call_args.args[1] if len(call_args.args) > 1 else {})
            assert len(payload["messages"]) == 2
            assert payload["messages"][0]["role"] == "system"
            assert payload["messages"][1]["role"] == "user"
            # Verify response_format is set for standard models
            assert payload.get("response_format") == {"type": "json_object"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
