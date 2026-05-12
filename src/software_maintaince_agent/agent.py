from __future__ import annotations

import json
import time
from pathlib import Path
from uuid import uuid4

from software_maintaince_agent.llm import provider_for
from software_maintaince_agent.models import (
    AgentPlan,
    CommandResult,
    CommandStatus,
    FinalReport,
    MaintenanceTask,
    PatchAttempt,
    RunState,
)
from software_maintaince_agent.patching import FileChange, HeuristicPatcher, PatchSafetyError, unified_diff, write_changes
from software_maintaince_agent.repo_inspect import inspect_repo, iter_repo_files
from software_maintaince_agent.report import write_report
from software_maintaince_agent.retrieval import hybrid_retrieve, lexical_retrieve
from software_maintaince_agent.risk import score_risk
from software_maintaince_agent.sandbox import E2BSandbox, LocalSandbox, SandboxError
from software_maintaince_agent.settings import Settings
from software_maintaince_agent.storage import TraceStore


def load_task(path: Path) -> MaintenanceTask:
    return MaintenanceTask.model_validate_json(path.read_text(encoding="utf-8"))


class SoftwareMaintainceAgent:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()

    def run_task(
        self,
        task: MaintenanceTask,
        sandbox_kind: str = "local",
        dry_run: bool = False,
        runs_dir: Path | None = None,
    ) -> FinalReport:
        run_id = f"{time.strftime('%Y%m%d_%H%M%S')}_{task.id}_{uuid4().hex[:8]}"
        root_runs_dir = runs_dir or self.settings.runs_dir
        run_dir = root_runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        trace = TraceStore(run_dir / "trace.sqlite")
        trace.init_run(run_id, task.id, run_dir)
        trace.update_status(run_id, RunState.INTAKE_VALIDATED)
        (run_dir / "task.json").write_text(task.model_dump_json(indent=2), encoding="utf-8")

        provider = provider_for(self.settings.llm_provider)
        provider_status = provider.status()
        trace.event(
            run_id,
            "llm_provider",
            f"Provider {provider_status.name}: {provider_status.available}",
            provider_status.__dict__,
        )

        if dry_run:
            report = FinalReport(
                status="success",
                risk_level="low",
                issue_understanding=summarize_issue(task),
                what_changed=["Dry run only; no sandbox commands or file edits were executed."],
                changed_files=[],
                tests_run=[],
                how_to_test=["Run the same command without `--dry-run`."],
                rollback_plan=["No changes were made."],
                known_limitations=[],
                trace=["intake validated", "dry run completed"],
            )
            risk = score_risk([], 0, [], attempts=0)
            report_path = write_report(run_dir, report, risk)
            report.report_path = str(report_path)
            trace.update_status(run_id, RunState.FINALIZED_SUCCESS)
            return report

        try:
            sandbox = self._prepare_sandbox(sandbox_kind, run_id, run_dir, trace, task)
        except SandboxError as exc:
            return self._finalize_blocked(run_id, run_dir, trace, task, str(exc))

        repo_dir = sandbox.repo_dir
        original_snapshot = snapshot_repo(repo_dir)
        summary = inspect_repo(repo_dir, task)
        trace.update_status(run_id, RunState.PROJECT_INSPECTED)
        trace.event(run_id, "repo_summary", "Project inspected", summary.model_dump())
        (run_dir / "repo_summary.json").write_text(summary.model_dump_json(indent=2), encoding="utf-8")

        focused_command = task.focused_test_command or summary.focused_test_command
        baseline_result: CommandResult | None = None
        if focused_command:
            baseline_result = sandbox.run(focused_command)
            trace.update_status(run_id, RunState.BASELINE_TESTED)

        log_text = ""
        if baseline_result:
            log_text = f"{baseline_result.stdout}\n{baseline_result.stderr}"
        lexical_candidates = lexical_retrieve(repo_dir, task, log_text=log_text, top_k=8)
        candidates = hybrid_retrieve(repo_dir, task, log_text=log_text, top_k=8)
        trace.update_status(run_id, RunState.FILES_SELECTED)
        trace.event(
            run_id,
            "retrieval",
            "Relevant files selected with hybrid RRF retrieval",
            {
                "method": "hybrid_rrf",
                "candidates": [candidate.model_dump() for candidate in candidates],
                "lexical_baseline": [candidate.model_dump() for candidate in lexical_candidates],
            },
        )
        (run_dir / "selected_files.json").write_text(
            json.dumps([candidate.model_dump() for candidate in candidates], indent=2),
            encoding="utf-8",
        )

        plan = build_agent_plan(task, [candidate.path for candidate in candidates], summary.test_commands)
        trace.update_status(run_id, RunState.PATCH_PLANNED)
        trace.event(run_id, "plan", "Patch plan created", plan.model_dump())
        (run_dir / "agent_plan.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")

        attempts: list[PatchAttempt] = []
        patcher = HeuristicPatcher()
        final_tests: list[CommandResult] = []
        patch_diff = ""
        changed_files: list[str] = []
        known_limitations: list[str] = []

        for attempt_number in range(1, task.max_attempts + 1):
            selected_files = plan.files_to_edit or plan.files_to_read
            changes = patcher.plan_changes(repo_dir, task, selected_files, attempt_number)
            if not changes:
                attempts.append(
                    PatchAttempt(
                        attempt=attempt_number,
                        result="blocked",
                        failure_reason="No safe deterministic patch was identified.",
                    )
                )
                known_limitations.append("The local fallback patcher could not identify a safe edit.")
                break

            try:
                write_changes(repo_dir, task, changes)
            except PatchSafetyError as exc:
                attempts.append(
                    PatchAttempt(
                        attempt=attempt_number,
                        result="blocked",
                        failure_reason=str(exc),
                    )
                )
                known_limitations.append(str(exc))
                break

            changed_files = [change.path for change in changes]
            patch_diff = cumulative_diff(repo_dir, original_snapshot, changed_files)
            (run_dir / "patch.diff").write_text(patch_diff, encoding="utf-8")
            trace.update_status(run_id, RunState.PATCH_APPLIED)
            trace.event(
                run_id,
                "patch",
                "Patch applied in sandbox copy",
                {"files_changed": changed_files, "diff_lines": len(patch_diff.splitlines())},
            )

            commands_run: list[CommandResult] = []
            if focused_command:
                focused_result = sandbox.run(focused_command)
                commands_run.append(focused_result)
                final_tests.append(focused_result)
            else:
                known_limitations.append("No focused test command was detected.")

            if commands_run and all(result.status == CommandStatus.PASSED for result in commands_run):
                broad_commands = [command for command in summary.test_commands if command != focused_command]
                for command in broad_commands[:1]:
                    broad_result = sandbox.run(command)
                    commands_run.append(broad_result)
                    final_tests.append(broad_result)
                result = "passed" if all(cmd.status == CommandStatus.PASSED for cmd in commands_run) else "failed"
            else:
                result = "failed"

            attempt = PatchAttempt(
                attempt=attempt_number,
                files_changed=changed_files,
                diff_summary=summarize_diff(changed_files, patch_diff),
                commands_run=commands_run,
                result=result,
                failure_reason=commands_run[-1].failure_summary if result == "failed" and commands_run else None,
            )
            attempts.append(attempt)
            trace.event(run_id, "attempt", f"Patch attempt {attempt_number} {result}", attempt.model_dump())

            if result == "passed":
                trace.update_status(run_id, RunState.TESTS_PASSED)
                break
            trace.update_status(run_id, RunState.REPAIR_ATTEMPTED)

        success = bool(attempts and attempts[-1].result == "passed")
        if not success:
            trace.update_status(run_id, RunState.TESTS_FAILED)

        diff_lines = len(patch_diff.splitlines())
        risk = score_risk(changed_files, diff_lines, final_tests, attempts=len(attempts))
        issue_understanding = summarize_issue(task)
        tests_run = [result.command + f" => {result.status.value}" for result in final_tests]
        report = FinalReport(
            status="success" if success else "failed",
            risk_level=risk.level,
            issue_understanding=issue_understanding,
            what_changed=what_changed(success, changed_files, attempts),
            changed_files=changed_files,
            tests_run=tests_run,
            how_to_test=[result.command for result in final_tests] or ["Run the project test suite."],
            rollback_plan=[
                "Discard the generated patch or revert the branch commit.",
                "No database migrations or external service changes were performed.",
            ],
            known_limitations=known_limitations,
            trace=[
                "intake validated",
                "sandbox prepared",
                "project inspected",
                "baseline test executed" if baseline_result else "baseline test unavailable",
                "files selected",
                "patch attempted",
                "tests passed" if success else "tests failed or patch blocked",
            ],
            patch_path=str(run_dir / "patch.diff") if patch_diff else None,
        )
        report_path = write_report(run_dir, report, risk)
        report.report_path = str(report_path)
        (run_dir / "attempts.json").write_text(
            json.dumps([attempt.model_dump(mode="json") for attempt in attempts], indent=2),
            encoding="utf-8",
        )
        trace.update_status(run_id, RunState.FINALIZED_SUCCESS if success else RunState.FINALIZED_FAILED)
        return report

    def _prepare_sandbox(
        self,
        sandbox_kind: str,
        run_id: str,
        run_dir: Path,
        trace: TraceStore,
        task: MaintenanceTask,
    ) -> LocalSandbox:
        if sandbox_kind == "e2b":
            prepared = E2BSandbox(run_id, run_dir, trace).prepare(task)
            if prepared.blocker:
                raise SandboxError(prepared.blocker)
        sandbox = LocalSandbox(run_id, run_dir, trace, trusted_fixture=task.source == "local_fixture")
        sandbox.prepare(task)
        trace.update_status(run_id, RunState.REPO_CLONED)
        return sandbox

    def _finalize_blocked(
        self,
        run_id: str,
        run_dir: Path,
        trace: TraceStore,
        task: MaintenanceTask,
        reason: str,
    ) -> FinalReport:
        risk = score_risk([], 0, [], attempts=0, blocked=True)
        report = FinalReport(
            status="blocked",
            risk_level="blocked",
            issue_understanding=summarize_issue(task),
            what_changed=["No code changes were made."],
            changed_files=[],
            tests_run=[],
            how_to_test=["Resolve the blocker and rerun the task."],
            rollback_plan=["No rollback is needed because no files were changed."],
            known_limitations=[reason],
            trace=["intake validated", "blocked before sandbox execution"],
        )
        report_path = write_report(run_dir, report, risk)
        report.report_path = str(report_path)
        trace.event(run_id, "blocker", reason, {"task_id": task.id}, RunState.ESCALATED)
        trace.update_status(run_id, RunState.FINALIZED_FAILED)
        return report


