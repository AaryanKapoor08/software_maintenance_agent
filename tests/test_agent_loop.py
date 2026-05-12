from __future__ import annotations

from pathlib import Path

from software_maintaince_agent.agent import SoftwareMaintainceAgent, load_task
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
