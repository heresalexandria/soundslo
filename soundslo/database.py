from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
MUTABLE_COLUMNS = {
    "name",
    "status",
    "progress",
    "stage",
    "file_path",
    "file_size",
    "error",
    "elapsed_seconds",
    "log",
    "video_path",
}

GENERATION_COLUMNS = (
    ("mode", "TEXT NOT NULL DEFAULT 'text'"),
    ("input_path", "TEXT"),
    ("sample_rate", "INTEGER NOT NULL DEFAULT 44100"),
    ("video_path", "TEXT"),
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS generations (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    negative_prompt TEXT NOT NULL DEFAULT '',
                    duration_seconds REAL NOT NULL,
                    seed INTEGER NOT NULL,
                    steps INTEGER NOT NULL,
                    cfg_scale REAL NOT NULL,
                    status TEXT NOT NULL,
                    progress REAL NOT NULL DEFAULT 0,
                    stage TEXT NOT NULL DEFAULT '',
                    file_path TEXT,
                    file_size INTEGER,
                    error TEXT,
                    elapsed_seconds REAL,
                    log TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT 'stable-audio-3-medium',
                    model_revision TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS generations_created_at_idx
                    ON generations(created_at DESC);
                CREATE INDEX IF NOT EXISTS generations_status_idx
                    ON generations(status);
                """
            )
            existing = {
                row[1] for row in connection.execute("PRAGMA table_info(generations)")
            }
            for column, ddl in GENERATION_COLUMNS:
                if column not in existing:
                    connection.execute(f"ALTER TABLE generations ADD COLUMN {column} {ddl}")

    def create(self, values: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        row = {
            **values,
            "status": "queued",
            "progress": 0.0,
            "stage": "Waiting for the generator",
            "created_at": now,
            "updated_at": now,
        }
        columns = ", ".join(row)
        placeholders = ", ".join("?" for _ in row)
        with self.connect() as connection:
            connection.execute(
                f"INSERT INTO generations ({columns}) VALUES ({placeholders})",  # noqa: S608
                tuple(row.values()),
            )
        created = self.get(values["id"])
        assert created is not None
        return created

    def get(self, generation_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM generations WHERE id = ?", (generation_id,)
            ).fetchone()
        return dict(row) if row else None

    def list(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM generations ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def queued_ids(self) -> list[str]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id FROM generations WHERE status = 'queued' ORDER BY created_at"
            ).fetchall()
        return [row["id"] for row in rows]

    def update(self, generation_id: str, **values: Any) -> dict[str, Any] | None:
        unknown = set(values) - MUTABLE_COLUMNS
        if unknown:
            raise ValueError(f"Unsupported generation fields: {', '.join(sorted(unknown))}")
        if not values:
            return self.get(generation_id)
        values["updated_at"] = utc_now()
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self.connect() as connection:
            connection.execute(
                f"UPDATE generations SET {assignments} WHERE id = ?",  # noqa: S608
                (*values.values(), generation_id),
            )
        return self.get(generation_id)

    def delete(self, generation_id: str) -> dict[str, Any] | None:
        row = self.get(generation_id)
        if row is None:
            return None
        input_path = row.get("input_path")
        with self.connect() as connection:
            connection.execute("DELETE FROM generations WHERE id = ?", (generation_id,))
            input_in_use = bool(
                input_path
                and connection.execute(
                    "SELECT 1 FROM generations WHERE input_path = ? LIMIT 1", (input_path,)
                ).fetchone()
            )
        video_path = row.get("video_path")
        if video_path:
            self._unlink_data_file(video_path)
        if input_path and not input_in_use:
            self._unlink_data_file(input_path)
        return row

    def _unlink_data_file(self, raw_path: str) -> None:
        """Remove a generation artifact only when it remains inside the data directory."""
        path = Path(raw_path).resolve()
        data_dir = self.path.resolve().parent
        if path.is_relative_to(data_dir):
            path.unlink(missing_ok=True)

    def fail_interrupted(self) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE generations
                SET status = 'failed', progress = 0, stage = 'Interrupted',
                    error = 'Soundslo stopped before this generation finished.', updated_at = ?
                WHERE status = 'running'
                """,
                (now,),
            )

    def cancel_many(self, generation_ids: Iterable[str], reason: str) -> None:
        ids = list(generation_ids)
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        with self.connect() as connection:
            connection.execute(
                f"""UPDATE generations
                    SET status = 'cancelled', stage = 'Cancelled', error = ?, updated_at = ?
                    WHERE id IN ({placeholders}) AND status IN ('queued', 'running')""",  # noqa: S608
                (reason, utc_now(), *ids),
            )
