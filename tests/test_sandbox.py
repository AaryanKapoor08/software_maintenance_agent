from __future__ import annotations

from pathlib import Path

from patchpilot.agent import load_task
from patchpilot.models import CommandStatus
from patchpilot.sandbox import LocalSandbox
from patchpilot.storage import TraceStore


def test_local_sandbox_copies_fixture_and_blocks_unsafe_command(tmp_path: Path) -> None:
    task = load_task(Path("examples/tasks/python_email_empty.json"))
    trace = TraceStore(tmp_path / "trace.sqlite")
    trace.init_run("run", task.id, tmp_path)
    sandbox = LocalSandbox("run", tmp_path, trace)
    prepared = sandbox.prepare(task)
    assert (prepared.repo_dir / "src/email_validator_app/validation.py").exists()
    result = sandbox.run("cat .env.local")
    assert result.status == CommandStatus.BLOCKED
