from __future__ import annotations

import time
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from patchpilot.agent import PatchPilotAgent, load_task
from patchpilot.dashboard import serve_dashboard
from patchpilot.evals.benchmark import run_retrieval_benchmark
from patchpilot.github_integration import fetch_issue_task
from patchpilot.settings import Settings
from patchpilot.storage import TraceStore

app = typer.Typer(help="PatchPilot: CI failure to tested draft-PR-ready patch.")
console = Console()


@app.command()
def run(
    task: Annotated[Path | None, typer.Option("--task", help="Local task JSON file.")] = None,
    issue: Annotated[str | None, typer.Option("--issue", help="GitHub issue URL.")] = None,
    sandbox: Annotated[str, typer.Option("--sandbox", help="Sandbox adapter: local or e2b.")] = "local",
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

    report = PatchPilotAgent(settings).run_task(
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
        console.print(
            "[yellow]Draft PR creation is gated behind GITHUB_TOKEN and controlled-repo proof. "
            "A local PR-ready report was generated for this run.[/yellow]"
        )


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
def dashboard(
    host: Annotated[str, typer.Option("--host", help="Dashboard host.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Dashboard port.")] = 8765,
    runs_dir: Annotated[Path, typer.Option("--runs-dir", help="Runs directory.")] = Path("runs"),
) -> None:
    serve_dashboard(host=host, port=port, runs_dir=runs_dir)


if __name__ == "__main__":
    app()
