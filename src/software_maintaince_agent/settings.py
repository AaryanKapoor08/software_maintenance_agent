from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ENV_FILES = (".env.local", ".env")


def load_env_files(base_dir: Path | None = None) -> None:
    """Load KEY=VALUE lines from .env.local/.env into os.environ.

    Existing environment variables always win; files never override them.
    """
    root = base_dir or Path.cwd()
    for name in ENV_FILES:
        path = root / name
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///runs/software_maintaince_agent.sqlite"
    llm_provider: str = "gemini"
    max_attempts: int = 3
    max_changed_files: int = 6
    max_diff_lines: int = 300
    default_sandbox: str = "local"
    runs_dir: Path = Path("runs")

    @classmethod
    def from_env(cls) -> Settings:
        load_env_files()
        return cls(
            database_url=os.getenv("AMA_DATABASE_URL", cls.database_url),
            llm_provider=os.getenv("AMA_LLM_PROVIDER", cls.llm_provider),
            max_attempts=int(os.getenv("AMA_MAX_ATTEMPTS", str(cls.max_attempts))),
            max_changed_files=int(os.getenv("AMA_MAX_CHANGED_FILES", str(cls.max_changed_files))),
            max_diff_lines=int(os.getenv("AMA_MAX_DIFF_LINES", str(cls.max_diff_lines))),
            default_sandbox=os.getenv("AMA_DEFAULT_SANDBOX", cls.default_sandbox),
            runs_dir=Path(os.getenv("AMA_RUNS_DIR", "runs")),
        )
