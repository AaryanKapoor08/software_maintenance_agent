from __future__ import annotations

from pathlib import Path

from patchpilot.agent import load_task
from patchpilot.jepa.predictor import CodeJepaExample
from patchpilot.retrieval import file_text


def examples_from_task_files(task_files: list[Path]) -> list[CodeJepaExample]:
    examples: list[CodeJepaExample] = []
    for task_file in task_files:
        task = load_task(task_file)
        repo_dir = (task_file.parent / ".." / task.repo_url).resolve()
        if not repo_dir.exists():
            repo_dir = Path(task.repo_url).resolve()
        for rel_path in task.expected_relevant_files or task.expected_changed_files:
            target = repo_dir / rel_path
            if target.exists():
                examples.append(
                    CodeJepaExample(
                        context=f"{task.title}\n{task.body}",
                        target_path=rel_path,
                        target_text=file_text(target),
                    )
                )
    return examples
