"""
EC FAQ Vector Search Service
-----------------------------
Self-hosted replacement for the third-party `top_similar` embedding-search
API: a small FastAPI service backed by Postgres + pgvector, with embeddings
computed locally (src/vector/embeddings.py — no outbound calls per request).

Two endpoints:

  POST /top_similar   Same request/response contract the MCP server
                       (src/mcp/server.py) already speaks: given a question
                       and top_k, return the nearest {tag, question,
                       cosine_similarity} rows. Point TOP_SIMILAR_API_URL at
                       this service and nothing else needs to change.

  POST /index          Upload the knowledge base (or an incremental batch)
                       as JSON: a list of {tag, question, answer} entries.
                       Each is embedded and stored/upserted in Postgres.
                       Optionally protected by VECTOR_INDEX_API_KEY.

  POST /reindex        Re-fetch tag_answer.json + question_tag.csv from
                       GitHub and replace the whole index. Runs
                       automatically every day at REINDEX_HOUR_UTC
                       (src/vector/reindex.py); this triggers it on demand.
                       Same X-API-Key gate as /index.

All configuration lives in src/core/config.py (VectorSettings).
"""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, status

from src.core.config import vector_settings as settings
from src.core.logger import get_logger
from src.vector import db, reindex
from src.vector.embeddings import embed_passages, embed_query
from src.vector.schemas import (
    HealthResponse,
    IndexRequest,
    IndexResponse,
    ReindexResponse,
    TopSimilarRequest,
    TopSimilarResponse,
)

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.ensure_schema()
    reindex.start_scheduler()
    logger.info(
        "vector service ready model=%s rows=%d",
        settings.EMBEDDING_MODEL_NAME,
        db.row_count(),
    )
    yield


app = FastAPI(title="EC FAQ Vector Search", lifespan=lifespan)


def require_index_api_key(
    x_api_key: str = Header(default=""),
) -> None:
    if settings.INDEX_API_KEY and x_api_key != settings.INDEX_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing X-API-Key",
        )


@app.post("/top_similar", response_model=TopSimilarResponse)
def top_similar(payload: TopSimilarRequest) -> TopSimilarResponse:
    query_vector = embed_query(payload.question)
    matches = db.top_similar(query_vector, payload.top_k)
    return TopSimilarResponse(input_question=payload.question, top_similar=matches)


@app.post(
    "/index",
    response_model=IndexResponse,
    dependencies=[Depends(require_index_api_key)],
)
def index(payload: IndexRequest) -> IndexResponse:
    vectors = embed_passages([entry.question for entry in payload.entries])
    rows = [
        (entry.tag, entry.question, entry.answer, vector)
        for entry, vector in zip(payload.entries, vectors)
    ]
    written = db.replace_all(rows) if payload.mode == "replace" else db.upsert(rows)
    return IndexResponse(indexed=written, mode=payload.mode, total_rows=db.row_count())


@app.post(
    "/reindex",
    response_model=ReindexResponse,
    dependencies=[Depends(require_index_api_key)],
)
def trigger_reindex() -> ReindexResponse:
    started = reindex.trigger_background()
    return ReindexResponse(
        status="started" if started else "already_running", row_count=db.row_count()
    )


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        row_count=db.row_count(),
        embedding_model=settings.EMBEDDING_MODEL_NAME,
    )
