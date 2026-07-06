from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from software_maintaince_agent.models import RunState, TraceEvent
from software_maintaince_agent.redaction import redact, redact_mapping


class TraceStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # sqlite3's own context manager commits/rolls back but never closes;
        # the leaked handle keeps trace.sqlite locked on Windows.
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    run_dir TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    state TEXT,
                    kind TEXT NOT NULL,
                    message TEXT NOT NULL,
                    data_json TEXT NOT NULL
                )
                """
            )

    def init_run(self, run_id: str, task_id: str, run_dir: Path) -> None:
        event = TraceEvent(run_id=run_id, state=RunState.CREATED, kind="state", message="Run created")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO runs
                (run_id, task_id, status, run_dir, started_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    task_id,
                    RunState.CREATED.value,
                    str(run_dir),
                    event.timestamp.isoformat(),
                    event.timestamp.isoformat(),
                ),
            )
        self.add_event(event)

    def update_status(self, run_id: str, status: RunState) -> None:
        event = TraceEvent(
            run_id=run_id,
            state=status,
            kind="state",
            message=f"State transitioned to {status.value}",
        )
        with self._connect() as conn:
            conn.execute(
                "UPDATE runs SET status = ?, updated_at = ? WHERE run_id = ?",
                (status.value, event.timestamp.isoformat(), run_id),
            )
        self.add_event(event)

    def add_event(self, event: TraceEvent) -> None:
        data = redact_mapping(event.data)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO events (run_id, timestamp, state, kind, message, data_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.run_id,
                    event.timestamp.isoformat(),
                    event.state.value if event.state else None,
                    event.kind,
                    redact(event.message),
                    json.dumps(data, sort_keys=True),
                ),
            )

    def event(
        self,
        run_id: str,
        kind: str,
        message: str,
        data: dict[str, Any] | None = None,
        state: RunState | None = None,
    ) -> None:
        self.add_event(
            TraceEvent(
                run_id=run_id,
                state=state,
                kind=kind,
                message=message,
                data=data or {},
            )
        )

    def list_events(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT timestamp, state, kind, message, data_json
                FROM events
                WHERE run_id = ?
                ORDER BY id ASC
                """,
                (run_id,),
            ).fetchall()
        return [
            {
                "timestamp": row[0],
                "state": row[1],
                "kind": row[2],
                "message": row[3],
                "data": json.loads(row[4]),
            }
            for row in rows
        ]

    def list_runs(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT run_id, task_id, status, run_dir, started_at, updated_at FROM runs"
                " ORDER BY started_at DESC"
            ).fetchall()
        return [
            {
                "run_id": row[0],
                "task_id": row[1],
                "status": row[2],
                "run_dir": row[3],
                "started_at": row[4],
                "updated_at": row[5],
            }
            for row in rows
        ]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT run_id, task_id, status, run_dir, started_at, updated_at FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "run_id": row[0],
            "task_id": row[1],
            "status": row[2],
            "run_dir": row[3],
            "started_at": row[4],
            "updated_at": row[5],
        }
