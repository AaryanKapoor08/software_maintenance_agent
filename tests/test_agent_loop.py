from __future__ import annotations

from pathlib import Path

import pytest

from software_maintaince_agent.agent import SoftwareMaintainceAgent, load_task
from software_maintaince_agent.llm import LLMProvider, ProviderStatus
from software_maintaince_agent.settings import Settings


def test_fixture_agent_run_succeeds_end_to_end(tmp_path: Path) -> None:
    task = load_task(Path("examples/tasks/python_email_empty.json"))
    settings = Settings(runs_dir=tmp_path)
    report = SoftwareMaintainceAgent(settings).run_task(task, sandbox_kind="local", runs_dir=tmp_path)
    assert report.status == "success"
    assert "src/email_validator_app/validation.py" in report.changed_files
    assert report.report_path is not None
    assert Path(report.report_path).exists()
    assert report.patch_path is not None
    assert Path(report.patch_path).exists()


def test_repair_loop_retries_when_llm_proposes_no_effective_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixed_content = (
        'def is_valid_email(email: str | None) -> bool:\n'
        '    """Return True when a string looks like an email address."""\n'
        "    if not email:\n"
        "        return False\n"
        '    return "@" in email and "." in email.rsplit("@", 1)[-1]\n'
    )

    class NoChangeThenFixProvider(LLMProvider):
        name = "fake"
        can_generate = True

        def __init__(self) -> None:
            self.prompts: list[str] = []

        def status(self) -> ProviderStatus:
            return ProviderStatus(self.name, True)

        def generate_json(self, prompt: str) -> dict:
            self.prompts.append(prompt)
            if len(self.prompts) == 1:
                return {"reasoning": "looks fine", "changes": []}
            return {
                "reasoning": "reject empty emails",
                "changes": [
                    {"path": "src/email_validator_app/validation.py", "content": fixed_content}
                ],
            }

    class NoOpHeuristic:
        def plan_changes(self, *args, **kwargs) -> list:
            return []

    provider = NoChangeThenFixProvider()
    monkeypatch.setattr("software_maintaince_agent.agent.provider_for", lambda kind: provider)
    monkeypatch.setattr("software_maintaince_agent.agent.HeuristicPatcher", NoOpHeuristic)

    task = load_task(Path("examples/tasks/python_email_empty.json"))
    settings = Settings(runs_dir=tmp_path)
    report = SoftwareMaintainceAgent(settings).run_task(task, sandbox_kind="local", runs_dir=tmp_path)

    assert report.status == "success"
    attempts_text = (Path(report.report_path).parent / "attempts.json").read_text(encoding="utf-8")
    assert "Patcher proposed no effective change." in attempts_text
    assert len(provider.prompts) == 2
    assert "no effective changes" in provider.prompts[1]


def test_repair_loop_recovers_from_bad_first_patch(tmp_path: Path) -> None:
    task = load_task(Path("examples/tasks/python_email_repair.json"))
    settings = Settings(runs_dir=tmp_path)
    report = SoftwareMaintainceAgent(settings).run_task(task, sandbox_kind="local", runs_dir=tmp_path)
    assert report.status == "success"
    attempts_path = Path(report.report_path).parent / "attempts.json"
    assert '"attempt": 2' in attempts_path.read_text(encoding="utf-8")
    patch_text = Path(report.patch_path).read_text(encoding="utf-8")
    assert '"""Return True when a string looks like an email address."""' in patch_text
    assert '"""Return True when a non-empty string looks like an email address."""' not in patch_text
