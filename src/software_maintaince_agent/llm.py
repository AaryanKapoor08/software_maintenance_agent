from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderStatus:
    name: str
    available: bool
    reason: str | None = None


class LLMProvider:
    name = "base"

    def status(self) -> ProviderStatus:
        raise NotImplementedError


class GeminiProvider(LLMProvider):
    name = "gemini"

    def status(self) -> ProviderStatus:
        if not os.getenv("GEMINI_API_KEY"):
            return ProviderStatus(self.name, False, "GEMINI_API_KEY is not configured.")
        return ProviderStatus(
            self.name,
            True,
            "GEMINI_API_KEY is configured. This build still uses deterministic local patching.",
        )


class LocalHeuristicProvider(LLMProvider):
    name = "local-heuristic"

    def status(self) -> ProviderStatus:
        return ProviderStatus(self.name, True, "Deterministic local patching is available.")


def provider_for(name: str) -> LLMProvider:
    if name.lower() == "gemini":
        return GeminiProvider()
    return LocalHeuristicProvider()
