"""Request/response models for the vector search service."""

from typing import Literal

from pydantic import BaseModel, Field


class IndexEntry(BaseModel):
    tag: str = Field(min_length=1)
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)


class IndexRequest(BaseModel):
    entries: list[IndexEntry] = Field(min_length=1)
    mode: Literal["append", "replace"] = Field(
        default="append",
        description=(
            "'append' upserts each entry (same tag+question overwrites its "
            "row); 'replace' truncates the table before inserting, so the "
            "upload becomes the entire knowledge base."
        ),
    )


class IndexResponse(BaseModel):
    indexed: int
    mode: str
    total_rows: int


class TopSimilarRequest(BaseModel):
    question: str = Field(min_length=1)
    top_k: int = Field(default=10, ge=1, le=100)


class TopSimilarMatch(BaseModel):
    tag: str
    question: str
    cosine_similarity: float


class TopSimilarResponse(BaseModel):
    input_question: str
    top_similar: list[TopSimilarMatch]


class HealthResponse(BaseModel):
    status: str
    row_count: int
    embedding_model: str
