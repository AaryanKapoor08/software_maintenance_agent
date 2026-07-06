from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from software_maintaince_agent.models import RunState
from software_maintaince_agent.run_index import (
    list_run_records,
    prune_runs,
    select_prunable_runs,
    summarize_runs,
)
from software_maintaince_agent.storage import TraceStore


def make_run(
    runs_dir: Path,
    run_id: str,
    status: RunState,
    started_at: datetime | None = None,
    with_patch: bool = False,
    with_report: bool = False,
) -> Path:
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    store = TraceStore(run_dir / "trace.sqlite")
    store.init_run(run_id, f"task_{run_id}", run_dir)
    store.update_status(run_id, status)
    if started_at is not None:
        import sqlite3
        from contextlib import closing

        with closing(sqlite3.connect(run_dir / "trace.sqlite")) as conn, conn:
            conn.execute(
                "UPDATE runs SET started_at = ? WHERE run_id = ?",
                (started_at.isoformat(), run_id),
            )
    if with_patch:
        (run_dir / "patch.diff").write_text("diff", encoding="utf-8")
    if with_report:
        (run_dir / "final_report.md").write_text("# Report", encoding="utf-8")
    return run_dir


def test_list_run_records_orders_newest_first(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    make_run(tmp_path, "run_old", RunState.FINALIZED_SUCCESS, started_at=now - timedelta(days=2))
    make_run(tmp_path, "run_new", RunState.FINALIZED_FAILED, started_at=now, with_patch=True)
    (tmp_path / "benchmarks").mkdir()  # non-run directory is skipped
    (tmp_path / "stray.txt").write_text("x", encoding="utf-8")

    records = list_run_records(tmp_path)

    assert [record.run_id for record in records] == ["run_new", "run_old"]
    assert records[0].has_patch is True
    assert records[1].has_patch is False


def test_list_run_records_filters_by_status(tmp_path: Path) -> None:
    make_run(tmp_path, "run_a", RunState.FINALIZED_SUCCESS)
    make_run(tmp_path, "run_b", RunState.ESCALATED)

    records = list_run_records(tmp_path, status="finalized_success")

    assert [record.run_id for record in records] == ["run_a"]


def test_list_run_records_missing_dir_returns_empty(tmp_path: Path) -> None:
    assert list_run_records(tmp_path / "does_not_exist") == []


def test_summarize_runs_counts_outcomes(tmp_path: Path) -> None:
    make_run(tmp_path, "run_a", RunState.FINALIZED_SUCCESS)
    make_run(tmp_path, "run_b", RunState.FINALIZED_SUCCESS)
    make_run(tmp_path, "run_c", RunState.ESCALATED)
    make_run(tmp_path, "run_d", RunState.TESTS_RUNNING)

    summary = summarize_runs(list_run_records(tmp_path))

    assert summary.total == 4
    assert summary.succeeded == 2
    assert summary.failed == 1
    assert summary.in_progress == 1
    assert summary.success_rate == pytest.approx(2 / 3)


def test_select_prunable_runs_requires_criteria(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        select_prunable_runs(tmp_path)


def test_select_prunable_runs_keep(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    for offset in range(3):
        make_run(
            tmp_path,
            f"run_{offset}",
            RunState.FINALIZED_SUCCESS,
            started_at=now - timedelta(days=offset),
        )

    candidates = select_prunable_runs(tmp_path, keep=1)

    assert sorted(record.run_id for record in candidates) == ["run_1", "run_2"]


def test_select_prunable_runs_intersects_both_criteria(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    make_run(tmp_path, "run_new", RunState.FINALIZED_SUCCESS, started_at=now)
    make_run(
        tmp_path,
        "run_recent",
        RunState.FINALIZED_SUCCESS,
        started_at=now - timedelta(days=1),
    )
    make_run(
        tmp_path,
        "run_ancient",
        RunState.FINALIZED_FAILED,
        started_at=now - timedelta(days=30),
    )

    candidates = select_prunable_runs(tmp_path, keep=1, older_than_days=7)

    assert [record.run_id for record in candidates] == ["run_ancient"]


def test_prune_runs_deletes_directories(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    make_run(tmp_path, "run_keep", RunState.FINALIZED_SUCCESS, started_at=now)
    old_dir = make_run(
        tmp_path,
        "run_drop",
        RunState.FINALIZED_FAILED,
        started_at=now - timedelta(days=5),
    )

    deleted = prune_runs(select_prunable_runs(tmp_path, keep=1))

    assert deleted == ["run_drop"]
    assert not old_dir.exists()
    assert (tmp_path / "run_keep").exists()
