from __future__ import annotations

from pathlib import Path

from patchpilot.agent import load_task
from patchpilot.repo_inspect import inspect_repo
from patchpilot.retrieval import hashed_vector, hybrid_retrieve, lexical_retrieve, recall_at_k

FIXTURE = Path("examples/fixtures/python_email_validator")
TASK_FILE = Path("examples/tasks/python_email_empty.json")


def test_repo_inspection_detects_python_pytest() -> None:
    task = load_task(TASK_FILE)
    summary = inspect_repo(FIXTURE, task)
    assert summary.language == "python"
    assert "pytest" in summary.frameworks
    assert "python -m pytest" in summary.test_commands


def test_lexical_retrieval_finds_relevant_file() -> None:
    task = load_task(TASK_FILE)
    candidates = lexical_retrieve(FIXTURE, task, top_k=5)
    assert recall_at_k(candidates, task.expected_relevant_files, 5) >= 0.5
    assert any(candidate.path == "src/email_validator_app/validation.py" for candidate in candidates)


def test_hybrid_retrieval_fuses_relevant_file() -> None:
    task = load_task(TASK_FILE)
    candidates = hybrid_retrieve(FIXTURE, task, top_k=5)
    assert recall_at_k(candidates, task.expected_relevant_files, 5) >= 0.5
    assert candidates[0].reasons


def test_hash_embedding_is_stable() -> None:
    assert hashed_vector("email validator") == hashed_vector("email validator")
