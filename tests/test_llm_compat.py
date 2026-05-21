"""Tests for chat completion parameter helpers (openai_client_factory)."""

import pytest

from classymail.services.openai_client_factory import build_chat_params, is_reasoning_model


# ---------------------------------------------------------------------------
# is_reasoning_model
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "deployment",
    [
        "gpt-5",
        "gpt-5-mini",
        "gpt-5-nano",
        "gpt-5.2-chat",
        "gpt5-nano",
        "o1",
        "o1-mini",
        "o1-preview",
        "o3",
        "o3-mini",
        "o4-mini",
    ],
)
def test_reasoning_models_detected(deployment: str):
    assert is_reasoning_model(deployment) is True


@pytest.mark.parametrize(
    "deployment",
    [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4.1",
        "gpt-4.1-nano",
        "phi-4",
        "mistral-document-ai-2512",
        "text-embedding-3-small",
        "",
        None,
    ],
)
def test_classic_models_not_reasoning(deployment: str | None):
    assert is_reasoning_model(deployment) is False


# ---------------------------------------------------------------------------
# build_chat_params – classic models
# ---------------------------------------------------------------------------

def test_build_classic_with_all_params():
    params = build_chat_params("gpt-4o-mini", temperature=0.3, max_output_tokens=1500)
    assert params == {"temperature": 0.3, "max_tokens": 1500}


def test_build_classic_tokens_only():
    params = build_chat_params("phi-4", max_output_tokens=1000)
    assert params == {"max_tokens": 1000}


def test_build_classic_temperature_only():
    params = build_chat_params("gpt-4o", temperature=0.7)
    assert params == {"temperature": 0.7}


def test_build_classic_no_params():
    params = build_chat_params("phi-4")
    assert params == {}


# ---------------------------------------------------------------------------
# build_chat_params – reasoning models
# ---------------------------------------------------------------------------

def test_build_reasoning_omits_temperature():
    params = build_chat_params("gpt-5-nano", temperature=0.3, max_output_tokens=1500)
    assert params == {"max_completion_tokens": 1500}
    assert "temperature" not in params
    assert "max_tokens" not in params


def test_build_reasoning_tokens_only():
    params = build_chat_params("o3-mini", max_output_tokens=500)
    assert params == {"max_completion_tokens": 500}


def test_build_reasoning_temperature_silently_ignored():
    params = build_chat_params("gpt-5.2-chat", temperature=0.0)
    assert params == {}


# ---------------------------------------------------------------------------
# Integration-style: payload construction pattern
# ---------------------------------------------------------------------------

def test_payload_spread_classic():
    deployment = "gpt-4o-mini"
    payload = {
        "model": deployment,
        "messages": [{"role": "user", "content": "hi"}],
        **build_chat_params(deployment, temperature=0.0, max_output_tokens=2000),
    }
    assert payload["max_tokens"] == 2000
    assert payload["temperature"] == 0.0
    assert "max_completion_tokens" not in payload


def test_payload_spread_reasoning():
    deployment = "gpt-5-nano"
    payload = {
        "model": deployment,
        "messages": [{"role": "user", "content": "hi"}],
        **build_chat_params(deployment, temperature=0.0, max_output_tokens=2000),
    }
    assert payload["max_completion_tokens"] == 2000
    assert "temperature" not in payload
    assert "max_tokens" not in payload
