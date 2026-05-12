from __future__ import annotations

from pathlib import Path

from software_maintaince_agent.command_policy import CommandPolicy


def test_policy_allows_pytest() -> None:
    decision = CommandPolicy().validate("python -m pytest tests/test_validation.py", Path.cwd())
    assert decision.allowed, decision.reason


def test_policy_blocks_destructive_commands() -> None:
    decision = CommandPolicy().validate("rm -rf .", Path.cwd())
    assert not decision.allowed
    assert "blocked" in decision.reason.lower()


def test_policy_blocks_env_reads() -> None:
    decision = CommandPolicy().validate("cat .env.local", Path.cwd())
    assert not decision.allowed
