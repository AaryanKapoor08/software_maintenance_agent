from __future__ import annotations

import pytest

from software_maintaince_agent.models import MaintenanceTask
from software_maintaince_agent.redaction import redact


def test_task_schema_validates_attempt_limit() -> None:
    with pytest.raises(ValueError):
        MaintenanceTask(
            id="bad",
            repo_url="repo",
            title="bad",
            max_attempts=0,
        )


def test_secret_redaction_handles_common_tokens() -> None:
    fake_google_key = "AIza" + "A" * 32
    fake_github_token = "ghp_" + "B" * 36
    text = f"GEMINI_API_KEY={fake_google_key}\nGITHUB_TOKEN={fake_github_token}"
    redacted = redact(text)
    assert fake_google_key not in redacted
    assert fake_github_token not in redacted
    assert "[REDACTED]" in redacted
