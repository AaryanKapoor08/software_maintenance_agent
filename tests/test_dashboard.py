from __future__ import annotations

from pathlib import Path

from software_maintaince_agent.agent import SoftwareMaintainceAgent, load_task
from software_maintaince_agent.dashboard import list_runs, load_run_bundle, render_dashboard_html
from software_maintaince_agent.settings import Settings


def test_dashboard_html_contains_runner_controls() -> None:
    html = render_dashboard_html()
    assert "MAINTENANCE&nbsp;AGENT" in html
    assert "Run fixture" in html
    assert 'value="docker"' in html
    assert "/api/run" in html


def test_dashboard_lists_and_loads_runs(tmp_path: Path) -> None:
    task = load_task(Path("examples/tasks/python_email_empty.json"))
    report = SoftwareMaintainceAgent(Settings(runs_dir=tmp_path)).run_task(task, runs_dir=tmp_path)
    runs = list_runs(tmp_path)
    assert runs
    run_id = Path(report.report_path).parent.name
    bundle = load_run_bundle(tmp_path, run_id)
    assert bundle["report"]
    assert bundle["events"]
