from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from software_maintaince_agent.command_policy import CommandPolicy
from software_maintaince_agent.models import CommandResult, CommandStatus, MaintenanceTask, RunState
from software_maintaince_agent.redaction import redact
from software_maintaince_agent.storage import TraceStore


class SandboxError(RuntimeError):
    pass


@dataclass
class PreparedSandbox:
    repo_dir: Path
    sandbox_kind: str
    blocker: str | None = None


class LocalSandbox:
    """Trusted local sandbox used only for controlled fixtures."""

    def __init__(
        self,
        run_id: str,
        run_dir: Path,
        trace: TraceStore,
        trusted_fixture: bool = True,
    ) -> None:
        self.run_id = run_id
        self.run_dir = run_dir
        self.trace = trace
        self.trusted_fixture = trusted_fixture
        self.repo_dir = run_dir / "repo"
        self.policy = CommandPolicy()

    def prepare(self, task: MaintenanceTask) -> PreparedSandbox:
        source = Path(task.repo_url)
        if not source.exists():
            raise SandboxError(
                "Local sandbox can only run trusted local paths. Use E2B or a remote sandbox for URLs."
            )
        if not self.trusted_fixture and task.source != "local_fixture":
            raise SandboxError("Local sandbox refused a non-fixture task.")
        if self.repo_dir.exists():
            shutil.rmtree(self.repo_dir)
        ignore = shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".env", ".env.*")
        shutil.copytree(source, self.repo_dir, ignore=ignore)
        self.policy = CommandPolicy(blocked_paths=task.blocked_paths)
        self.trace.event(
            self.run_id,
            "sandbox",
            "Trusted local fixture copied into sandbox run directory",
            {"repo_dir": str(self.repo_dir)},
            RunState.SANDBOX_READY,
        )
        return PreparedSandbox(repo_dir=self.repo_dir, sandbox_kind="local")

    def run(self, command: str, timeout_seconds: int = 120) -> CommandResult:
        decision = self.policy.validate(command, self.repo_dir)
        if not decision.allowed:
            result = CommandResult(
                command=command,
                exit_code=126,
                status=CommandStatus.BLOCKED,
                duration_ms=0,
                failure_summary=decision.reason,
            )
            self.trace.event(
                self.run_id,
                "command_blocked",
                decision.reason,
                {"command": command},
                RunState.ESCALATED,
            )
            return result

        started = time.perf_counter()
        try:
            proc = subprocess.run(
                decision.tokens,
                cwd=self.repo_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                shell=False,
            )
            duration_ms = int((time.perf_counter() - started) * 1000)
            status = CommandStatus.PASSED if proc.returncode == 0 else CommandStatus.FAILED
            result = CommandResult(
                command=command,
                exit_code=proc.returncode,
                status=status,
                duration_ms=duration_ms,
                stdout=redact(proc.stdout[-6000:]),
                stderr=redact(proc.stderr[-6000:]),
                failure_summary=summarize_failure(proc.stdout, proc.stderr, proc.returncode),
            )
        except subprocess.TimeoutExpired as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            result = CommandResult(
                command=command,
                exit_code=124,
                status=CommandStatus.TIMED_OUT,
                duration_ms=duration_ms,
                stdout=redact(exc.stdout or ""),
                stderr=redact(exc.stderr or ""),
                failure_summary=f"Command timed out after {timeout_seconds}s",
            )

        self.trace.event(
            self.run_id,
            "command",
            f"{command} => {result.status.value}",
            {
                "command": command,
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
                "stdout_excerpt": result.stdout[-1200:],
                "stderr_excerpt": result.stderr[-1200:],
                "failure_summary": result.failure_summary,
            },
            RunState.TESTS_RUNNING if "pytest" in command else None,
        )
        return result

    def close(self) -> None:
        return


SANDBOX_IMAGE = "ama-sandbox:py312"
SANDBOX_DOCKERFILE = """\
FROM python:3.12-slim
RUN apt-get update \\
    && apt-get install -y --no-install-recommends git ripgrep \\
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir pytest
WORKDIR /work
"""


