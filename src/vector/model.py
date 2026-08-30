"""SQLAlchemy ORM model for the vector index.

One table, faq_entries, holding tag/question/answer rows plus their
embedding. See db.py for schema setup (extension, HNSW index) and queries.
"""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, DateTime, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from src.core.config import vector_settings as settings


class Base(DeclarativeBase):
    pass


class VectorDatabase(Base):
    __tablename__ = "faq_entries"
    __table_args__ = (UniqueConstraint("tag", "question"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tag: Mapped[str] = mapped_column(Text, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    # Dimension is read from settings rather than hardcoded so it always
    # matches EMBEDDING_MODEL_NAME's actual output width.
    embedding: Mapped[list[float]] = mapped_column(
        Vector(settings.EMBEDDING_DIM), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
