from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class AssessmentHistoryStore:
    """Durable operational history for API assessment jobs.

    This store is intentionally separate from Sibyl. Sibyl remains the agent's
    learned operational memory; this database preserves application/job records.
    """

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS assessment_jobs (
                    job_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    memory_enabled INTEGER NOT NULL,
                    provider_mode TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    events_json TEXT NOT NULL,
                    result_json TEXT,
                    error TEXT,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS assessment_jobs_updated_idx "
                "ON assessment_jobs(updated_at DESC)"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def upsert(self, job: dict[str, Any]) -> None:
        payload = json.loads(json.dumps(job))
        created_at = str(payload.get("createdAt") or payload.get("updatedAt") or "")
        updated_at = str(payload.get("updatedAt") or created_at)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO assessment_jobs (
                    job_id, created_at, updated_at, status, memory_enabled,
                    provider_mode, request_json, events_json, result_json,
                    error, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    status = excluded.status,
                    memory_enabled = excluded.memory_enabled,
                    provider_mode = excluded.provider_mode,
                    request_json = excluded.request_json,
                    events_json = excluded.events_json,
                    result_json = excluded.result_json,
                    error = excluded.error,
                    payload_json = excluded.payload_json
                """,
                (
                    payload["id"],
                    created_at,
                    updated_at,
                    payload["status"],
                    1 if payload.get("memoryEnabled") else 0,
                    payload.get("providerMode", "local"),
                    json.dumps(payload.get("request", {})),
                    json.dumps(payload.get("events", [])),
                    json.dumps(payload.get("result")) if payload.get("result") is not None else None,
                    payload.get("error"),
                    json.dumps(payload),
                ),
            )

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM assessment_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        value = json.loads(row["payload_json"])
        return value if isinstance(value, dict) else None

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 200))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT job_id, created_at, updated_at, status, memory_enabled,
                       provider_mode, request_json, error
                FROM assessment_jobs
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [
            {
                "id": row["job_id"],
                "createdAt": row["created_at"],
                "updatedAt": row["updated_at"],
                "status": row["status"],
                "memoryEnabled": bool(row["memory_enabled"]),
                "providerMode": row["provider_mode"],
                "request": json.loads(row["request_json"]),
                "error": row["error"],
            }
            for row in rows
        ]
