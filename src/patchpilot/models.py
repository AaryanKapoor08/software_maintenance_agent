from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class RunState(StrEnum):
    CREATED = "CREATED"
    INTAKE_VALIDATED = "INTAKE_VALIDATED"
    SANDBOX_READY = "SANDBOX_READY"
    REPO_CLONED = "REPO_CLONED"
    PROJECT_INSPECTED = "PROJECT_INSPECTED"
    BASELINE_TESTED = "BASELINE_TESTED"
    FILES_SELECTED = "FILES_SELECTED"
    PATCH_PLANNED = "PATCH_PLANNED"
    PATCH_APPLIED = "PATCH_APPLIED"
    TESTS_RUNNING = "TESTS_RUNNING"
    TESTS_PASSED = "TESTS_PASSED"
    TESTS_FAILED = "TESTS_FAILED"
    REPAIR_ATTEMPTED = "REPAIR_ATTEMPTED"
    FINALIZED_SUCCESS = "FINALIZED_SUCCESS"
    FINALIZED_FAILED = "FINALIZED_FAILED"
    ESCALATED = "ESCALATED"


class CommandStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    TIMED_OUT = "timed_out"


class MaintenanceTask(BaseModel):
    id: str
    source: Literal["local_fixture", "github_issue", "local_log"] = "local_fixture"
    repo_url: str
    issue_number: int | None = None
    title: str
    body: str = ""
    labels: list[str] = Field(default_factory=list)
    base_branch: str = "main"
    allowed_paths: list[str] = Field(default_factory=lambda: ["src/**", "tests/**"])
    blocked_paths: list[str] = Field(
        default_factory=lambda: [".github/**", ".env*", "*lock*", "secrets/**"]
    )
    max_attempts: int = 3
    focused_test_command: str | None = None
    expected_relevant_files: list[str] = Field(default_factory=list)
    expected_changed_files: list[str] = Field(default_factory=list)

    @field_validator("max_attempts")
    @classmethod
    def validate_attempts(cls, value: int) -> int:
        if value < 1 or value > 5:
            raise ValueError("max_attempts must be between 1 and 5")
        return value


class RepoSummary(BaseModel):
    language: str = "unknown"
    frameworks: list[str] = Field(default_factory=list)
    package_manager: str = "unknown"
    test_commands: list[str] = Field(default_factory=list)
    focused_test_command: str | None = None
    entry_points: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    files_indexed: int = 0


class CommandResult(BaseModel):
    command: str
    exit_code: int
    status: CommandStatus
    duration_ms: int
    stdout: str = ""
    stderr: str = ""
    failure_summary: str | None = None


class RetrievalCandidate(BaseModel):
    path: str
    score: float
    reasons: list[str] = Field(default_factory=list)


class AgentPlan(BaseModel):
    issue_summary: str
    hypothesis: str
    files_to_read: list[str]
    files_to_edit: list[str]
    test_strategy: list[str]
    risk_level: Literal["low", "medium", "high", "blocked"] = "medium"


class FileChange(BaseModel):
    path: str
    before: str
    after: str


class PatchAttempt(BaseModel):
    attempt: int
    files_changed: list[str] = Field(default_factory=list)
    diff_summary: str = ""
    commands_run: list[CommandResult] = Field(default_factory=list)
    result: Literal["passed", "failed", "blocked"] = "failed"
    failure_reason: str | None = None


class RiskReport(BaseModel):
    level: Literal["low", "medium", "high", "blocked"]
    score: int
    reasons: list[str]


class FinalReport(BaseModel):
    status: Literal["success", "failed", "blocked"]
    risk_level: Literal["low", "medium", "high", "blocked"]
    issue_understanding: str
    what_changed: list[str]
    changed_files: list[str]
    tests_run: list[str]
    how_to_test: list[str]
    rollback_plan: list[str]
    known_limitations: list[str]
    trace: list[str]
    report_path: str | None = None
    patch_path: str | None = None


class TraceEvent(BaseModel):
    run_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    state: RunState | None = None
    kind: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)


class BenchmarkTask(BaseModel):
    task_file: Path


class BenchmarkSuite(BaseModel):
    name: str
    tasks: list[BenchmarkTask]


class RetrievalMetrics(BaseModel):
    method: str
    top_1_recall: float
    top_3_recall: float
    top_5_recall: float
    average_context_files: float
    latency_ms: int


class BenchmarkReport(BaseModel):
    suite: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    task_count: int
    metrics: list[RetrievalMetrics]
    jepa_status: Literal["active", "experimental"]
    report_path: str | None = None
