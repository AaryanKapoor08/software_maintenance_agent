from __future__ import annotations

import difflib
import fnmatch
from pathlib import Path

from patchpilot.models import FileChange, MaintenanceTask


class PatchSafetyError(RuntimeError):
    pass


def validate_patch_path(path: str, task: MaintenanceTask) -> None:
    clean = path.replace("\\", "/")
    if clean.startswith("../") or "/../" in clean or clean.startswith("/"):
        raise PatchSafetyError(f"Patch path escapes repository: {path}")
    for pattern in task.blocked_paths:
        if fnmatch.fnmatch(clean, pattern):
            raise PatchSafetyError(f"Patch touches blocked path: {path}")
    if task.allowed_paths and not any(fnmatch.fnmatch(clean, pattern) for pattern in task.allowed_paths):
        raise PatchSafetyError(f"Patch path is outside allowed paths: {path}")


def unified_diff(change: FileChange) -> str:
    before_lines = change.before.splitlines(keepends=True)
    after_lines = change.after.splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=f"a/{change.path}",
            tofile=f"b/{change.path}",
        )
    )


def write_changes(repo_dir: Path, task: MaintenanceTask, changes: list[FileChange]) -> str:
    diff_parts: list[str] = []
    for change in changes:
        validate_patch_path(change.path, task)
        target = (repo_dir / change.path).resolve()
        target.relative_to(repo_dir.resolve())
        target.write_text(change.after, encoding="utf-8")
        diff_parts.append(unified_diff(change))
    return "\n".join(diff_parts)


class HeuristicPatcher:
    """Small deterministic patcher for the fixture proof and safe fallback demos."""

    def plan_changes(
        self,
        repo_dir: Path,
        task: MaintenanceTask,
        selected_files: list[str],
        attempt: int = 1,
    ) -> list[FileChange]:
        title_body = f"{task.title}\n{task.body}".lower()
        if "email" in title_body and ("empty" in title_body or "blank" in title_body):
            if attempt == 1 and "force-bad-first-patch" in task.labels:
                change = self._patch_docstring_only(repo_dir, selected_files)
            else:
                change = self._patch_empty_email(repo_dir, selected_files)
            return [change] if change else []
        return []

    def _patch_empty_email(self, repo_dir: Path, selected_files: list[str]) -> FileChange | None:
        candidates = [
            path
            for path in selected_files
            if path.endswith(".py") and ("valid" in path or "email" in path or "src/" in path)
        ]
        candidates.extend(
            path.relative_to(repo_dir).as_posix()
            for path in repo_dir.rglob("*.py")
            if "test" not in path.name.lower()
        )
        for rel_path in dict.fromkeys(candidates):
            target = repo_dir / rel_path
            if not target.exists():
                continue
            before = target.read_text(encoding="utf-8")
            if "def is_valid_email" not in before:
                continue
            after = self._replace_email_validator(before)
            if after != before:
                return FileChange(path=rel_path, before=before, after=after)
        return None

    @staticmethod
    def _replace_email_validator(source: str) -> str:
        start = source.find("def is_valid_email")
        if start == -1:
            return source
        lines = source.splitlines(keepends=True)
        def_line = next((index for index, line in enumerate(lines) if line.startswith("def is_valid_email")), -1)
        if def_line == -1:
            return source
        end = def_line + 1
        while end < len(lines) and (lines[end].startswith(" ") or lines[end].strip() == ""):
            end += 1
        replacement = [
            "def is_valid_email(email: str | None) -> bool:\n",
            "    \"\"\"Return True only for non-empty email-like strings.\"\"\"\n",
            "    if email is None:\n",
            "        return False\n",
            "    normalized = email.strip()\n",
            "    if not normalized:\n",
            "        return False\n",
            "    if \"@\" not in normalized:\n",
            "        return False\n",
            "    local, domain = normalized.rsplit(\"@\", 1)\n",
            "    return bool(local) and \".\" in domain and bool(domain.rsplit(\".\", 1)[-1])\n",
        ]
        return "".join([*lines[:def_line], *replacement, *lines[end:]])

    def _patch_docstring_only(self, repo_dir: Path, selected_files: list[str]) -> FileChange | None:
        for rel_path in selected_files:
            target = repo_dir / rel_path
            if not target.exists() or not rel_path.endswith(".py"):
                continue
            before = target.read_text(encoding="utf-8")
            if "Return True when a string looks like an email address." not in before:
                continue
            after = before.replace(
                "Return True when a string looks like an email address.",
                "Return True when a non-empty string looks like an email address.",
            )
            return FileChange(path=rel_path, before=before, after=after)
        return None
