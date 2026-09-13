"""
SQLite checkpointer for conversation transcripts.

Each session's full message list is stored as one JSON blob, which matches how
a turn actually uses it: read the whole history, append to it, write it back
trimmed. That avoids reassembling a row-per-message table on every request.

A hybrid session has a second transcript beside it: the opaque `messages`
string the upstream smart API hands back each turn and expects to receive on
the next one (see src/chatbot/smart.py). It is stored in its own column rather
than smuggled into the history list, because anything in that list is sent to
llama-server as a chat message and this is not one.

sqlite3 is blocking, so every call runs in a worker thread. Blocking the event
loop would stall the token streaming this service exists to serve.

Scope: this gives durability across restarts, not horizontal scale. One
container against one file is well within SQLite's range; several replicas
sharing that file over a volume is fragile, and across hosts it does not work
at all. That needs Redis or Postgres.
"""

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

    #: Added after the table shipped, so an existing database file has to be
    #: migrated in place rather than recreated -- dropping it would end every
    #: conversation in flight at deploy time.
    SMART_COLUMN = "smart_messages"

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        """Open a connection.

        A fresh one per operation: sqlite3 connections are not safe to share
        across threads, and asyncio.to_thread gives no guarantee about which
        thread runs a call. For a local file this costs microseconds.
        """
        connection = sqlite3.connect(self.db_path, timeout=5.0)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def init(self) -> None:
        """Create the database and schema if they do not exist yet."""
        parent = os.path.dirname(os.path.abspath(self.db_path))
        os.makedirs(parent, exist_ok=True)
        with self._connect() as connection:
            connection.execute(self.SCHEMA)
            self._add_smart_column(connection)
        logger.info("checkpointer ready sqlite=%s", self.db_path)

    def _add_smart_column(self, connection: sqlite3.Connection) -> None:
        """Add the smart-transcript column to a pre-hybrid database.

        Checked by inspecting the table rather than catching the error from a
        blind ALTER, so a genuine failure is not mistaken for "already there".
        Rows written before the migration read back as NULL, which load()
        turns into "", i.e. a conversation the smart API has not seen yet --
        the correct starting state for it.
        """
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(checkpoints)")
        }
        if self.SMART_COLUMN in columns:
            return
        connection.execute(
            f"ALTER TABLE checkpoints ADD COLUMN {self.SMART_COLUMN} TEXT"
        )
        logger.info("migrated checkpoints: added %s column", self.SMART_COLUMN)

    def _load(self, session_id: str) -> tuple[list[dict] | None, str]:
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT history, {self.SMART_COLUMN} FROM checkpoints "
                "WHERE session_id = ?",
                (session_id,),
            ).fetchone()

        if row is None:
            return None, ""

        smart = row[1] or ""

        try:
            history = json.loads(row[0])
        except json.JSONDecodeError:
            logger.warning(
                "corrupt checkpoint for session=%s; starting fresh", session_id
            )
            return None, smart

        if not isinstance(history, list) or not history:
            return None, smart
        return history, smart

    def _save(self, session_id: str, history: list[dict], smart: str) -> None:
        payload = json.dumps(history, ensure_ascii=False)
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute(
                f"""
                INSERT INTO checkpoints
                    (session_id, history, updated_at, {self.SMART_COLUMN})
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    history = excluded.history,
                    updated_at = excluded.updated_at,
                    {self.SMART_COLUMN} = excluded.{self.SMART_COLUMN}
                """,
                (session_id, payload, now, smart),
            )

    def _delete(self, session_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM checkpoints WHERE session_id = ?", (session_id,)
            )

    def _purge_expired(self, ttl_minutes: int) -> int:
        """Delete checkpoints untouched for longer than the TTL.

        updated_at is always written by _save as a UTC ISO-8601 string, so
        every row shares one format and offset; a string comparison against a
        cutoff built the same way orders correctly.
        """
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
        """Return (transcript, smart transcript) for a session.

        The transcript is None if this session is new; the smart transcript is
        "" if it is new, pre-hybrid, or has only ever been answered locally.
        """
        return await asyncio.to_thread(self._load, session_id)

    async def save(
        self, session_id: str, history: list[dict], smart: str = ""
    ) -> None:
        """Persist both transcripts, replacing any earlier checkpoint."""
        await asyncio.to_thread(self._save, session_id, history, smart)

    async def delete(self, session_id: str) -> None:
        """Drop a session's checkpoint."""
        await asyncio.to_thread(self._delete, session_id)

    async def count(self) -> int:
        """How many sessions are currently checkpointed."""
        return await asyncio.to_thread(self._count)

    async def purge_expired(self, ttl_minutes: int | None = None) -> int:
        """Clear finished conversations, returning how many were removed.

        A chat has no observable end over HTTP, so "finished" means idle: no
        turn for ttl_minutes. A TTL of 0 or less disables expiry and keeps
        transcripts until they are reset explicitly.
        """
        ttl = settings.SESSION_TTL_MINUTES if ttl_minutes is None else ttl_minutes
        if ttl <= 0:
            return 0

        removed = await asyncio.to_thread(self._purge_expired, ttl)
        if removed:
            logger.info("purged %d session(s) idle over %d min", removed, ttl)
        return removed


checkpointer = SqliteCheckpointer(settings.SESSION_DB_PATH)
