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
    """Settings for the FastAPI chatbot backend (src/chatbot)."""

    model_config = _BASE_CONFIG

    LLAMA_BASE_URL: str = "http://172.31.60.228:8080/v1"
    # llama-server usually ignores this field, but the OpenAI client requires one.
    LLAMA_MODEL: str = "local-model"
    # 'none' suppresses most of the thinking pass -- the bulk of the delay
    # between a tool result and the first answer token on a reasoning model.
    # Empty leaves the model's default. Unreliable through the streaming path;
    # prefer llama-server's own --reasoning off.
    LLAMA_REASONING_EFFORT: str = ""

    MCP_SERVER_URL: str = "http://ec-conversational-mcp:9000/mcp"

    # '*' is fine here since no cookies/auth headers are used cross-origin.
    CORS_ALLOW_ORIGINS: str = "*"

    MAX_HISTORY_TURNS: int = Field(default=12, ge=1)
    MAX_TOOL_HOPS: int = Field(default=3, ge=1)

    SESSION_DB_PATH: str = "/data/sessions.db"
    # 0 or less keeps transcripts until reset explicitly.
    SESSION_TTL_MINUTES: int = 60
    SESSION_SWEEP_MINUTES: int = Field(default=10, ge=1)

    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    STATIC_DIR: str = "static"


class McpSettings(BaseSettings):
    """Settings for the FastMCP server (src/mcp)."""

    model_config = _BASE_CONFIG

    # Defaults to the self-hosted pgvector service (src/vector); point
    # elsewhere to use a different top_similar backend.
    TOP_SIMILAR_API_URL: str = "http://ec-conversational-vector:8001/top_similar"
    TOP_SIMILAR_TIMEOUT: float = 10.0

    TAG_ANSWER_URL: str = (
        "https://raw.githubusercontent.com/Synesis-IT-PLC/ec-faq-bot/"
        "development/full_dataset/tag_answer.json"
    )
    TAG_ANSWER_URL_TIMEOUT: float = 15.0
    # Required while Synesis-IT-PLC/ec-faq-bot is private.
    GITHUB_TOKEN: str = ""
    TAG_ANSWER_PATH: str = Field(default_factory=_default_tag_answer_path)
    TAG_ANSWER_ALLOW_LOCAL_FALLBACK: bool = True
    # 0 disables polling and only fetches once at startup.
    TAG_ANSWER_REFRESH_SECONDS: float = Field(default=0.0, ge=0.0)
    CONFIDENCE_THRESHOLD: float = Field(default=0.55, ge=0.0, le=1.0)

    # 'http' (Streamable HTTP, for Docker/network use) or 'stdio' (local MCP clients).
    MCP_TRANSPORT: str = "http"
    MCP_HOST: str = "0.0.0.0"
    MCP_PORT: int = 9000
    MCP_PATH: str = "/mcp"


class VectorSettings(BaseSettings):
    """Settings for the pgvector-backed search service (src/vector)."""

    model_config = _BASE_CONFIG

    DATABASE_URL: str = "postgresql://ec_faq:ec_faq@pgvector-db:5432/ec_faq"
    DB_POOL_MAX_SIZE: int = Field(default=5, ge=1)

    # Must stay in sync with EMBEDDING_DIM and with whatever model produced
    # the rows already stored in faq_entries -- scores are meaningless across
    # models. Not in fastembed's built-in registry; registered as a custom
    # model in src/vector/embeddings.py, which also applies the E5-instruct
    # query prefix per RETRIEVAL_TASK below.
    EMBEDDING_MODEL_NAME: str = "intfloat/multilingual-e5-large-instruct"
    EMBEDDING_DIM: int = 1024
    EMBEDDING_CACHE_DIR: str = "/root/.cache/fastembed_cache"
    # Baked into the query instruction prefix ('Instruct: {task}\nQuery:
    # {text}'), per the E5-instruct convention.
    RETRIEVAL_TASK: str = (
        "Given a question, retrieve the FAQ entry that best answers it"
    )

    # Empty leaves POST /index and POST /reindex open -- fine behind a
    # private network, not fine on the public internet.
    INDEX_API_KEY: str = ""
    VECTOR_API_HOST: str = "0.0.0.0"
    VECTOR_API_PORT: int = 8001

    # -- Daily dataset refresh (src/vector/reindex.py) -----------------------
    # Rebuilds faq_entries from these two files, so an edit landed upstream
    # reaches search without a manual /index upload.
    TAG_ANSWER_URL: str = (
        "https://raw.githubusercontent.com/Synesis-IT-PLC/ec-faq-bot/"
        "development/full_dataset/tag_answer.json"
    )
    QUESTION_TAG_CSV_URL: str = (
        "https://raw.githubusercontent.com/Synesis-IT-PLC/ec-faq-bot/"
        "development/full_dataset/question_tag.csv"
    )
    GITHUB_TOKEN: str = ""
    REINDEX_FETCH_TIMEOUT: float = 30.0
    # Manual POST /reindex works regardless of this.
    REINDEX_ENABLED: bool = True
    # A fixed UTC hour rather than "every 24h from whenever the container
    # booted", so a restart at any hour doesn't shift it to a busier time.
    REINDEX_HOUR_UTC: int = Field(default=3, ge=0, le=23)


chatbot_settings = ChatbotSettings()
mcp_settings = McpSettings()
vector_settings = VectorSettings()
