from __future__ import annotations

from pathlib import Path

import pytest

from software_maintaince_agent.agent import load_task
from software_maintaince_agent.llm import GeminiProvider, LLMError, LLMProvider
from software_maintaince_agent.patching import LLMPatcher, PatchSafetyError


class FakeProvider(LLMProvider):
    name = "fake"
    can_generate = True

    def __init__(self, response) -> None:
        self.response = response
        self.prompts: list[str] = []

    def generate_json(self, prompt: str):
        self.prompts.append(prompt)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "app.py").write_text("def broken():\n    return 1\n", encoding="utf-8")
    return repo


def test_llm_patcher_parses_changes_and_sets_before(tmp_path: Path) -> None:
    task = load_task(Path("examples/tasks/python_email_empty.json"))
    repo = make_repo(tmp_path)
    provider = FakeProvider(
        {
            "reasoning": "fix the return value",
            "changes": [{"path": "src/app.py", "content": "def broken():\n    return 2\n"}],
        }
    )
    patcher = LLMPatcher(provider)
    changes = patcher.plan_changes(repo, task, ["src/app.py"], attempt=1)
    assert len(changes) == 1
    assert changes[0].path == "src/app.py"
    assert changes[0].before == "def broken():\n    return 1\n"
    assert changes[0].after == "def broken():\n    return 2\n"
    assert patcher.last_reasoning == "fix the return value"


def test_llm_patcher_skips_identical_content_and_rejects_blocked_paths(tmp_path: Path) -> None:
    task = load_task(Path("examples/tasks/python_email_empty.json"))
    repo = make_repo(tmp_path)
    identical = FakeProvider(
        {"changes": [{"path": "src/app.py", "content": "def broken():\n    return 1\n"}]}
    )
    assert LLMPatcher(identical).plan_changes(repo, task, ["src/app.py"]) == []

    escaping = FakeProvider({"changes": [{"path": "../outside.py", "content": "x = 1\n"}]})
    with pytest.raises(PatchSafetyError):
        LLMPatcher(escaping).plan_changes(repo, task, ["src/app.py"])


def test_llm_patcher_feedback_lands_in_prompt(tmp_path: Path) -> None:
    task = load_task(Path("examples/tasks/python_email_empty.json"))
    repo = make_repo(tmp_path)
    provider = FakeProvider({"changes": []})
    patcher = LLMPatcher(provider)
    patcher.plan_changes(
        repo,
        task,
        ["src/app.py"],
        attempt=2,
        feedback={"command": "pytest", "failure_summary": "AssertionError: boom", "output": "E boom"},
    )
    prompt = provider.prompts[0]
    assert "AssertionError: boom" in prompt
    assert "did not pass" in prompt
    assert "src/app.py" in prompt


def test_llm_patcher_raises_on_non_object_response(tmp_path: Path) -> None:
    task = load_task(Path("examples/tasks/python_email_empty.json"))
    repo = make_repo(tmp_path)
    with pytest.raises(LLMError):
        LLMPatcher(FakeProvider([1, 2, 3])).plan_changes(repo, task, ["src/app.py"])


def test_llm_patcher_creates_new_file_in_new_directory(tmp_path: Path) -> None:
    from software_maintaince_agent.patching import write_changes

    task = load_task(Path("examples/tasks/python_email_empty.json"))
    repo = make_repo(tmp_path)
    provider = FakeProvider(
        {"changes": [{"path": "src/new/deep/module.py", "content": "VALUE = 1\n"}]}
    )
    changes = LLMPatcher(provider).plan_changes(repo, task, ["src/app.py"])
    assert changes[0].before == ""
    # write must materialize a brand-new nested path without crashing
    write_changes(repo, task, changes)
    assert (repo / "src/new/deep/module.py").read_text(encoding="utf-8") == "VALUE = 1\n"


def test_gemini_extract_json() -> None:
    body = {"candidates": [{"content": {"parts": [{"text": '{"changes": []}'}]}}]}
    assert GeminiProvider._extract_json(body) == {"changes": []}
    with pytest.raises(LLMError):
        GeminiProvider._extract_json({"candidates": []})
    with pytest.raises(LLMError):
        GeminiProvider._extract_json(
            {"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}
        )


def test_gemini_status_without_key(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    provider = GeminiProvider()
    status = provider.status()
    assert status.available is False
    assert provider.can_generate is False
