from __future__ import annotations

import os
import shutil
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, Field

from software_maintaince_agent.models import RunState
from software_maintaince_agent.storage import TraceStore

SUCCESS_STATES = {RunState.FINALIZED_SUCCESS.value}
FAILURE_STATES = {RunState.FINALIZED_FAILED.value, RunState.ESCALATED.value}


class RunRecord(BaseModel):
    run_id: str
    task_id: str
    status: str
    started_at: str
    updated_at: str
    run_dir: str
    has_patch: bool = False
    has_report: bool = False


class RunsSummary(BaseModel):
    total: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    by_task: dict[str, int] = Field(default_factory=dict)
    succeeded: int = 0
    failed: int = 0
    in_progress: int = 0
    success_rate: float = 0.0


def _record_for_dir(run_dir: Path) -> RunRecord | None:
    db_path = run_dir / "trace.sqlite"
    if not db_path.is_file():
        return None
    store = TraceStore(db_path)
    info = store.get_run(run_dir.name)
    if info is None:
        rows = store.list_runs()
        if not rows:
            return None
        info = rows[0]
    return RunRecord(
        run_id=info["run_id"],
        task_id=info["task_id"],
        status=info["status"],
        started_at=info["started_at"],
        updated_at=info["updated_at"],
        run_dir=str(run_dir),
        has_patch=(run_dir / "patch.diff").is_file(),
        has_report=(run_dir / "final_report.md").is_file(),
    )


def list_run_records(runs_dir: Path, status: str | None = None) -> list[RunRecord]:
    """Index every run directory under runs_dir, newest first."""
    if not runs_dir.is_dir():
        return []
    records: list[RunRecord] = []
    for child in runs_dir.iterdir():
        if not child.is_dir():
            continue
        record = _record_for_dir(child)
        if record is None:
            continue
        if status and record.status.lower() != status.lower():
            continue
        records.append(record)
    records.sort(key=lambda record: record.started_at, reverse=True)
    return records


def summarize_runs(records: list[RunRecord]) -> RunsSummary:
    summary = RunsSummary(total=len(records))
    for record in records:
        summary.by_status[record.status] = summary.by_status.get(record.status, 0) + 1
        summary.by_task[record.task_id] = summary.by_task.get(record.task_id, 0) + 1
        if record.status in SUCCESS_STATES:
            summary.succeeded += 1
        elif record.status in FAILURE_STATES:
            summary.failed += 1
        else:
            summary.in_progress += 1
    finished = summary.succeeded + summary.failed
    summary.success_rate = summary.succeeded / finished if finished else 0.0
    return summary


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def select_prunable_runs(
    runs_dir: Path,
    keep: int | None = None,
    older_than_days: int | None = None,
) -> list[RunRecord]:
    """Runs eligible for deletion. When both criteria are given a run must
    satisfy both (conservative intersection)."""
    if keep is None and older_than_days is None:
        raise ValueError("Provide keep and/or older_than_days to select prunable runs.")
    records = list_run_records(runs_dir)
    candidates = records[keep:] if keep is not None else list(records)
    if older_than_days is not None:
        cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
        candidates = [
            record for record in candidates if _parse_timestamp(record.started_at) < cutoff
        ]
    return candidates


def _chmod_and_retry(func, path, _exc):  # noqa: ANN001
    # Cloned repos leave read-only .git objects that rmtree cannot remove on Windows.
    os.chmod(path, stat.S_IWRITE)
    func(path)


def prune_runs(records: list[RunRecord]) -> list[str]:
    """Delete the run directories for the given records. Returns deleted run ids."""
    deleted: list[str] = []
    for record in records:
        run_dir = Path(record.run_dir)
        if run_dir.is_dir():
            shutil.rmtree(run_dir, onexc=_chmod_and_retry)
            deleted.append(record.run_id)
    return deleted
