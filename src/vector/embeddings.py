"""Local embedding model wrapper (fastembed: ONNX runtime, no torch, no
outbound API calls once the model is cached), so nearest-neighbour search no
longer depends on a third-party embedding service.

sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 is the default:
384 dims, CPU-friendly, and trained across ~50 languages including Bengali.
query_embed/passage_embed are used (rather than plain embed) so that if the
model is swapped for an asymmetric one (e.g. an E5 variant, which needs a
"query: " / "passage: " prefix to perform well) no caller code has to change
— fastembed applies the right prefix per model, or none for a symmetric one.
"""

from functools import lru_cache

from src.core.config import vector_settings as settings
from src.core.logger import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def _model():
    from fastembed import TextEmbedding

    logger.info("loading embedding model %s", settings.embedding_model)
    return TextEmbedding(
        model_name=settings.embedding_model, cache_dir=settings.embedding_cache_dir
    )


def embed_query(text: str) -> list[float]:
    (vector,) = _model().query_embed([text])
    return vector.tolist()


def embed_passages(texts: list[str]) -> list[list[float]]:
    return [vector.tolist() for vector in _model().passage_embed(texts)]
