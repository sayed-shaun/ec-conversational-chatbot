"""Postgres/pgvector access layer (SQLAlchemy).

One table, `faq_entries` (src/vector/model.py), holds tag/question/answer
rows plus their embedding. A HNSW index on the embedding column (cosine
ops) backs approximate nearest-neighbour search for /top_similar.
"""

from functools import lru_cache

import psycopg
from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.core.config import vector_settings as settings
from src.vector.model import Base, VectorDatabase


def _sqlalchemy_url() -> str:
    """Rewrite DATABASE_URL's plain 'postgresql://' scheme to
    'postgresql+psycopg://', the driver SQLAlchemy needs named explicitly
    to pick psycopg3 over the (not installed) psycopg2 default."""
    url = settings.DATABASE_URL
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def _bootstrap_extension() -> None:
    """Create the `vector` extension via a one-off connection, before the
    engine (and pgvector's type registration) touches the database."""
    with psycopg.connect(settings.DATABASE_URL, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")


@lru_cache(maxsize=1)
def _engine() -> Engine:
    _bootstrap_extension()
    return create_engine(_sqlalchemy_url(), pool_size=settings.DB_POOL_MAX_SIZE)


def ensure_schema() -> None:
    engine = _engine()
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS faq_entries_embedding_idx "
                "ON faq_entries USING hnsw (embedding vector_cosine_ops)"
            )
        )


def row_count() -> int:
    with Session(_engine()) as session:
        return session.scalar(select(func.count()).select_from(VectorDatabase))


def replace_all(rows: list[tuple[str, str, str, list[float]]]) -> int:
    with Session(_engine()) as session:
        session.execute(text("TRUNCATE faq_entries"))
        session.add_all(
            VectorDatabase(tag=tag, question=question, answer=answer, embedding=embedding)
            for tag, question, answer, embedding in rows
        )
        session.commit()
    return len(rows)


def upsert(rows: list[tuple[str, str, str, list[float]]]) -> int:
    if not rows:
        return 0
    stmt = pg_insert(VectorDatabase).values(
        [
            {"tag": tag, "question": question, "answer": answer, "embedding": embedding}
            for tag, question, answer, embedding in rows
        ]
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[VectorDatabase.tag, VectorDatabase.question],
        set_={"answer": stmt.excluded.answer, "embedding": stmt.excluded.embedding},
    )
    with Session(_engine()) as session:
        session.execute(stmt)
        session.commit()
    return len(rows)


def top_similar(query_embedding: list[float], top_k: int) -> list[dict]:
    distance = VectorDatabase.embedding.cosine_distance(query_embedding)
    similarity = (1 - distance).label("cosine_similarity")
    columns = (VectorDatabase.tag, VectorDatabase.question, similarity)
    stmt = select(*columns).order_by(distance).limit(top_k)
    with Session(_engine()) as session:
        rows = session.execute(stmt).all()
    return [
        {"tag": tag, "question": question, "cosine_similarity": float(score)}
        for tag, question, score in rows
    ]
