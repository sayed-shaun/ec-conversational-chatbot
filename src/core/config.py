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

    LLAMA_BASE_URL: str = Field(
        default="http://172.31.60.228:8080/v1",
        description="Base URL of the OpenAI-compatible llama-server API.",
    )
    LLAMA_MODEL: str = Field(
        default="local-model",
        description=(
            "Model name sent in chat-completion requests "
            "(llama-server usually ignores it)."
        ),
    )

    LLAMA_REASONING_EFFORT: str = Field(
        default="",
        description=(
            "Passed through as reasoning_effort on chat-completion requests. "
            "Empty leaves the model's default. 'none' suppresses most of the "
            "thinking pass, which on a reasoning model is the bulk of the "
            "delay between a tool result and the first answer token."
        ),
    )

    MCP_SERVER_URL: str = Field(
        default="http://ec-faq-mcp:9000/mcp",
        description="Streamable HTTP endpoint of the EC FAQ MCP server.",
    )

    CORS_ALLOW_ORIGINS: str = Field(
        default="*",
        description=(
            "Comma-separated origins allowed to call this API cross-origin, "
            "e.g. when the UI is hosted separately (Vercel) from this "
            "backend. '*' allows any origin; fine here since no cookies or "
            "auth headers are used."
        ),
    )

    MAX_HISTORY_TURNS: int = Field(
        default=12,
        ge=1,
        description=(
            "How many past user+assistant turns to keep per session " "before trimming."
        ),
    )
    MAX_TOOL_HOPS: int = Field(
        default=3,
        ge=1,
        description="Safety cap on tool-call round-trips per single user turn.",
    )

    SESSION_DB_PATH: str = Field(
        default="/data/sessions.db",
        description=(
            "SQLite file holding conversation checkpoints. "
            "Mount a volume at its directory to keep them."
        ),
    )

    SESSION_TTL_MINUTES: int = Field(
        default=60,
        description=(
            "Clear a conversation after this many idle minutes. "
            "0 or less keeps transcripts until reset explicitly."
        ),
    )
    SESSION_SWEEP_MINUTES: int = Field(
        default=10,
        ge=1,
        description="How often the background sweeper purges idle sessions.",
    )

    API_HOST: str = Field(
        default="0.0.0.0",
        description="Interface uvicorn binds for the chatbot API.",
    )
    API_PORT: int = Field(
        default=8000,
        description="Port uvicorn binds for the chatbot API.",
    )

    STATIC_DIR: str = Field(
        default="static",
        description="Directory served at /static, holding the test chat UI.",
    )


class McpSettings(BaseSettings):
    """Settings for the FastMCP server (src/mcp)."""

    model_config = _BASE_CONFIG

    TOP_SIMILAR_API_URL: str = Field(
        default="http://ec-faq-vector:8001/top_similar",
        description=(
            "POST endpoint returning top-k similar questions "
            "with tag + cosine_similarity. Defaults to the self-hosted "
            "pgvector service (src/vector); point elsewhere to use a "
            "different backend."
        ),
    )
    TOP_SIMILAR_TIMEOUT: float = Field(
        default=10.0,
        description="Timeout in seconds for calls to TOP_SIMILAR_API_URL.",
    )

    TAG_ANSWER_URL: str = Field(
        default=(
            "https://raw.githubusercontent.com/Synesis-IT-PLC/ec-faq-bot/"
            "development/full_dataset/tag_answer.json"
        ),
        description="Raw URL of the tag -> answer JSON, fetched at startup.",
    )
    TAG_ANSWER_URL_TIMEOUT: float = Field(
        default=15.0,
        description="Timeout in seconds for the startup fetch of TAG_ANSWER_URL.",
    )
    GITHUB_TOKEN: str = Field(
        default="",
        description=(
            "GitHub token for TAG_ANSWER_URL; required while the repo is private."
        ),
    )
    TAG_ANSWER_PATH: str = Field(
        default_factory=_default_tag_answer_path,
        description="Local fallback copy of the tag -> Bengali answer JSON file.",
    )
    TAG_ANSWER_ALLOW_LOCAL_FALLBACK: bool = Field(
        default=True,
        description=(
            "If the live fetch fails, load TAG_ANSWER_PATH "
            "instead of failing startup."
        ),
    )
    TAG_ANSWER_REFRESH_SECONDS: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Re-fetch TAG_ANSWER_URL on this interval so GitHub-side edits "
            "reach a running server without a restart. 0 disables polling."
        ),
    )
    CONFIDENCE_THRESHOLD: float = Field(
        default=0.55,
        ge=0.0,
        le=1.0,
        description="Minimum cosine_similarity for a match to be considered reliable.",
    )

    MCP_TRANSPORT: str = Field(
        default="http",
        description=(
            "'http' (Streamable HTTP, for Docker/network use) "
            "or 'stdio' (local MCP clients)."
        ),
    )
    MCP_HOST: str = Field(default="0.0.0.0")
    MCP_PORT: int = Field(default=9000)
    MCP_PATH: str = Field(default="/mcp")


class VectorSettings(BaseSettings):
    """Settings for the pgvector-backed search service (src/vector)."""

    model_config = _BASE_CONFIG

    DATABASE_URL: str = Field(
        default="postgresql://ec_faq:ec_faq@pgvector-db:5432/ec_faq",
        description="Postgres connection string (psycopg format) for pgvector.",
    )
    DB_POOL_MAX_SIZE: int = Field(
        default=5,
        ge=1,
        description="Max connections in the Postgres connection pool.",
    )
    EMBEDDING_MODEL_NAME: str = Field(
        default="intfloat/multilingual-e5-large-instruct",
        description=(
            "fastembed model name. Must stay in sync with EMBEDDING_DIM and "
            "with whatever model produced the rows already stored in "
            "faq_entries, since scores are meaningless across models. The "
            "default isn't in fastembed's built-in registry and is "
            "registered as a custom model in src/vector/embeddings.py."
        ),
    )
    EMBEDDING_DIM: int = Field(
        default=1024,
        description="Vector width of EMBEDDING_MODEL_NAME's output.",
    )
    EMBEDDING_CACHE_DIR: str = Field(
        default="/root/.cache/fastembed_cache",
        description="Where fastembed caches downloaded model weights.",
    )
    INDEX_API_KEY: str = Field(
        default="",
        description=(
            "If set, POST /index requires this value in the X-API-Key "
            "header. Empty leaves the endpoint open (fine behind a private "
            "network, not fine on the public internet)."
        ),
    )
    VECTOR_API_HOST: str = Field(default="0.0.0.0")
    VECTOR_API_PORT: int = Field(default=8001)


chatbot_settings = ChatbotSettings()
mcp_settings = McpSettings()
vector_settings = VectorSettings()
