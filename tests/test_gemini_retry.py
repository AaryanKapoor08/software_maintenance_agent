import io
import urllib.error

import pytest

from software_maintaince_agent.llm import (
    GeminiProvider,
    LLMError,
    _retry_delay_seconds,
)


def test_retry_delay_parses_human_readable_hint() -> None:
    body = '{"error": {"message": "Quota exceeded. Please retry in 38.598281122s."}}'
    assert _retry_delay_seconds(body) == pytest.approx(39.598281122)


def test_retry_delay_parses_retry_info_detail() -> None:
    body = '{"details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "7s"}]}'
    assert _retry_delay_seconds(body) == pytest.approx(8.0)


def test_retry_delay_defaults_to_zero_and_caps() -> None:
    assert _retry_delay_seconds("no hint here") == 0.0
    assert _retry_delay_seconds("Please retry in 3600s.") == 90.0


def test_generate_json_honors_429_retry_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    body = b'{"error": {"message": "Quota exceeded. Please retry in 5s."}}'

    def raise_429(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 429, "Too Many Requests", {}, io.BytesIO(body)
        )

    sleeps: list[float] = []
    monkeypatch.setattr("software_maintaince_agent.llm.urllib.request.urlopen", raise_429)
    monkeypatch.setattr("software_maintaince_agent.llm.time.sleep", sleeps.append)

    with pytest.raises(LLMError, match="HTTP 429"):
        GeminiProvider().generate_json("prompt")

    assert sleeps == [pytest.approx(6.0), pytest.approx(6.0)]
