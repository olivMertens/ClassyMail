import logging
import pytest

from classymail.services.llm_pipeline import _combine_ocr_pages, OCRFailed


def test_combine_logs_metrics(caplog):
    ocr_pages = [
        {"markdown": "Hello", "images": [{"id": "img1", "type": "photo"}]},
        {"markdown": "World", "images": []},
    ]
    with caplog.at_level(logging.INFO):
        content, annotated = _combine_ocr_pages(ocr_pages, enable_vision_enrichment=False, data={"pages": ocr_pages})

    assert "OCR Response: 2 pages" in caplog.text
    assert "Page 0: markdown_length=5 chars, images=1" in caplog.text
    assert "Page 1: markdown_length=5 chars, images=0" in caplog.text
    assert "OCR Final combined content" in caplog.text
    assert "pages" in caplog.text

    assert content.strip() == "Hello\n\nWorld"
    assert len(annotated) == 1
    assert annotated[0]["page_index"] == 0
    assert annotated[0]["id"] == "img1"


def test_combine_warn_empty_page(caplog):
    ocr_pages = [{"markdown": "", "images": []}]
    with caplog.at_level(logging.WARNING):
        with pytest.raises(OCRFailed):
            _combine_ocr_pages(ocr_pages, enable_vision_enrichment=False, data={"pages": ocr_pages})

    assert "Page 0: empty content" in caplog.text
    assert "Raw response preview" in caplog.text
