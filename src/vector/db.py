"""Postgres/pgvector access layer.

One table, `faq_entries`, holds tag/question/answer rows plus their
embedding. A HNSW index on the embedding column (cosine ops) backs
approximate nearest-neighbour search for /top_similar.
"""

from functools import lru_cache

import psycopg
from psycopg_pool import ConnectionPool
from pgvector.psycopg import register_vector

from src.core.config import vector_settings as settings


def _bootstrap_extension() -> None:
    """Create the `vector` extension via a one-off, unregistered connection.

    The pool below registers the `vector` type on every connection it opens,
    which requires CREATE EXTENSION to have already run -- otherwise pool
    init deadlocks retrying "vector type not found".
    """
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")


@lru_cache(maxsize=1)
def _pool() -> ConnectionPool:
    _bootstrap_extension()
    pool = ConnectionPool(
        settings.database_url,
        min_size=1,
        max_size=settings.db_pool_max_size,
        open=True,
        configure=register_vector,
    )
    pool.wait()
    return pool


def ensure_schema() -> None:
    with _pool().connection() as conn:
        # A vector column's width is a type modifier, not a value, so it
        # can't be a bind parameter -- interpolated directly instead. Safe:
        # embedding_dim is a validated int from our own settings, never
        # request input.
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS faq_entries (
                id BIGSERIAL PRIMARY KEY,
                tag TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                embedding vector({int(settings.embedding_dim)}) NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (tag, question)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS faq_entries_embedding_idx
            ON faq_entries USING hnsw (embedding vector_cosine_ops)
            """
        )


def row_count() -> int:
    with _pool().connection() as conn:
        return conn.execute("SELECT count(*) FROM faq_entries").fetchone()[0]


def replace_all(rows: list[tuple[str, str, str, list[float]]]) -> int:
    with _pool().connection() as conn:
        with conn.transaction():
            conn.execute("TRUNCATE faq_entries")
            conn.cursor().executemany(
                """
                INSERT INTO faq_entries (tag, question, answer, embedding)
                VALUES (%s, %s, %s, %s)
                """,
                rows,
            )
    return len(rows)


def upsert(rows: list[tuple[str, str, str, list[float]]]) -> int:
    with _pool().connection() as conn:
        with conn.transaction():
            conn.cursor().executemany(
                """
                INSERT INTO faq_entries (tag, question, answer, embedding)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (tag, question)
                DO UPDATE SET answer = EXCLUDED.answer,
                              embedding = EXCLUDED.embedding
                """,
                rows,
            )
    return len(rows)


def top_similar(query_embedding: list[float], top_k: int) -> list[dict]:
    with _pool().connection() as conn:
        # The bind parameter has no target column to infer a type from (this
        # is an expression, not an INSERT), so without an explicit cast
        # psycopg sends it as a plain float array and Postgres can't match a
        # `<=>` operator overload for it.
        cur = conn.execute(
            """
            SELECT tag, question, 1 - (embedding <=> %s::vector) AS cosine_similarity
            FROM faq_entries
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (query_embedding, query_embedding, top_k),
        )
        return [
            {"tag": tag, "question": question, "cosine_similarity": float(score)}
            for tag, question, score in cur.fetchall()
        ]
