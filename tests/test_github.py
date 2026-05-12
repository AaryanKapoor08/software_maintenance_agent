from __future__ import annotations

from software_maintaince_agent.github_integration import parse_issue_url


def test_parse_issue_url() -> None:
    ref = parse_issue_url("https://github.com/acme/example/issues/42")
    assert ref.owner == "acme"
    assert ref.repo == "example"
    assert ref.issue_number == 42
    assert ref.repo_url == "https://github.com/acme/example.git"