def build_agent_plan(task: MaintenanceTask, selected_files: list[str], test_commands: list[str]) -> AgentPlan:
    implementation_files = [path for path in selected_files if "/tests/" not in f"/{path}" and "test_" not in path]
    files_to_edit = implementation_files[:2] or selected_files[:1]
    return AgentPlan(
        issue_summary=summarize_issue(task),
        hypothesis="The failure is likely caused by validation behavior near the selected implementation files.",
        files_to_read=selected_files[:6],
        files_to_edit=files_to_edit,
        test_strategy=[
            f"Run focused command `{task.focused_test_command}`." if task.focused_test_command else "Run detected focused tests.",
            *[f"Run broader command `{command}`." for command in test_commands[:1]],
        ],
        risk_level="low" if len(files_to_edit) <= 2 else "medium",
    )


def summarize_issue(task: MaintenanceTask) -> str:
    body = task.body.strip()
    if body:
        return f"{task.title.strip()} - {body[:280]}"
    return task.title.strip()


def summarize_diff(changed_files: list[str], diff_text: str) -> str:
    additions = sum(1 for line in diff_text.splitlines() if line.startswith("+") and not line.startswith("+++"))
    deletions = sum(1 for line in diff_text.splitlines() if line.startswith("-") and not line.startswith("---"))
    return f"Changed {', '.join(changed_files)} with {additions} additions and {deletions} deletions."


def what_changed(success: bool, changed_files: list[str], attempts: list[PatchAttempt]) -> list[str]:
    if not changed_files:
        return ["No safe patch was produced."]
    result = "passing" if success else "attempted"
    summary = attempts[-1].diff_summary if attempts else ""
    return [f"Applied a {result} maintenance patch to {', '.join(changed_files)}.", summary]


def snapshot_repo(repo_dir: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in iter_repo_files(repo_dir):
        rel = path.relative_to(repo_dir).as_posix()
        try:
            snapshot[rel] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
    return snapshot


def cumulative_diff(repo_dir: Path, original_snapshot: dict[str, str], changed_files: list[str]) -> str:
    parts: list[str] = []
    for rel_path in dict.fromkeys(changed_files):
        current = (repo_dir / rel_path).read_text(encoding="utf-8")
        before = original_snapshot.get(rel_path, "")
        parts.append(unified_diff(FileChange(path=rel_path, before=before, after=current)))
    return "\n".join(parts)
