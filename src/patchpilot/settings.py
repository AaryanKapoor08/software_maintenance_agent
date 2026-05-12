from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///runs/patchpilot.sqlite"
    llm_provider: str = "gemini"
    max_attempts: int = 3
    max_changed_files: int = 6
    max_diff_lines: int = 300
    default_sandbox: str = "local"
    runs_dir: Path = Path("runs")

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            database_url=os.getenv("AMA_DATABASE_URL", cls.database_url),
            llm_provider=os.getenv("AMA_LLM_PROVIDER", cls.llm_provider),
            max_attempts=int(os.getenv("AMA_MAX_ATTEMPTS", str(cls.max_attempts))),
            max_changed_files=int(os.getenv("AMA_MAX_CHANGED_FILES", str(cls.max_changed_files))),
            max_diff_lines=int(os.getenv("AMA_MAX_DIFF_LINES", str(cls.max_diff_lines))),
            default_sandbox=os.getenv("AMA_DEFAULT_SANDBOX", cls.default_sandbox),
            runs_dir=Path(os.getenv("AMA_RUNS_DIR", "runs")),
        )
