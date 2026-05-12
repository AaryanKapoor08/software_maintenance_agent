from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass

from patchpilot.models import MaintenanceTask
from patchpilot.redaction import redact

ISSUE_RE = re.compile(r"https://github\.com/([^/]+)/([^/]+)/issues/(\d+)")


@dataclass(frozen=True)
class GitHubIssueRef:
    owner: str
    repo: str
    issue_number: int

    @property
    def repo_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}.git"


def parse_issue_url(url: str) -> GitHubIssueRef:
    match = ISSUE_RE.fullmatch(url.strip())
    if not match:
        raise ValueError("Expected a GitHub issue URL like https://github.com/org/repo/issues/42")
    owner, repo, number = match.groups()
    return GitHubIssueRef(owner=owner, repo=repo, issue_number=int(number))


def fetch_issue_task(url: str) -> MaintenanceTask:
    ref = parse_issue_url(url)
    api_url = f"https://api.github.com/repos/{ref.owner}/{ref.repo}/issues/{ref.issue_number}"
    request = urllib.request.Request(api_url, headers={"Accept": "application/vnd.github+json"})
    token = os.getenv("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return MaintenanceTask(
        id=f"github_{ref.owner}_{ref.repo}_{ref.issue_number}",
        source="github_issue",
        repo_url=ref.repo_url,
        issue_number=ref.issue_number,
        title=redact(payload.get("title", "")),
        body=redact(payload.get("body", "") or ""),
        labels=[label.get("name", "") for label in payload.get("labels", []) if isinstance(label, dict)],
        allowed_paths=["src/**", "tests/**", "app/**", "lib/**"],
        blocked_paths=[".github/**", ".env*", "*lock*", "secrets/**"],
    )
