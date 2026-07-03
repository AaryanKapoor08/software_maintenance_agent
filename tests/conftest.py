from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def hermetic_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests offline and deterministic: ambient API keys (including values
    loaded from .env.local) must never route test runs to a real LLM."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("AMA_LLM_PROVIDER", "local-heuristic")
