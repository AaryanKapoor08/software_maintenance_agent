from __future__ import annotations

import os
import re
from collections.abc import Iterable

SECRET_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"gh[pousr]_[0-9A-Za-z_]{20,}"),
    re.compile(r"github_pat_[0-9A-Za-z_]{20,}"),
    re.compile(r"sk-[0-9A-Za-z_-]{20,}"),
    re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[^'\"\s]+"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
]

SECRET_ENV_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PRIVATE")


def env_secret_values() -> list[str]:
    values: list[str] = []
    for name, value in os.environ.items():
        if any(hint in name.upper() for hint in SECRET_ENV_HINTS) and len(value) >= 8:
            values.append(value)
    return values


def redact(text: object, extra_secrets: Iterable[str] | None = None) -> str:
    value = "" if text is None else str(text)
    for pattern in SECRET_PATTERNS:
        value = pattern.sub("[REDACTED]", value)
    for secret in [*env_secret_values(), *(extra_secrets or [])]:
        if secret:
            value = value.replace(secret, "[REDACTED]")
    return value


def redact_mapping(data: dict[str, object]) -> dict[str, object]:
    redacted: dict[str, object] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            redacted[key] = redact_mapping(value)
        elif isinstance(value, list):
            redacted[key] = [redact(item) if not isinstance(item, dict) else redact_mapping(item) for item in value]
        else:
            redacted[key] = redact(value)
    return redacted
