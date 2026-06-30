"""Unit tests for the opt-in Azure AI Content Understanding OCR provider (PoC).

Covers the async analyze + poll flow with mocked httpx, the synchronous 200 path,
failure propagation (so the pipeline can fall back to Document Intelligence), and
that the default OCR provider selector stays "mistral" (current behavior unchanged).
"""
import asyncio
import base64

import pytest

from classymail.core import config
from classymail.models import OCRFailed
from classymail.services import llm_pipeline
from classymail.services.costing import compute_cost_content_understanding


class FakeCUResponse:
    def __init__(self, status_code, *, headers=None, json_data=None, text=""):
        self.status_code = status_code
        self.headers = headers or {}
        self._json = json_data or {}
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError("raise_for_status should not fire on polled 2xx responses")

    def json(self):
        return self._json


class FakeCUClient:
    """Scriptable async httpx client with queued POST and GET responses."""

    def __init__(self, post_responses, get_responses=None):
        self._post = list(post_responses)
        self._get = list(get_responses or [])
        self.post_calls = []
        self.get_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json=None, headers=None):
        self.post_calls.append({"url": url, "json": json, "headers": headers})
        return self._post.pop(0)

    async def get(self, url, headers=None):
        self.get_calls.append({"url": url, "headers": headers})
        return self._get.pop(0)


def _patch(monkeypatch, client):
    """Wire the fake client + no-op sleep + key-based auth config for CU."""
    async def _no_sleep(*_a, **_k):
        return None

    monkeypatch.setattr(llm_pipeline.httpx, "AsyncClient", lambda timeout=180: client)
    monkeypatch.setattr(llm_pipeline.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(config, "CONTENT_UNDERSTANDING_ENDPOINT", "https://fake-cu.cognitiveservices.azure.com/")
    monkeypatch.setattr(config, "CONTENT_UNDERSTANDING_KEY", "test-key")
    monkeypatch.setattr(config, "CONTENT_UNDERSTANDING_ANALYZER_ID", "prebuilt-documentSearch")
    monkeypatch.setattr(config, "CONTENT_UNDERSTANDING_API_VERSION", "2025-11-01")


_DUMMY_PDF = base64.b64encode(b"%PDF-1.4 dummy").decode()


def test_cu_async_poll_success(monkeypatch):
    client = FakeCUClient(
        post_responses=[FakeCUResponse(202, headers={"Operation-Location": "https://fake-cu/op/1"})],
        get_responses=[
            FakeCUResponse(
                200,
                json_data={
                    "status": "Succeeded",
                    "result": {"contents": [{"markdown": "# Invoice\nTotal: 42", "pages": [1, 2]}]},
                },
            )
        ],
    )
    _patch(monkeypatch, client)

    result = asyncio.run(llm_pipeline.ocr_with_content_understanding(_DUMMY_PDF))

    assert result["markdown"] == "# Invoice\nTotal: 42"
    assert result["usage"]["pages_processed"] == 2
    assert result["usage"]["provider"] == "content_understanding"
    assert result["images"] == []
    # Verify the documented analyze endpoint + envelope were used.
    assert ":analyze?api-version=2025-11-01" in client.post_calls[0]["url"]
    assert "prebuilt-documentSearch" in client.post_calls[0]["url"]
    assert client.post_calls[0]["json"]["inputs"][0]["url"].startswith("data:application/pdf;base64,")


def test_cu_poll_then_succeed(monkeypatch):
    client = FakeCUClient(
        post_responses=[FakeCUResponse(202, headers={"Operation-Location": "https://fake-cu/op/2"})],
        get_responses=[
            FakeCUResponse(200, json_data={"status": "Running"}),
            FakeCUResponse(
                200,
                json_data={
                    "status": "Succeeded",
                    "result": {"contents": [{"markdown": "page text", "pages": [1]}]},
                },
            ),
        ],
    )
    _patch(monkeypatch, client)

    result = asyncio.run(llm_pipeline.ocr_with_content_understanding(_DUMMY_PDF))

    assert result["markdown"] == "page text"
    assert len(client.get_calls) == 2  # polled once while Running, then Succeeded


def test_cu_synchronous_200(monkeypatch):
    client = FakeCUClient(
        post_responses=[
            FakeCUResponse(
                200,
                json_data={"result": {"contents": [{"markdown": "sync md", "pages": [1]}]}},
            )
        ],
    )
    _patch(monkeypatch, client)

    result = asyncio.run(llm_pipeline.ocr_with_content_understanding(_DUMMY_PDF))

    assert result["markdown"] == "sync md"
    assert result["usage"]["pages_processed"] == 1
    assert client.get_calls == []  # no polling on synchronous response


def test_cu_submit_failure_raises_for_fallback(monkeypatch):
    client = FakeCUClient(post_responses=[FakeCUResponse(500, text="boom")])
    _patch(monkeypatch, client)

    with pytest.raises(OCRFailed):
        asyncio.run(llm_pipeline.ocr_with_content_understanding(_DUMMY_PDF))


def test_cu_failed_status_raises(monkeypatch):
    client = FakeCUClient(
        post_responses=[FakeCUResponse(202, headers={"Operation-Location": "https://fake-cu/op/3"})],
        get_responses=[
            FakeCUResponse(200, json_data={"status": "Failed", "error": {"message": "bad doc"}})
        ],
    )
    _patch(monkeypatch, client)

    with pytest.raises(OCRFailed):
        asyncio.run(llm_pipeline.ocr_with_content_understanding(_DUMMY_PDF))


def test_cu_empty_content_raises(monkeypatch):
    client = FakeCUClient(
        post_responses=[FakeCUResponse(200, json_data={"result": {"contents": [{"markdown": ""}]}})],
    )
    _patch(monkeypatch, client)

    with pytest.raises(OCRFailed):
        asyncio.run(llm_pipeline.ocr_with_content_understanding(_DUMMY_PDF))


def test_cu_missing_endpoint_raises(monkeypatch):
    monkeypatch.setattr(config, "CONTENT_UNDERSTANDING_ENDPOINT", None)
    with pytest.raises(RuntimeError):
        asyncio.run(llm_pipeline.ocr_with_content_understanding(_DUMMY_PDF))


def test_default_ocr_provider_is_mistral():
    # PoC is default-off: without OCR_PROVIDER set, the pipeline uses Mistral as today.
    assert (config.OCR_PROVIDER or "mistral").strip().lower() == "mistral"


def test_cost_content_understanding():
    rate = config.CU_OCR_COST_PER_1K_PAGES
    assert compute_cost_content_understanding(1000) == pytest.approx(rate)
    assert compute_cost_content_understanding(500) == pytest.approx(rate * 0.5)
    assert compute_cost_content_understanding(0, overrides={"cu_per_1k_pages": 9.0}) == 0.0
