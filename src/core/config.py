"""
Central configuration for every EC FAQ service, loaded from environment
variables (and an optional local .env for standalone/dev runs). Modules
should import the settings object they need from here instead of calling
os.getenv directly, so every knob is declared, typed, and validated in
one place.

Field names are UPPERCASE to match the environment variables they're read
from 1:1, since pydantic-settings' case-insensitive matching means that
mapping already holds either way -- writing it out avoids having to mentally
lower-case an env var name to find its field, or vice versa.
"""

import os

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_BASE_CONFIG = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    case_sensitive=False,
    extra="ignore",
)

_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _default_tag_answer_path() -> str:
    """Locate tag_answer.json in a source checkout or inside the image.

    In the container the MCP service's files are copied to the WORKDIR, so the
    file sits beside the process; from a checkout it lives in src/mcp/.
    """
    candidates = [
        os.path.join(_SRC_DIR, "mcp", "tag_answer.json"),
        os.path.join(os.getcwd(), "tag_answer.json"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return candidates[0]


class ChatbotSettings(BaseSettings):
    """Settings for the FastAPI chatbot backend (src/chatbot).

    LLAMA_MODEL is sent but usually ignored by llama-server; the OpenAI
    client just requires a value. LLAMA_REASONING_EFFORT='none' suppresses
    most of the thinking pass on a reasoning model (the bulk of the delay
    before the first answer token); it's unreliable through the streaming
    path, so prefer llama-server's own --reasoning off instead.
    SESSION_TTL_MINUTES=0 (or less) keeps transcripts until reset
    explicitly.
    """

    model_config = _BASE_CONFIG

    LLAMA_BASE_URL: str = "http://172.31.60.228:8080/v1"
    LLAMA_MODEL: str = "local-model"
    LLAMA_REASONING_EFFORT: str = ""

    MCP_SERVER_URL: str = "http://ec-conversational-mcp:9000/mcp"

    CORS_ALLOW_ORIGINS: str = "*"

    MAX_HISTORY_TURNS: int = Field(default=12, ge=1)
    MAX_TOOL_HOPS: int = Field(default=3, ge=1)

    SESSION_DB_PATH: str = "/data/sessions.db"
    SESSION_TTL_MINUTES: int = 60
    SESSION_SWEEP_MINUTES: int = Field(default=10, ge=1)

    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    STATIC_DIR: str = "static"


class McpSettings(BaseSettings):
    """Settings for the FastMCP server (src/mcp).

    TOP_SIMILAR_API_URL defaults to the self-hosted pgvector service
    (src/vector); point it elsewhere to use a different backend.
    GITHUB_TOKEN is required while Synesis-IT-PLC/ec-faq-bot is private.
    TAG_ANSWER_REFRESH_SECONDS=0 disables polling and only fetches once at
    startup. MCP_TRANSPORT is 'http' (Streamable HTTP, for Docker/network
    use) or 'stdio' (local MCP clients).
    """

    model_config = _BASE_CONFIG

    TOP_SIMILAR_API_URL: str = "http://ec-conversational-vector:8001/top_similar"
    TOP_SIMILAR_TIMEOUT: float = 10.0

    TAG_ANSWER_URL: str = (
        "https://raw.githubusercontent.com/Synesis-IT-PLC/ec-faq-bot/"
        "development/full_dataset/tag_answer.json"
    )
    TAG_ANSWER_URL_TIMEOUT: float = 15.0
    GITHUB_TOKEN: str = ""
    TAG_ANSWER_PATH: str = Field(default_factory=_default_tag_answer_path)
    TAG_ANSWER_ALLOW_LOCAL_FALLBACK: bool = True
    TAG_ANSWER_REFRESH_SECONDS: float = Field(default=0.0, ge=0.0)
    CONFIDENCE_THRESHOLD: float = Field(default=0.55, ge=0.0, le=1.0)

    MCP_TRANSPORT: str = "http"
    MCP_HOST: str = "0.0.0.0"
    MCP_PORT: int = 9000
    MCP_PATH: str = "/mcp"


class VectorSettings(BaseSettings):
    """Settings for the pgvector-backed search service (src/vector).

    EMBEDDING_MODEL_NAME must stay in sync with EMBEDDING_DIM and with
    whatever model produced the rows already stored in faq_entries -- scores
    are meaningless across models. It isn't in fastembed's built-in
    registry; it's registered as a custom model in src/vector/embeddings.py,
    which also applies the E5-instruct query prefix built from
    RETRIEVAL_TASK.

    TAG_ANSWER_URL and QUESTION_TAG_CSV_URL feed the daily reindex
    (src/vector/reindex.py), which rebuilds faq_entries from them so an
    edit landed upstream reaches search without a manual /index upload.
    REINDEX_ENABLED only controls the daily schedule -- manual POST
    /reindex works regardless. REINDEX_HOUR_UTC is a fixed UTC hour rather
    than "every 24h from whenever the container booted", so a restart at
    any hour doesn't shift it to a busier time of day.
    """

    model_config = _BASE_CONFIG

    DATABASE_URL: str = "postgresql://ec_faq:ec_faq@pgvector-db:5432/ec_faq"
    DB_POOL_MAX_SIZE: int = Field(default=5, ge=1)

    EMBEDDING_MODEL_NAME: str = "intfloat/multilingual-e5-large-instruct"
    EMBEDDING_DIM: int = 1024
    EMBEDDING_CACHE_DIR: str = "/root/.cache/fastembed_cache"
    RETRIEVAL_TASK: str = (
        "You are an expert in matching Bangladeshi National Identity Card (NID) "
        "and voter registration queries. Your task is to identify the most "
        "semantically relevant question from the provided document, considering "
        "context, intent, and specific details. Use semantic similarity and "
        "contextual understanding to retrieve the closest match, prioritizing "
        "exact phrase matches and context-aware matching."
    )

    VECTOR_API_HOST: str = "0.0.0.0"
    VECTOR_API_PORT: int = 8001

    TAG_ANSWER_URL: str = (
        "https://raw.githubusercontent.com/Synesis-IT-PLC/ec-faq-bot/"
        "development/full_dataset/tag_answer.json"
    )
    QUESTION_TAG_CSV_URL: str = (
        "https://raw.githubusercontent.com/Synesis-IT-PLC/ec-faq-bot/"
        "feat/multilingual-en-banglish-questions/full_dataset/question_tag.csv"
    )
    GITHUB_TOKEN: str = ""
    REINDEX_FETCH_TIMEOUT: float = 30.0
    REINDEX_ENABLED: bool = True
    REINDEX_HOUR_UTC: int = Field(default=3, ge=0, le=23)


chatbot_settings = ChatbotSettings()
mcp_settings = McpSettings()
vector_settings = VectorSettings()
