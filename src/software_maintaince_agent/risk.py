from __future__ import annotations

from software_maintaince_agent.models import CommandResult, CommandStatus, RiskReport


def score_risk(
    changed_files: list[str],
    diff_lines: int,
    test_results: list[CommandResult],
    attempts: int,
    blocked: bool = False,
) -> RiskReport:
    if blocked:
        return RiskReport(level="blocked", score=100, reasons=["Safety policy or external blocker stopped the run."])

    score = 10
    reasons: list[str] = []
    if len(changed_files) <= 2:
        reasons.append("Small file change set.")
    else:
        score += 20
        reasons.append("Multiple files changed.")
    if diff_lines > 80:
        score += 20
        reasons.append("Diff is larger than the preferred MVP patch size.")
    if any("schema" in path or "config" in path for path in changed_files):
        score += 20
        reasons.append("Schema or config path touched.")
    if attempts > 1:
        score += 10
        reasons.append("Patch required repair attempts.")
    if test_results and all(result.status == CommandStatus.PASSED for result in test_results):
        score -= 10
        reasons.append("Focused/broad tests passed.")
    else:
        score += 25
        reasons.append("Tests were unavailable or did not all pass.")

    if score < 25:
        level = "low"
    elif score < 60:
        level = "medium"
    else:
        level = "high"
    return RiskReport(level=level, score=max(score, 0), reasons=reasons)
