from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderStatus:
    name: str
    available: bool
    reason: str | None = None


class LLMProvider:
    name = "base"
    can_generate = False

    def status(self) -> ProviderStatus:
        raise NotImplementedError

    def generate_json(self, prompt: str) -> dict | list:
        raise LLMError(f"Provider {self.name} does not support generation.")


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self) -> None:
        self.model = os.getenv("AMA_GEMINI_MODEL", DEFAULT_GEMINI_MODEL)

    @property
    def can_generate(self) -> bool:  # type: ignore[override]
        return bool(os.getenv("GEMINI_API_KEY"))

    def status(self) -> ProviderStatus:
        if not self.can_generate:
            return ProviderStatus(
                self.name,
                False,
                "GEMINI_API_KEY is not configured; the deterministic fallback patcher will be used.",
            )
        return ProviderStatus(self.name, True, f"Gemini patch planning is enabled (model {self.model}).")

    def generate_json(self, prompt: str, timeout_seconds: int = 120) -> dict | list:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise LLMError("GEMINI_API_KEY is not configured.")
        payload = json.dumps(
            {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.2,
                    "response_mime_type": "application/json",
                },
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            GEMINI_ENDPOINT.format(model=self.model),
            data=payload,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
            method="POST",
        )
        last_error = "unknown error"
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                    body = json.loads(response.read().decode("utf-8"))
                return self._extract_json(body)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:400]
                last_error = f"Gemini API returned HTTP {exc.code}: {detail}"
                if exc.code not in (429, 500, 502, 503):
                    raise LLMError(last_error) from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = f"Gemini API request failed: {exc}"
            time.sleep(2 * (attempt + 1))
        raise LLMError(last_error)

    @staticmethod
    def _extract_json(body: dict) -> dict | list:
        try:
            text = body["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            block = body.get("promptFeedback", {}).get("blockReason") if isinstance(body, dict) else None
            raise LLMError(
                f"Gemini response had no candidate text{f' (blocked: {block})' if block else ''}."
            ) from exc
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Gemini response was not valid JSON: {text[:200]}") from exc


class LocalHeuristicProvider(LLMProvider):
    name = "local-heuristic"

    def status(self) -> ProviderStatus:
        return ProviderStatus(self.name, True, "Deterministic local patching is available.")


def provider_for(name: str) -> LLMProvider:
    if name.lower() == "gemini":
        return GeminiProvider()
    return LocalHeuristicProvider()
