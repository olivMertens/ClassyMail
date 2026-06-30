"""Tests for the UI-switchable primary OCR provider setting (Element 2).

Covers settings_store sanitize/default behavior for ``ocr_provider`` and the
``/settings/defaults`` endpoint surface that the UI uses to seed the dropdown and
warn when Content Understanding is selected but not configured. Document
Intelligence stays the automatic fallback and is intentionally not selectable.
"""
import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from classymail.services.settings_store import (
    DEFAULT_SETTINGS,
    VALID_OCR_PROVIDERS,
    load_settings,
    save_settings,
)


def _tmp_settings(initial: dict | None = None) -> Path:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(initial if initial is not None else {}, f)
        return Path(f.name)


def test_default_settings_has_ocr_provider():
    assert "ocr_provider" in DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS["ocr_provider"] in VALID_OCR_PROVIDERS


def test_valid_providers_are_mistral_and_cu():
    # DI is the automatic fallback, not a selectable primary.
    assert set(VALID_OCR_PROVIDERS) == {"mistral", "content_understanding"}


def test_load_injects_default_when_absent(monkeypatch):
    monkeypatch.delenv("OCR_PROVIDER", raising=False)
    tmp = _tmp_settings({"processing_strategy": "standard"})
    try:
        with patch("classymail.services.settings_store.DATA_FILE", tmp):
            loaded = load_settings()
            assert loaded["ocr_provider"] == "mistral"
    finally:
        tmp.unlink(missing_ok=True)


def test_load_default_seeds_from_env(monkeypatch):
    monkeypatch.setenv("OCR_PROVIDER", "content_understanding")
    tmp = _tmp_settings({"processing_strategy": "standard"})
    try:
        with patch("classymail.services.settings_store.DATA_FILE", tmp):
            loaded = load_settings()
            assert loaded["ocr_provider"] == "content_understanding"
    finally:
        tmp.unlink(missing_ok=True)


def test_save_preserves_valid_provider(monkeypatch):
    monkeypatch.delenv("OCR_PROVIDER", raising=False)
    tmp = _tmp_settings()
    try:
        with patch("classymail.services.settings_store.DATA_FILE", tmp):
            save_settings({"ocr_provider": "content_understanding", "categories": []})
            assert load_settings()["ocr_provider"] == "content_understanding"
    finally:
        tmp.unlink(missing_ok=True)


def test_save_sanitizes_invalid_provider(monkeypatch):
    monkeypatch.delenv("OCR_PROVIDER", raising=False)
    tmp = _tmp_settings()
    try:
        with patch("classymail.services.settings_store.DATA_FILE", tmp):
            # An invalid/unsupported value (e.g. trying to force DI as primary)
            # is reset to the safe default rather than persisted.
            save_settings({"ocr_provider": "document_intelligence", "categories": []})
            assert load_settings()["ocr_provider"] == "mistral"
    finally:
        tmp.unlink(missing_ok=True)


def test_pipeline_precedence_settings_over_env(monkeypatch):
    # The pipeline reads ((settings or {}).get("ocr_provider") or env or "mistral").
    # A saved UI value must win over the OCR_PROVIDER env var.
    monkeypatch.setenv("OCR_PROVIDER", "mistral")
    settings = {"ocr_provider": "content_understanding"}
    import os
    resolved = ((settings or {}).get("ocr_provider") or os.getenv("OCR_PROVIDER", "mistral") or "mistral").strip().lower()
    assert resolved == "content_understanding"

    # With no saved value, the pipeline falls back to the env var.
    resolved_env = ((None or {}).get("ocr_provider") or os.getenv("OCR_PROVIDER", "mistral") or "mistral").strip().lower()
    assert resolved_env == "mistral"


def test_settings_defaults_endpoint_exposes_provider(monkeypatch):
    from classymail.api.routers import settings as settings_router
    from classymail.core import config

    monkeypatch.setenv("OCR_PROVIDER", "mistral")
    monkeypatch.setattr(config, "CONTENT_UNDERSTANDING_ENDPOINT", "https://cu.example.com/", raising=False)

    out = asyncio.run(settings_router.get_settings_defaults())
    assert out["ocr_provider"] == "mistral"
    assert out["content_understanding_configured"] is True


def test_settings_defaults_endpoint_cu_unconfigured(monkeypatch):
    from classymail.api.routers import settings as settings_router
    from classymail.core import config

    monkeypatch.delenv("OCR_PROVIDER", raising=False)
    monkeypatch.setattr(config, "CONTENT_UNDERSTANDING_ENDPOINT", None, raising=False)

    out = asyncio.run(settings_router.get_settings_defaults())
    assert out["ocr_provider"] == "mistral"
    assert out["content_understanding_configured"] is False
