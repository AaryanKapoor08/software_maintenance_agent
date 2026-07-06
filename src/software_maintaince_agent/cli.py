from __future__ import annotations

import time
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from software_maintaince_agent.agent import SoftwareMaintainceAgent, load_task
from software_maintaince_agent.dashboard import serve_dashboard
from software_maintaince_agent.evals.benchmark import run_retrieval_benchmark
from software_maintaince_agent.github_integration import fetch_issue_task
from software_maintaince_agent.publisher import PublishError, publish_patch
from software_maintaince_agent.run_index import (
    list_run_records,
    prune_runs,
    select_prunable_runs,
    summarize_runs,
)
from software_maintaince_agent.settings import Settings
from software_maintaince_agent.storage import TraceStore

app = typer.Typer(help="Software Maintenance Agent: run small, tested maintenance patches locally.")
console = Console()


@app.command()
def run(
    task: Annotated[Path | None, typer.Option("--task", help="Local task JSON file.")] = None,
    issue: Annotated[str | None, typer.Option("--issue", help="GitHub issue URL.")] = None,
    sandbox: Annotated[str, typer.Option("--sandbox", help="Sandbox adapter: docker, local, or e2b.")] = "docker",
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Validate and plan without edits.")] = False,
    create_pr: Annotated[bool, typer.Option("--create-pr", help="Create draft PR when configured.")] = False,
) -> None:
    settings = Settings.from_env()
    if not task and not issue:
        task = Path("examples/tasks/python_email_empty.json")
    if task and issue:
        raise typer.BadParameter("Provide either --task or --issue, not both.")

    if issue:
        maintenance_task = fetch_issue_task(issue)
    else:
        assert task is not None
        maintenance_task = load_task(task)

    report = SoftwareMaintainceAgent(settings).run_task(
        maintenance_task,
        sandbox_kind=sandbox,
        dry_run=dry_run,
    )
    console.print(f"[bold]Status:[/bold] {report.status}")
    console.print(f"[bold]Risk:[/bold] {report.risk_level}")
    if report.report_path:
        console.print(f"[bold]Report:[/bold] {report.report_path}")
    if report.patch_path:
        console.print(f"[bold]Patch:[/bold] {report.patch_path}")
    if create_pr:
        if report.status != "success" or not report.report_path:
            console.print("[yellow]Skipping publish: only successful runs with a patch are published.[/yellow]")
            return
        run_dir = Path(report.report_path).parent
        run_id = run_dir.name
        trace_store = TraceStore(run_dir / "trace.sqlite")
        try:
            published = publish_patch(maintenance_task, report, run_id, run_dir, trace_store)
        except PublishError as exc:
            console.print(f"[red]Publish failed:[/red] {exc}")
            return
        console.print(f"[bold]Branch:[/bold] {published['branch']}")
        if published.get("pr_url"):
            console.print(f"[bold]Draft PR:[/bold] {published['pr_url']}")


@app.command()
def benchmark(
    suite: Annotated[Path, typer.Option("--suite", help="Benchmark suite JSON file.")] = Path(
        "benchmark/suites/mvp.json"
    ),
) -> None:
    output_dir = Settings.from_env().runs_dir / "benchmarks" / time.strftime("%Y%m%d_%H%M%S")
    report = run_retrieval_benchmark(suite, output_dir)
    table = Table(title=f"Retrieval Benchmark: {report.suite}")
    table.add_column("Method")
    table.add_column("Top-1", justify="right")
    table.add_column("Top-3", justify="right")
    table.add_column("Top-5", justify="right")
    table.add_column("Context", justify="right")
    table.add_column("Latency ms", justify="right")
    for metric in report.metrics:
        table.add_row(
            metric.method,
            f"{metric.top_1_recall:.3f}",
            f"{metric.top_3_recall:.3f}",
            f"{metric.top_5_recall:.3f}",
            f"{metric.average_context_files:.2f}",
            str(metric.latency_ms),
        )
    console.print(table)
    console.print(f"[bold]Code-JEPA status:[/bold] {report.jepa_status}")
    console.print(f"[bold]Report:[/bold] {report.report_path}")


@app.command()
def trace(
    run_id: Annotated[str, typer.Option("--run-id", help="Run id under runs/.")],
    runs_dir: Annotated[Path, typer.Option("--runs-dir", help="Runs directory.")] = Path("runs"),
) -> None:
    db_path = runs_dir / run_id / "trace.sqlite"
    if not db_path.exists():
        raise typer.BadParameter(f"Trace database not found: {db_path}")
    store = TraceStore(db_path)
    run_info = store.get_run(run_id)
    if not run_info:
        raise typer.BadParameter(f"Run not found in trace database: {run_id}")
    console.print(f"[bold]Run:[/bold] {run_id}")
    console.print(f"[bold]Status:[/bold] {run_info['status']}")
    table = Table(title="Trace Events")
    table.add_column("Time")
    table.add_column("State")
    table.add_column("Kind")
    table.add_column("Message")
    for event in store.list_events(run_id):
        table.add_row(
            event["timestamp"].split("T")[-1][:8],
            event["state"] or "",
            event["kind"],
            event["message"],
        )
    console.print(table)


