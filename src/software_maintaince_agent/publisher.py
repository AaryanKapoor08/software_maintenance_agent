from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

from software_maintaince_agent.models import FinalReport, MaintenanceTask
from software_maintaince_agent.redaction import redact
from software_maintaince_agent.sandbox import is_remote_repo
from software_maintaince_agent.storage import TraceStore


class PublishError(RuntimeError):
    pass


def publish_patch(
    task: MaintenanceTask,
    report: FinalReport,
    run_id: str,
    run_dir: Path,
    trace: TraceStore,
) -> dict[str, str]:
    """Push a successful run's patch to a new branch and open a draft PR.

    Only ever pushes a fresh `ama/<run_id>` branch; never touches the default branch.
    """
    if report.status != "success":
        raise PublishError(f"Refusing to publish a run with status '{report.status}'.")
    patch_path = Path(report.patch_path or "")
    if not patch_path.exists() or not patch_path.read_text(encoding="utf-8").strip():
        raise PublishError("Run produced no patch to publish.")
    if not is_remote_repo(task.repo_url):
        raise PublishError("Publishing requires a remote git URL as the task repo_url.")

    workdir = (run_dir / "publish").resolve()
    if workdir.exists():
        _force_rmtree(workdir)
    branch = f"ama/{run_id}"

    _git(["clone", "--depth", "1", task.repo_url, str(workdir)], cwd=run_dir.resolve())
    _git(["checkout", "-b", branch], cwd=workdir)
    _git(["apply", "--whitespace=nowarn", str(patch_path.resolve())], cwd=workdir)
    _git(["add", "-A"], cwd=workdir)
    _git(
        [
            "commit",
            "-m",
            f"{task.title}\n\nAutomated patch by software maintenance agent (run {run_id}).",
        ],
        cwd=workdir,
    )
    _git(["push", "-u", "origin", branch], cwd=workdir)

    result: dict[str, str] = {"branch": branch, "repo": task.repo_url}
    pr_url = _create_draft_pr(task, run_id, branch, workdir)
    if pr_url:
        result["pr_url"] = pr_url

    (run_dir / "publish.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    trace.event(
        run_id,
        "publish",
        f"Patch pushed to branch {branch}" + (f"; draft PR {pr_url}" if pr_url else ""),
        result,
    )
    return result


def _create_draft_pr(task: MaintenanceTask, run_id: str, branch: str, workdir: Path) -> str | None:
    body = (
        f"Automated maintenance patch produced by run `{run_id}`.\n\n"
        f"**Issue:** {task.title}\n\n{task.body}\n\n"
        "Review the diff before merging; this PR was opened as a draft by the agent."
    )
    try:
        proc = subprocess.run(
            [
                "gh",
                "pr",
                "create",
                "--draft",
                "--title",
                f"[agent] {task.title}",
                "--body",
                body,
                "--head",
                branch,
            ],
            cwd=workdir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.startswith("https://"):
            return line
    return None


def _force_rmtree(path: Path) -> None:
    """Remove a tree that may contain git's read-only pack files (Windows)."""

    def on_error(func, target, _exc):  # noqa: ANN001 - shutil onexc signature
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            pass

    shutil.rmtree(path, onexc=on_error)


def _git(args: list[str], cwd: Path) -> None:
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    if proc.returncode != 0:
        raise PublishError(f"git {args[0]} failed: {redact(proc.stderr[-800:])}")
