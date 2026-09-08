"""
Central configuration for every EC FAQ service, loaded from environment
variables (and an optional local .env for standalone/dev runs). Modules
should import the settings object they need from here instead of calling
os.getenv directly, so every knob is declared, typed, and validated in
one place.
"""

import os

from pydantic import Field, field_validator
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

    LLAMA_BASE_URL: str = Field(default="http://172.31.60.228:8080/v1")
    LLAMA_MODEL: str = Field(default="local-model")

    LLAMA_REASONING_EFFORT: str = Field(default="")

    @field_validator("LLAMA_REASONING_EFFORT")
    @classmethod
    def _check_reasoning_effort(cls, v: str) -> str:
        """Reject values that look like a dial but aren't one.

        llama-server reports `supports_reasoning_effort: false` and treats this
        as a binary: only "none" suppresses the thinking pass. "low"/"medium"/
        "high" are accepted by the API and then ignored, so a config that reads
        like a compromise silently buys full thinking -- and an invented value
        ("max") is swallowed just as quietly. Fail loudly instead.
        """
        v = v.strip().lower()
        if v in ("", "none"):
            return v
        if v in ("low", "medium", "high"):
            raise ValueError(
                f"LLAMA_REASONING_EFFORT={v!r} is a no-op: llama-server only "
                'honours "none". Use "none" to disable thinking, or "" to '
                "leave it on."
            )
        raise ValueError(
            f"LLAMA_REASONING_EFFORT={v!r} is not a valid effort. "
            'Use "none" or "".'
        )

    MCP_SERVER_URL: str = Field(default="http://ec-faq-mcp:9000/mcp")

    ASR_TTS_URL: str = Field(default="http://172.31.60.228:8000")

    ASR_TIMEOUT: float = Field(default=60.0)

    ASR_LANGUAGE: str = Field(default="bn")

    ASR_DUMP_DIR: str = Field(default="")

    TRACE_DIR: str = Field(default="/data/tracing")

    TTS_MAX_CHARS: int = Field(default=3000, ge=1)

    CORS_ALLOW_ORIGINS: str = Field(default="*")

    MAX_HISTORY_TURNS: int = Field(default=12, ge=1)
    MAX_TOOL_HOPS: int = Field(default=3, ge=1)

    SESSION_DB_PATH: str = Field(default="/data/sessions.db")

    SESSION_TTL_MINUTES: int = Field(default=60)
    SESSION_SWEEP_MINUTES: int = Field(default=10, ge=1)

    API_HOST: str = Field(default="0.0.0.0")
    API_PORT: int = Field(default=8000)

    STATIC_DIR: str = Field(default="static")


class McpSettings(BaseSettings):
    """Settings for the FastMCP server (src/mcp)."""

    model_config = _BASE_CONFIG

    TOP_SIMILAR_API_URL: str = Field(
        default="http://172.31.60.228:8002/ec_bot/top_similar/",
    )
    TOP_SIMILAR_TIMEOUT: float = Field(default=10.0)

    TAG_ANSWER_URL: str = Field(
        default=(
            "https://raw.githubusercontent.com/Synesis-IT-PLC/ec-faq-bot/"
            "development/full_dataset/tag_answer.json"
        ),
    )
    TAG_ANSWER_URL_TIMEOUT: float = Field(default=15.0)
    GITHUB_TOKEN: str = Field(default="")
    TAG_ANSWER_PATH: str = Field(default_factory=_default_tag_answer_path)
    TAG_ANSWER_ALLOW_LOCAL_FALLBACK: bool = Field(default=True)
    TAG_ANSWER_REFRESH_SECONDS: float = Field(default=0.0, ge=0.0)
    CONFIDENCE_THRESHOLD: float = Field(default=0.55, ge=0.0, le=1.0)

    MCP_TRANSPORT: str = Field(default="http")
    MCP_HOST: str = Field(default="0.0.0.0")
    MCP_PORT: int = Field(default=9000)
    MCP_PATH: str = Field(default="/mcp")


chatbot_settings = ChatbotSettings()
mcp_settings = McpSettings()