@app.command()
def run_batch(
    tasks_dir: Annotated[Path, typer.Option("--tasks-dir", help="Directory of task JSON files.")] = Path(
        "examples/tasks"
    ),
    sandbox: Annotated[str, typer.Option("--sandbox", help="Sandbox adapter: docker, local, or e2b.")] = "docker",
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Validate and plan without edits.")] = False,
    runs_dir: Annotated[Path | None, typer.Option("--runs-dir", help="Override runs directory.")] = None,
) -> None:
    """Run every task JSON in a directory and print a summary table."""
    task_files = sorted(tasks_dir.glob("*.json"))
    if not task_files:
        raise typer.BadParameter(f"No task JSON files found in: {tasks_dir}")
    settings = Settings.from_env()
    agent = SoftwareMaintainceAgent(settings)
    results: list[tuple[str, str, str, str]] = []
    any_failed = False
    for task_file in task_files:
        try:
            maintenance_task = load_task(task_file)
            report = agent.run_task(
                maintenance_task,
                sandbox_kind=sandbox,
                dry_run=dry_run,
                runs_dir=runs_dir,
            )
            status, risk = report.status, report.risk_level
            detail = report.report_path or ""
        except Exception as exc:  # keep the batch going when one task blows up
            status, risk, detail = "error", "-", str(exc)
        if status != "success":
            any_failed = True
        results.append((task_file.name, status, risk, detail))
    table = Table(title=f"Batch: {len(task_files)} task(s) from {tasks_dir}")
    table.add_column("Task file")
    table.add_column("Status")
    table.add_column("Risk")
    table.add_column("Report")
    for name, status, risk, detail in results:
        color = "green" if status == "success" else "red"
        table.add_row(name, f"[{color}]{status}[/{color}]", risk, detail)
    console.print(table)
    if any_failed:
        raise typer.Exit(code=1)


@app.command()
def runs(
    runs_dir: Annotated[Path, typer.Option("--runs-dir", help="Runs directory.")] = Path("runs"),
    limit: Annotated[int, typer.Option("--limit", help="Show at most N runs (0 = all).")] = 20,
    status: Annotated[str | None, typer.Option("--status", help="Filter by run state, e.g. FINALIZED_SUCCESS.")] = None,
) -> None:
    """List past runs, newest first."""
    records = list_run_records(runs_dir, status=status)
    if not records:
        console.print(f"No runs found in {runs_dir}.")
        return
    shown = records if limit == 0 else records[:limit]
    table = Table(title=f"Runs ({len(shown)} of {len(records)})")
    table.add_column("Run ID", overflow="fold")
    table.add_column("Task", overflow="fold")
    table.add_column("Status")
    table.add_column("Started")
    table.add_column("Patch")
    table.add_column("Report")
    for record in shown:
        color = (
            "green"
            if record.status == "FINALIZED_SUCCESS"
            else "red"
            if record.status in ("FINALIZED_FAILED", "ESCALATED")
            else "yellow"
        )
        table.add_row(
            record.run_id,
            record.task_id,
            f"[{color}]{record.status}[/{color}]",
            record.started_at.replace("T", " ")[:19],
            "yes" if record.has_patch else "-",
            "yes" if record.has_report else "-",
        )
    console.print(table)


@app.command()
def stats(
    runs_dir: Annotated[Path, typer.Option("--runs-dir", help="Runs directory.")] = Path("runs"),
) -> None:
    """Aggregate outcomes across all runs."""
    records = list_run_records(runs_dir)
    if not records:
        console.print(f"No runs found in {runs_dir}.")
        return
    summary = summarize_runs(records)
    table = Table(title="Run Statistics")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Total runs", str(summary.total))
    table.add_row("Succeeded", f"[green]{summary.succeeded}[/green]")
    table.add_row("Failed / escalated", f"[red]{summary.failed}[/red]")
    table.add_row("In progress / other", str(summary.in_progress))
    table.add_row("Success rate", f"{summary.success_rate:.1%}")
    console.print(table)
    by_task = Table(title="Runs by Task")
    by_task.add_column("Task")
    by_task.add_column("Runs", justify="right")
    for task_id, count in sorted(summary.by_task.items(), key=lambda item: -item[1]):
        by_task.add_row(task_id, str(count))
    console.print(by_task)


@app.command()
def report(
    run_id: Annotated[str, typer.Option("--run-id", help="Run id under runs/.")],
    runs_dir: Annotated[Path, typer.Option("--runs-dir", help="Runs directory.")] = Path("runs"),
) -> None:
    """Show the final report for a run."""
    report_path = runs_dir / run_id / "final_report.md"
    if not report_path.is_file():
        raise typer.BadParameter(f"No final report found: {report_path}")
    console.print(Markdown(report_path.read_text(encoding="utf-8")))


@app.command()
def clean(
    runs_dir: Annotated[Path, typer.Option("--runs-dir", help="Runs directory.")] = Path("runs"),
    keep: Annotated[int | None, typer.Option("--keep", help="Keep only the N most recent runs.")] = None,
    older_than_days: Annotated[
        int | None, typer.Option("--older-than-days", help="Only prune runs older than N days.")
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="Actually delete; otherwise just preview.")] = False,
) -> None:
    """Prune old run directories. Preview by default; pass --force to delete."""
    if keep is None and older_than_days is None:
        raise typer.BadParameter("Provide --keep and/or --older-than-days.")
    candidates = select_prunable_runs(runs_dir, keep=keep, older_than_days=older_than_days)
    if not candidates:
        console.print("Nothing to prune.")
        return
    for record in candidates:
        console.print(f"  {record.run_id} ({record.status}, started {record.started_at[:19]})")
    if not force:
        console.print(
            f"[yellow]Preview only:[/yellow] {len(candidates)} run(s) would be deleted. "
            "Re-run with --force to delete."
        )
        return
    deleted = prune_runs(candidates)
    console.print(f"[bold]Deleted {len(deleted)} run(s).[/bold]")


@app.command()
def dashboard(
    host: Annotated[str, typer.Option("--host", help="Dashboard host.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Dashboard port.")] = 8765,
    runs_dir: Annotated[Path, typer.Option("--runs-dir", help="Runs directory.")] = Path("runs"),
) -> None:
    serve_dashboard(host=host, port=port, runs_dir=runs_dir)


if __name__ == "__main__":
    app()
