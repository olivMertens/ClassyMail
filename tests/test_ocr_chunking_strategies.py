import base64
import types
import asyncio
import sys

from classificationg2s.services import llm_pipeline


class FakePage:
    def __init__(self, idx: int):
        self.idx = idx

    def get_pixmap(self, matrix=None):
        raise AssertionError("get_pixmap should not be called for chunking path")


class FakeDoc:
    def __init__(self, page_count: int = 0, pages=None):
        self.pages = list(pages) if pages is not None else [f"p{i}" for i in range(page_count)]

    def __len__(self):
        return len(self.pages)

    def load_page(self, idx: int):
        return FakePage(idx)

    def insert_pdf(self, other, from_page: int, to_page: int):
        self.pages.extend(other.pages[from_page : to_page + 1])

    def tobytes(self):
        # return deterministic bytes for chunk content
        return f"PDF-{len(self.pages)}".encode()

    def close(self):
        pass


class FakeResponse:
    def __init__(self, pages):
        self._pages = pages
        self.status_code = 200
        self.text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return {"pages": self._pages, "usage": {"pages": len(self._pages)}}


class FakeAsyncClient:
    def __init__(self, responses):
        self._responses = responses
        self._idx = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json, headers):
        # Return next fake response
        if self._idx >= len(self._responses):
            raise AssertionError("No more fake responses queued")
        resp_pages = self._responses[self._idx]
        self._idx += 1
        return FakeResponse(resp_pages)


def make_fake_fitz(monkeypatch, total_pages: int):
    # fitz.open(stream=...) => FakeDoc(total_pages); fitz.open() => FakeDoc(0)
    def fake_open(stream=None, filetype=None):
        if stream is None:
            return FakeDoc(page_count=0)
        return FakeDoc(page_count=total_pages)

    fake_fitz = types.SimpleNamespace(open=fake_open)
    monkeypatch.setitem(sys.modules, "fitz", fake_fitz)


def patch_auth(monkeypatch):
    async def fake_auth_headers(*args, **kwargs):
        return {}

    monkeypatch.setattr(llm_pipeline, "auth_headers", fake_auth_headers)


def patch_config():
    llm_pipeline.config.MISTRAL_ENDPOINT = "https://fake"
    llm_pipeline.config.MISTRAL_DEPLOYMENT = "mistral-test"


def test_chunking_standard_strategy(monkeypatch):
    # Arrange: 31 pages -> chunk into 30 + 1 (document_url payloads)
    total_pages = 31
    make_fake_fitz(monkeypatch, total_pages)
    patch_auth(monkeypatch)
    patch_config()

    # Fake httpx client: first call returns 30 pages, second returns 1 page
    fake_client = FakeAsyncClient(
        responses=[[{"markdown": f"chunk0-page{p}"} for p in range(30)], [{"markdown": "chunk1-page0"}]]
    )
    monkeypatch.setattr(llm_pipeline.httpx, "AsyncClient", lambda timeout=90: fake_client)

    # Act
    result = asyncio.run(llm_pipeline.ocr_with_mistral(base64_pdf=base64.b64encode(b"dummy").decode()))

    # Assert
    assert result["markdown"].count("chunk0-page") == 30
    assert "chunk1-page0" in result["markdown"]


def test_chunking_reasoning_strategy(monkeypatch):
    # Reasoning strategy does not change OCR params; just verify aggregation works
    total_pages = 31
    make_fake_fitz(monkeypatch, total_pages)
    patch_auth(monkeypatch)
    patch_config()
    fake_client = FakeAsyncClient(
        responses=[[{"markdown": f"chunk0-page{p}"} for p in range(30)], [{"markdown": "chunk1-page0"}]]
    )
    monkeypatch.setattr(llm_pipeline.httpx, "AsyncClient", lambda timeout=90: fake_client)

    result = asyncio.run(llm_pipeline.ocr_with_mistral(base64_pdf=base64.b64encode(b"dummy").decode()))
    assert result["markdown"].count("chunk0-page") == 30
    assert "chunk1-page0" in result["markdown"]


def test_chunking_vision_strategy(monkeypatch):
    # Vision strategy uses enable_vision_enrichment + include_images (still chunked as document_url)
    total_pages = 31
    make_fake_fitz(monkeypatch, total_pages)
    patch_auth(monkeypatch)
    patch_config()
    fake_client = FakeAsyncClient(
        responses=[
            [{"markdown": f"chunk0-page{p}", "images": [{"summary": "img"}]} for p in range(30)],
            [{"markdown": "chunk1-page0", "images": [{"summary": "img"}]}],
        ]
    )
    monkeypatch.setattr(llm_pipeline.httpx, "AsyncClient", lambda timeout=90: fake_client)

    result = asyncio.run(
        llm_pipeline.ocr_with_mistral(
            base64_pdf=base64.b64encode(b"dummy").decode(),
            include_images=True,
            enable_vision_enrichment=True,
        )
    )
    # images should be aggregated; content includes visual context markers
    assert result["markdown"].count("chunk0-page") == 30
    assert "chunk1-page0" in result["markdown"]
    # annotated_images present
    assert result["images"]
