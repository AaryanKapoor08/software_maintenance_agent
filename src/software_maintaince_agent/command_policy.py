from __future__ import annotations

import fnmatch
import shlex
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str
    tokens: list[str] = field(default_factory=list)


class CommandPolicy:
    blocked_substrings = (
        "rm -rf",
        "sudo",
        "curl ",
        "wget ",
        "scp ",
        "ssh ",
        "aws ",
        "gcloud ",
        "az ",
        "kubectl ",
        "terraform ",
        "Remove-Item",
        "rmdir /s",
        "del /s",
        ".env",
        "id_rsa",
        "private_key",
    )
    allowed_prefixes = (
        ("git", "status"),
        ("git", "diff"),
        ("git", "clone"),
        ("rg",),
        ("find",),
        ("ls",),
        ("cat",),
        ("pytest",),
        ("python", "-m", "pytest"),
        ("python", "-m", "compileall"),
        ("npm", "test"),
        ("npm", "run", "test"),
        ("npm", "run", "lint"),
        ("npm", "run", "typecheck"),
        ("npx", "tsc"),
        ("tsc",),
        ("node", "--check"),
        ("ruff", "check"),
        ("mypy",),
    )

    def __init__(self, blocked_paths: list[str] | None = None) -> None:
        self.blocked_paths = blocked_paths or [".env*", ".github/**", "*lock*", "secrets/**"]

    def validate(self, command: str, repo_root: Path | None = None) -> PolicyDecision:
        normalized = command.strip()
        lowered = normalized.lower()
        for blocked in self.blocked_substrings:
            if blocked.lower() in lowered:
                return PolicyDecision(False, f"Command contains blocked pattern: {blocked}")

        try:
            tokens = shlex.split(normalized, posix=False)
        except ValueError as exc:
            return PolicyDecision(False, f"Command parsing failed: {exc}")

        if not tokens:
            return PolicyDecision(False, "Empty command")

        for token in tokens[1:]:
            token = token.strip('"').strip("'")
            if token.startswith("..") or "/../" in token or "\\..\\" in token:
                return PolicyDecision(False, f"Command attempts parent traversal: {token}", tokens)
            if self._matches_blocked_path(token):
                return PolicyDecision(False, f"Command touches blocked path: {token}", tokens)
            if repo_root and self._absolute_outside_repo(token, repo_root):
                return PolicyDecision(False, f"Command touches path outside repo: {token}", tokens)

        for prefix in self.allowed_prefixes:
            if tuple(tokens[: len(prefix)]) == prefix:
                return PolicyDecision(True, "Allowed by command prefix policy", tokens)

        return PolicyDecision(False, f"Command prefix is not allowlisted: {' '.join(tokens[:3])}", tokens)

    def _matches_blocked_path(self, token: str) -> bool:
        clean = token.replace("\\", "/").strip('"').strip("'")
        return any(fnmatch.fnmatch(clean, pattern) for pattern in self.blocked_paths)

    @staticmethod
    def _absolute_outside_repo(token: str, repo_root: Path) -> bool:
        clean = token.strip('"').strip("'")
        candidate = Path(clean)
        if not candidate.is_absolute():
            return False
        try:
            candidate.resolve().relative_to(repo_root.resolve())
        except ValueError:
            return True
        return False
