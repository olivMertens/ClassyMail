"""Unit tests for the opt-in Agent Framework 1.9 chat drop-ins (default-off).

Covers ``chat_agent._build_run_kwargs`` — the helper that translates the
default-off feature flags into ``agent.run`` kwargs:

- both flags off  → empty dict (legacy path stays byte-for-byte unchanged);
- reasoning effort → ``options={"reasoning": {"effort": ...}}`` for valid
  values, silently ignored for invalid ones;
- history compaction → a ``ContextWindowCompactionStrategy`` + built-in
  ``CharacterEstimatorTokenizer`` carrying the configured token budgets.
"""
from agent_framework import (
    CharacterEstimatorTokenizer,
    ContextWindowCompactionStrategy,
)

from classymail.core import config
from classymail.services import chat_agent


def _reset(monkeypatch, *, effort="", compaction=False,
           max_tokens=12000, max_output=2000):
    monkeypatch.setattr(config, "CHAT_REASONING_EFFORT", effort, raising=False)
    monkeypatch.setattr(config, "CHAT_HISTORY_COMPACTION", compaction, raising=False)
    monkeypatch.setattr(config, "CHAT_COMPACTION_MAX_TOKENS", max_tokens, raising=False)
    monkeypatch.setattr(config, "CHAT_COMPACTION_MAX_OUTPUT_TOKENS", max_output, raising=False)


def test_run_kwargs_empty_when_flags_off(monkeypatch):
    """Default-off: no kwargs → run() invocation is unchanged."""
    _reset(monkeypatch)
    assert chat_agent._build_run_kwargs() == {}


def test_run_kwargs_reasoning_valid(monkeypatch):
    _reset(monkeypatch, effort="high")
    assert chat_agent._build_run_kwargs() == {
        "options": {"reasoning": {"effort": "high"}}
    }


def test_run_kwargs_reasoning_normalized(monkeypatch):
    """Effort is whitespace/case-normalized before validation."""
    _reset(monkeypatch, effort="  Medium ")
    assert chat_agent._build_run_kwargs() == {
        "options": {"reasoning": {"effort": "medium"}}
    }


def test_run_kwargs_reasoning_invalid_ignored(monkeypatch):
    """An unknown effort is dropped (no options key) rather than sent."""
    _reset(monkeypatch, effort="bogus")
    assert chat_agent._build_run_kwargs() == {}


def test_run_kwargs_compaction(monkeypatch):
    _reset(monkeypatch, compaction=True, max_tokens=8000, max_output=1500)
    kwargs = chat_agent._build_run_kwargs()

    assert set(kwargs) == {"compaction_strategy", "tokenizer"}
    strategy = kwargs["compaction_strategy"]
    assert isinstance(strategy, ContextWindowCompactionStrategy)
    assert isinstance(kwargs["tokenizer"], CharacterEstimatorTokenizer)
    # Configured token budgets propagate into the strategy.
    assert strategy.max_context_window_tokens == 8000
    assert strategy.max_output_tokens == 1500


def test_run_kwargs_both_flags(monkeypatch):
    _reset(monkeypatch, effort="low", compaction=True)
    kwargs = chat_agent._build_run_kwargs()

    assert set(kwargs) == {"options", "compaction_strategy", "tokenizer"}
    assert kwargs["options"] == {"reasoning": {"effort": "low"}}
    assert isinstance(kwargs["compaction_strategy"], ContextWindowCompactionStrategy)