class DockerSandbox:
    """Isolated sandbox that executes every command inside a per-run Docker container.

    The repository is materialized on the host (local copy or shallow git clone),
    mounted into the container at /work, dependencies are installed while the
    container still has network access, and the network is disconnected before
    any agent command runs.
    """

    def __init__(self, run_id: str, run_dir: Path, trace: TraceStore) -> None:
        self.run_id = run_id
        self.run_dir = run_dir
        self.trace = trace
        self.repo_dir = run_dir / "repo"
        self.policy = CommandPolicy()
        self.image = os.getenv("AMA_DOCKER_IMAGE", SANDBOX_IMAGE)
        self.container = f"ama-{run_id}".replace("_", "-")
        self._started = False

    def prepare(self, task: MaintenanceTask) -> PreparedSandbox:
        self._require_docker()
        self._ensure_image()
        self._materialize_repo(task)
        self.policy = CommandPolicy(blocked_paths=task.blocked_paths)
        mount = str(self.repo_dir.resolve()).replace("\\", "/")
        self._docker(
            [
                "run",
                "-d",
                "--name",
                self.container,
                "--memory",
                "2g",
                "--cpus",
                "2",
                "--pids-limit",
                "256",
                "-v",
                f"{mount}:/work",
                "-w",
                "/work",
                self.image,
                "sleep",
                "infinity",
            ],
            error="Failed to start the sandbox container.",
        )
        self._started = True
        self._install_dependencies()
        self._disconnect_network()
        self.trace.event(
            self.run_id,
            "sandbox",
            "Docker sandbox container running with network disconnected",
            {"container": self.container, "image": self.image, "repo_dir": str(self.repo_dir)},
            RunState.SANDBOX_READY,
        )
        return PreparedSandbox(repo_dir=self.repo_dir, sandbox_kind="docker")

    def run(self, command: str, timeout_seconds: int = 120) -> CommandResult:
        decision = self.policy.validate(command, self.repo_dir)
        if not decision.allowed:
            result = CommandResult(
                command=command,
                exit_code=126,
                status=CommandStatus.BLOCKED,
                duration_ms=0,
                failure_summary=decision.reason,
            )
            self.trace.event(
                self.run_id,
                "command_blocked",
                decision.reason,
                {"command": command},
                RunState.ESCALATED,
            )
            return result

        started = time.perf_counter()
        try:
            proc = subprocess.run(
                ["docker", "exec", self.container, *decision.tokens],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                shell=False,
            )
            duration_ms = int((time.perf_counter() - started) * 1000)
            status = CommandStatus.PASSED if proc.returncode == 0 else CommandStatus.FAILED
            result = CommandResult(
                command=command,
                exit_code=proc.returncode,
                status=status,
                duration_ms=duration_ms,
                stdout=redact(proc.stdout[-6000:]),
                stderr=redact(proc.stderr[-6000:]),
                failure_summary=summarize_failure(proc.stdout, proc.stderr, proc.returncode),
            )
        except subprocess.TimeoutExpired as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            result = CommandResult(
                command=command,
                exit_code=124,
                status=CommandStatus.TIMED_OUT,
                duration_ms=duration_ms,
                stdout=redact(str(exc.stdout or "")),
                stderr=redact(str(exc.stderr or "")),
                failure_summary=f"Command timed out after {timeout_seconds}s",
            )

        self.trace.event(
            self.run_id,
            "command",
            f"{command} => {result.status.value}",
            {
                "command": command,
                "container": self.container,
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
                "stdout_excerpt": result.stdout[-1200:],
                "stderr_excerpt": result.stderr[-1200:],
                "failure_summary": result.failure_summary,
            },
            RunState.TESTS_RUNNING if "pytest" in command else None,
        )
        return result

    def close(self) -> None:
        if not self._started:
            return
        subprocess.run(
            ["docker", "rm", "-f", self.container],
            capture_output=True,
            text=True,
                encoding="utf-8",
                errors="replace",
            timeout=60,
        )
        self._started = False
        self.trace.event(
            self.run_id,
            "sandbox",
            "Docker sandbox container removed",
            {"container": self.container},
        )

    def _require_docker(self) -> None:
        try:
            proc = subprocess.run(
                ["docker", "version", "--format", "{{.Server.Version}}"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SandboxError(f"Docker is not available: {exc}") from exc
        if proc.returncode != 0:
            raise SandboxError(
                "Docker daemon is not running. Start Docker Desktop and rerun, "
                "or use --sandbox local for trusted fixtures."
            )

    def _ensure_image(self) -> None:
        inspect = subprocess.run(
            ["docker", "image", "inspect", self.image],
            capture_output=True,
            text=True,
                encoding="utf-8",
                errors="replace",
            timeout=60,
        )
        if inspect.returncode == 0:
            return
        dockerfile = self.run_dir / "sandbox.Dockerfile"
        dockerfile.write_text(SANDBOX_DOCKERFILE, encoding="utf-8")
        self.trace.event(
            self.run_id,
            "sandbox",
            f"Building sandbox image {self.image} (first run only)",
            {"image": self.image},
        )
        self._docker(
            ["build", "-t", self.image, "-f", str(dockerfile), str(self.run_dir)],
            error=f"Failed to build sandbox image {self.image}.",
            timeout=600,
        )

    def _materialize_repo(self, task: MaintenanceTask) -> None:
        if self.repo_dir.exists():
            shutil.rmtree(self.repo_dir)
        if is_remote_repo(task.repo_url):
            clone = subprocess.run(
                ["git", "clone", "--depth", "1", task.repo_url, str(self.repo_dir)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
            )
            if clone.returncode != 0:
                raise SandboxError(f"git clone failed: {redact(clone.stderr[-800:])}")
            shutil.rmtree(self.repo_dir / ".git", ignore_errors=True)
            self.trace.event(
                self.run_id,
                "sandbox",
                "Repository cloned into sandbox run directory",
                {"repo_url": task.repo_url, "repo_dir": str(self.repo_dir)},
            )
            return
        source = Path(task.repo_url)
        if not source.exists():
            raise SandboxError(f"Repository path does not exist: {task.repo_url}")
        ignore = shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".env", ".env.*")
        shutil.copytree(source, self.repo_dir, ignore=ignore)
        self.trace.event(
            self.run_id,
            "sandbox",
            "Local repository copied into sandbox run directory",
            {"repo_dir": str(self.repo_dir)},
        )

    def _install_dependencies(self) -> None:
        install: list[str] | None = None
        if (self.repo_dir / "requirements.txt").exists():
            install = ["pip", "install", "--no-cache-dir", "-r", "requirements.txt"]
        elif (self.repo_dir / "pyproject.toml").exists():
            install = ["pip", "install", "--no-cache-dir", "-e", "."]
        if not install:
            return
        proc = subprocess.run(
            ["docker", "exec", self.container, *install],
            capture_output=True,
            text=True,
                encoding="utf-8",
                errors="replace",
            timeout=600,
        )
        self.trace.event(
            self.run_id,
            "sandbox",
            f"Dependency install {'succeeded' if proc.returncode == 0 else 'failed (continuing)'}",
            {
                "command": " ".join(install),
                "exit_code": proc.returncode,
                "stderr_excerpt": redact(proc.stderr[-800:]),
            },
        )

    def _disconnect_network(self) -> None:
        subprocess.run(
            ["docker", "network", "disconnect", "bridge", self.container],
            capture_output=True,
            text=True,
                encoding="utf-8",
                errors="replace",
            timeout=60,
        )

    def _docker(self, args: list[str], error: str, timeout: int = 120) -> None:
        try:
            proc = subprocess.run(
                ["docker", *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise SandboxError(f"{error} (timed out after {timeout}s)") from exc
        if proc.returncode != 0:
            raise SandboxError(f"{error} {redact(proc.stderr[-800:])}")


def is_remote_repo(repo_url: str) -> bool:
    return repo_url.startswith(("http://", "https://", "git@", "ssh://"))


class E2BSandbox:
    """E2B adapter that records a blocker until remote sandbox execution is configured."""

    def __init__(self, run_id: str, run_dir: Path, trace: TraceStore) -> None:
        self.run_id = run_id
        self.run_dir = run_dir
        self.trace = trace

    def prepare(self, task: MaintenanceTask) -> PreparedSandbox:
        if not os.getenv("E2B_API_KEY"):
            blocker = "E2B_API_KEY is not configured; use the Docker sandbox (--sandbox docker) for isolated local execution."
            self.trace.event(
                self.run_id,
                "blocker",
                blocker,
                {"sandbox": "e2b", "task_id": task.id},
                RunState.ESCALATED,
            )
            return PreparedSandbox(repo_dir=self.run_dir / "repo", sandbox_kind="e2b", blocker=blocker)
        blocker = (
            "E2B credentials are present, but remote sandbox execution is not enabled in this build; "
            "use the Docker sandbox (--sandbox docker) for isolated local execution."
        )
        self.trace.event(
            self.run_id,
            "blocker",
            blocker,
            {"sandbox": "e2b", "task_id": task.id},
            RunState.ESCALATED,
        )
        return PreparedSandbox(repo_dir=self.run_dir / "repo", sandbox_kind="e2b", blocker=blocker)


def summarize_failure(stdout: str, stderr: str, exit_code: int) -> str | None:
    if exit_code == 0:
        return None
    combined = f"{stdout}\n{stderr}"
    interesting = []
    for line in combined.splitlines():
        stripped = line.strip()
        if (
            stripped.startswith("E ")
            or "FAILED" in stripped
            or "AssertionError" in stripped
            or "Error:" in stripped
        ):
            interesting.append(stripped)
    return redact("\n".join(interesting[-8:]) or f"Command exited with {exit_code}")
