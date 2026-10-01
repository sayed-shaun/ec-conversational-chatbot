"""SQLite checkpointer for conversation transcripts."""

import asyncio
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

from src.core.config import chatbot_settings as settings
from src.core.logger import get_logger

logger = get_logger(__name__)


class SqliteCheckpointer:
    """Stores and retrieves conversation transcripts in a SQLite file."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS checkpoints (
        session_id TEXT PRIMARY KEY,
        history    TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        """Open a fresh connection; sqlite3 connections are not thread-safe."""
        connection = sqlite3.connect(self.db_path, timeout=5.0)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def init(self) -> None:
        """Create the database and schema if they do not exist yet."""
        parent = os.path.dirname(os.path.abspath(self.db_path))
        os.makedirs(parent, exist_ok=True)
        with self._connect() as connection:
            connection.execute(self.SCHEMA)
            columns = [r[1] for r in connection.execute("PRAGMA table_info(checkpoints)")]
            if "smart_messages" not in columns:
                connection.execute(
                    "ALTER TABLE checkpoints ADD COLUMN smart_messages TEXT NOT NULL DEFAULT ''"
                )
        logger.info("checkpointer ready sqlite=%s", self.db_path)

    def _load(self, session_id: str) -> tuple[list[dict] | None, str]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT history, smart_messages FROM checkpoints WHERE session_id = ?",
                (session_id,),
            ).fetchone()

        if row is None:
            return None, ""

        try:
            history = json.loads(row[0])
        except json.JSONDecodeError:
            logger.warning(
                "corrupt checkpoint for session=%s; starting fresh", session_id
            )
            return None, ""

        if not isinstance(history, list) or not history:
            return None, ""
        return history, row[1] or ""

    def _save(self, session_id: str, history: list[dict], smart_messages: str) -> None:
        payload = json.dumps(history, ensure_ascii=False)
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO checkpoints (session_id, history, smart_messages, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    history = excluded.history,
                    smart_messages = excluded.smart_messages,
                    updated_at = excluded.updated_at
                """,
                (session_id, payload, smart_messages, now),
            )

    def _delete(self, session_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM checkpoints WHERE session_id = ?", (session_id,)
            )

    def _purge_expired(self, ttl_minutes: int) -> int:
        """Delete checkpoints untouched for longer than the TTL."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(minutes=ttl_minutes)
        ).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM checkpoints WHERE updated_at < ?", (cutoff,)
            )
            return cursor.rowcount

    def _count(self) -> int:
        with self._connect() as connection:
            return connection.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0]

    async def load(self, session_id: str) -> tuple[list[dict] | None, str]:
        """Return (transcript, smart-bot transcript); (None, "") for a new session."""
        return await asyncio.to_thread(self._load, session_id)

    async def save(
        self, session_id: str, history: list[dict], smart_messages: str = ""
    ) -> None:
        """Persist a transcript, replacing any earlier checkpoint."""
        await asyncio.to_thread(self._save, session_id, history, smart_messages)

    async def delete(self, session_id: str) -> None:
        """Drop a session's checkpoint."""
        await asyncio.to_thread(self._delete, session_id)

    async def count(self) -> int:
        """How many sessions are currently checkpointed."""
        return await asyncio.to_thread(self._count)

    async def purge_expired(self, ttl_minutes: int | None = None) -> int:
        """Clear finished conversations, returning how many were removed."""
        ttl = settings.SESSION_TTL_MINUTES if ttl_minutes is None else ttl_minutes
        if ttl <= 0:
            return 0

        removed = await asyncio.to_thread(self._purge_expired, ttl)
        if removed:
            logger.info("purged %d session(s) idle over %d min", removed, ttl)
        return removed


checkpointer = SqliteCheckpointer(settings.SESSION_DB_PATH)
