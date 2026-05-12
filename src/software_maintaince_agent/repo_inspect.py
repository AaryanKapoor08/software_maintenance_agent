from __future__ import annotations

import json
from pathlib import Path

from software_maintaince_agent.models import MaintenanceTask, RepoSummary

IGNORED_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules", ".venv", "dist", "build"}


def iter_repo_files(repo_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in repo_dir.rglob("*"):
        if not path.is_file():
            continue
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        if path.name.startswith(".env"):
            continue
        files.append(path)
    return sorted(files)


def inspect_repo(repo_dir: Path, task: MaintenanceTask | None = None) -> RepoSummary:
    files = iter_repo_files(repo_dir)
    names = {path.name for path in files}
    suffixes = {path.suffix for path in files}
    frameworks: list[str] = []
    package_manager = "unknown"
    language = "unknown"
    test_commands: list[str] = []
    entry_points: list[str] = []
    risk_notes: list[str] = []

    if "pyproject.toml" in names or ".py" in suffixes:
        language = "python"
        package_manager = "pip"
        if any("tests" in path.parts and path.name.startswith("test_") for path in files):
            frameworks.append("pytest")
            test_commands.append("python -m pytest")
        for candidate in ("src/app.py", "app.py", "main.py"):
            if (repo_dir / candidate).exists():
                entry_points.append(candidate)

    package_json = repo_dir / "package.json"
    if package_json.exists():
        language = "typescript/javascript" if language == "unknown" else f"{language}+js"
        package_manager = detect_node_package_manager(repo_dir)
        scripts = read_package_scripts(package_json)
        for script in ("test", "lint", "typecheck"):
            if script in scripts:
                test_commands.append(f"npm run {script}" if script != "test" else "npm test")

    if not test_commands:
        risk_notes.append("No test command detected.")

    focused = task.focused_test_command if task else None
    return RepoSummary(
        language=language,
        frameworks=frameworks,
        package_manager=package_manager,
        test_commands=test_commands,
        focused_test_command=focused,
        entry_points=entry_points,
        risk_notes=risk_notes,
        files_indexed=len(files),
    )


def detect_node_package_manager(repo_dir: Path) -> str:
    if (repo_dir / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (repo_dir / "yarn.lock").exists():
        return "yarn"
    return "npm"


def read_package_scripts(package_json: Path) -> dict[str, str]:
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    scripts = data.get("scripts", {})
    return scripts if isinstance(scripts, dict) else {}
