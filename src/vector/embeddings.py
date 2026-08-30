"""Local embedding model wrapper (fastembed: ONNX runtime, no torch, no
outbound API calls once the model is cached), so nearest-neighbour search no
longer depends on a third-party embedding service.

Default model: intfloat/multilingual-e5-large-instruct (1024 dims). It isn't
in fastembed's built-in registry, but its HF repo already ships ONNX weights
at onnx/model.onnx, so it's registered as a custom model instead of
converting anything ourselves.

E5-instruct models are asymmetric and don't get fastembed's automatic
query/passage prefixing (that only applies to models in its built-in
registry): per the model card, a query needs an "Instruct: {task}\\nQuery:
{text}" prefix, while passages get no prefix at all. That's applied here
explicitly rather than relying on fastembed to guess it for a custom model.
"""

from functools import lru_cache

from fastembed import TextEmbedding
from fastembed.common.model_description import ModelSource, PoolingType

from src.core.config import vector_settings as settings
from src.core.logger import get_logger

logger = get_logger(__name__)


def _register_custom_model_if_needed() -> None:
    already_registered = any(
        m["model"] == settings.EMBEDDING_MODEL_NAME
        for m in TextEmbedding.list_supported_models()
    )
    if already_registered:
        return
    TextEmbedding.add_custom_model(
        model=settings.EMBEDDING_MODEL_NAME,
        pooling=PoolingType.MEAN,
        normalization=True,
        sources=ModelSource(hf=settings.EMBEDDING_MODEL_NAME),
        dim=settings.EMBEDDING_DIM,
        model_file="onnx/model.onnx",
        additional_files=["onnx/model.onnx_data"],
        description="E5 multilingual instruct embedding model.",
        license="mit",
        size_in_gb=2.24,
    )


@lru_cache(maxsize=1)
def _model():
    _register_custom_model_if_needed()
    logger.info("loading embedding model %s", settings.EMBEDDING_MODEL_NAME)
    return TextEmbedding(
        model_name=settings.EMBEDDING_MODEL_NAME, cache_dir=settings.EMBEDDING_CACHE_DIR
    )


def _query_text(text: str) -> str:
    return f"Instruct: {settings.RETRIEVAL_TASK}\nQuery: {text}"


def embed_query(text: str) -> list[float]:
    (vector,) = _model().embed([_query_text(text)])
    return vector.tolist()


def embed_passages(texts: list[str]) -> list[list[float]]:
    return [vector.tolist() for vector in _model().embed(texts)]
