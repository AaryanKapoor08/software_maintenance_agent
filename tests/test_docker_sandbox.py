from __future__ import annotations

import subprocess
from pathlib import Path

from software_maintaince_agent.agent import load_task
from software_maintaince_agent.models import CommandStatus
from software_maintaince_agent.sandbox import DockerSandbox, is_remote_repo
from software_maintaince_agent.storage import TraceStore


class FakeCompleted:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def make_sandbox(tmp_path: Path) -> tuple[DockerSandbox, list[list[str]]]:
    task = load_task(Path("examples/tasks/python_email_empty.json"))
    trace = TraceStore(tmp_path / "trace.sqlite")
    trace.init_run("run", task.id, tmp_path)
    sandbox = DockerSandbox("run", tmp_path, trace)
    calls: list[list[str]] = []
    return sandbox, calls


def test_docker_sandbox_prepare_starts_container_and_disconnects_network(
    tmp_path: Path, monkeypatch
) -> None:
    task = load_task(Path("examples/tasks/python_email_empty.json"))
    sandbox, calls = make_sandbox(tmp_path)

    def fake_run(args, **kwargs):
        calls.append(list(args))
        return FakeCompleted()

    monkeypatch.setattr(subprocess, "run", fake_run)
    prepared = sandbox.prepare(task)

    assert prepared.sandbox_kind == "docker"
    assert (prepared.repo_dir / "src/email_validator_app/validation.py").exists()
    joined = [" ".join(call) for call in calls]
    assert any(call[:2] == ["docker", "run"] for call in calls)
    run_call = next(call for call in calls if call[:2] == ["docker", "run"])
    assert "--network" not in run_call  # network on during dependency install
    assert any("--memory" in call for call in calls)
    assert any(call[:3] == ["docker", "network", "disconnect"] for call in calls)
    # fixture has pyproject.toml, so dependencies install inside the container
    assert any("pip install --no-cache-dir -e ." in cmd for cmd in joined)
    # sleeper keeps the container alive for exec
    assert run_call[-2:] == ["sleep", "infinity"]


def test_docker_sandbox_blocks_unsafe_command_without_calling_docker(
    tmp_path: Path, monkeypatch
) -> None:
    task = load_task(Path("examples/tasks/python_email_empty.json"))
    sandbox, calls = make_sandbox(tmp_path)

    def fake_run(args, **kwargs):
        calls.append(list(args))
        return FakeCompleted()

    monkeypatch.setattr(subprocess, "run", fake_run)
    sandbox.prepare(task)
    calls.clear()

    result = sandbox.run("cat .env.local")
    assert result.status == CommandStatus.BLOCKED
    assert not calls  # blocked before any docker exec

    result = sandbox.run("curl http://example.com")
    assert result.status == CommandStatus.BLOCKED
    assert not calls


def test_docker_sandbox_exec_runs_inside_container(tmp_path: Path, monkeypatch) -> None:
    task = load_task(Path("examples/tasks/python_email_empty.json"))
    sandbox, calls = make_sandbox(tmp_path)

    def fake_run(args, **kwargs):
        calls.append(list(args))
        return FakeCompleted(stdout="1 passed")

    monkeypatch.setattr(subprocess, "run", fake_run)
    sandbox.prepare(task)
    calls.clear()

    result = sandbox.run("python -m pytest tests/test_validation.py")
    assert result.status == CommandStatus.PASSED
    exec_call = calls[0]
    assert exec_call[:3] == ["docker", "exec", sandbox.container]
    assert exec_call[3:] == ["python", "-m", "pytest", "tests/test_validation.py"]


def test_docker_sandbox_close_removes_container(tmp_path: Path, monkeypatch) -> None:
    task = load_task(Path("examples/tasks/python_email_empty.json"))
    sandbox, calls = make_sandbox(tmp_path)

    def fake_run(args, **kwargs):
        calls.append(list(args))
        return FakeCompleted()

    monkeypatch.setattr(subprocess, "run", fake_run)
    sandbox.prepare(task)
    calls.clear()

    sandbox.close()
    assert calls[0][:3] == ["docker", "rm", "-f"]
    calls.clear()
    sandbox.close()  # idempotent: second close is a no-op
    assert not calls


def test_is_remote_repo() -> None:
    assert is_remote_repo("https://github.com/octocat/hello-world")
    assert is_remote_repo("git@github.com:octocat/hello-world.git")
    assert not is_remote_repo("examples/fixtures/email_validator_app")
    assert not is_remote_repo(r"C:\dev\some\local\path")
