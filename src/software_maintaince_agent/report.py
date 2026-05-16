from __future__ import annotations

from pathlib import Path

from software_maintaince_agent.models import FinalReport, RiskReport


def render_final_report(report: FinalReport, risk: RiskReport) -> str:
    changed_files = [f"- `{path}`" for path in report.changed_files] or ["- None"]
    tests_run = [f"- `{item}`" for item in report.tests_run] or ["- None"]
    how_to_test = [
        f"{index}. {item}" for index, item in enumerate(report.how_to_test, start=1)
    ] or ["1. No test command available."]
    known_limitations = [f"- {item}" for item in report.known_limitations] or ["- None"]
    lines = [
        "# Software Maintenance Agent Final Report",
        "",
        f"Status: **{report.status}**",
        f"Risk: **{report.risk_level}** ({risk.score}/100)",
        "",
        "## Summary",
        "",
        *[f"- {item}" for item in report.what_changed],
        "",
        "## Issue Understanding",
        "",
        report.issue_understanding,
        "",
        "## Changed Files",
        "",
        *changed_files,
        "",
        "## Tests Run",
        "",
        *tests_run,
        "",
        "## Risk Notes",
        "",
        *[f"- {reason}" for reason in risk.reasons],
        "",
        "## How To Test",
        "",
        *how_to_test,
        "",
        "## Rollback Plan",
        "",
        *[f"- {item}" for item in report.rollback_plan],
        "",
        "## Known Limitations",
        "",
        *known_limitations,
        "",
        "## Agent Trace",
        "",
        *[f"- {item}" for item in report.trace],
        "",
    ]
    return "\n".join(lines)


def write_report(run_dir: Path, report: FinalReport, risk: RiskReport) -> Path:
    path = run_dir / "final_report.md"
    path.write_text(render_final_report(report, risk), encoding="utf-8")
    return path
