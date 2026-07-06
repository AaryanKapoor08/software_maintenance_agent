from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from software_maintaince_agent.cli import app
from software_maintaince_agent.models import RunState
from software_maintaince_agent.storage import TraceStore

runner = CliRunner()


def make_run(runs_dir: Path, run_id: str, status: RunState, with_report: bool = False) -> Path:
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    store = TraceStore(run_dir / "trace.sqlite")
    store.init_run(run_id, f"task_{run_id}", run_dir)
    store.update_status(run_id, status)
    if with_report:
        (run_dir / "final_report.md").write_text("# Final Report\n\nAll good.", encoding="utf-8")
    return run_dir


def test_runs_lists_history(tmp_path: Path) -> None:
    make_run(tmp_path, "run_a", RunState.FINALIZED_SUCCESS)
    make_run(tmp_path, "run_b", RunState.ESCALATED)

    result = runner.invoke(app, ["runs", "--runs-dir", str(tmp_path)])

    assert result.exit_code == 0
    assert "run_a" in result.output
    assert "run_b" in result.output


def test_runs_empty_dir(tmp_path: Path) -> None:
    result = runner.invoke(app, ["runs", "--runs-dir", str(tmp_path)])

    assert result.exit_code == 0
    assert "No runs found" in result.output


def test_stats_reports_success_rate(tmp_path: Path) -> None:
    make_run(tmp_path, "run_a", RunState.FINALIZED_SUCCESS)
    make_run(tmp_path, "run_b", RunState.FINALIZED_FAILED)

    result = runner.invoke(app, ["stats", "--runs-dir", str(tmp_path)])

    assert result.exit_code == 0
    assert "50.0%" in result.output


def test_report_renders_markdown(tmp_path: Path) -> None:
    make_run(tmp_path, "run_a", RunState.FINALIZED_SUCCESS, with_report=True)

    result = runner.invoke(app, ["report", "--run-id", "run_a", "--runs-dir", str(tmp_path)])

    assert result.exit_code == 0
    assert "Final Report" in result.output


def test_report_missing_run_errors(tmp_path: Path) -> None:
    result = runner.invoke(app, ["report", "--run-id", "nope", "--runs-dir", str(tmp_path)])

    assert result.exit_code != 0


def test_clean_previews_without_force(tmp_path: Path) -> None:
    make_run(tmp_path, "run_a", RunState.FINALIZED_SUCCESS)
    make_run(tmp_path, "run_b", RunState.FINALIZED_FAILED)

    result = runner.invoke(app, ["clean", "--runs-dir", str(tmp_path), "--keep", "1"])

    assert result.exit_code == 0
    assert "Preview only" in result.output
    assert (tmp_path / "run_a").exists()
    assert (tmp_path / "run_b").exists()


def test_clean_force_deletes(tmp_path: Path) -> None:
    make_run(tmp_path, "run_a", RunState.FINALIZED_SUCCESS)
    make_run(tmp_path, "run_b", RunState.FINALIZED_FAILED)

    result = runner.invoke(app, ["clean", "--runs-dir", str(tmp_path), "--keep", "1", "--force"])

    assert result.exit_code == 0
    remaining = [child.name for child in tmp_path.iterdir()]
    assert len(remaining) == 1


def test_clean_requires_criteria(tmp_path: Path) -> None:
    result = runner.invoke(app, ["clean", "--runs-dir", str(tmp_path)])

    assert result.exit_code != 0


def test_run_batch_dry_run(tmp_path: Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    task = {
        "id": "batch_demo",
        "repo_url": "examples/fixtures/python_email_validator",
        "title": "Demo task",
        "body": "Batch smoke test.",
    }
    (tasks_dir / "demo.json").write_text(json.dumps(task), encoding="utf-8")
    runs_dir = tmp_path / "runs"

    result = runner.invoke(
        app,
        [
            "run-batch",
            "--tasks-dir",
            str(tasks_dir),
            "--dry-run",
            "--runs-dir",
            str(runs_dir),
        ],
    )

    assert result.exit_code == 0
    assert "demo.json" in result.output
    assert "success" in result.output


def test_run_batch_empty_dir_errors(tmp_path: Path) -> None:
    result = runner.invoke(app, ["run-batch", "--tasks-dir", str(tmp_path)])

    assert result.exit_code != 0
