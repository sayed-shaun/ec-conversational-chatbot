"""Configuration for both services, read from environment variables and .env."""

import os
from typing import List, ClassVar, Tuple

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_BASE_CONFIG = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    case_sensitive=False,
    extra="ignore",
)

_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _Settings(BaseSettings):
    """Base for both services' settings."""

    REQUIRED: ClassVar[Tuple[str, ...]] = ()

    def check_required(self) -> None:
        """Raise if a deployment-specific variable was left unset."""
        missing = [name for name in self.REQUIRED if not str(getattr(self, name, "")).strip()]
        if missing:
            raise RuntimeError(
                "missing required environment variable(s): "
                + ", ".join(missing)
                + ". Set them in .env -- see .env.example."
            )


def _default_tag_answer_path() -> str:
    """Locate tag_answer.json in a source checkout or inside the image."""
    candidates = [
        os.path.join(_SRC_DIR, "mcp", "tag_answer.json"),
        os.path.join(os.getcwd(), "tag_answer.json"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return candidates[0]


class ChatbotSettings(_Settings):
    """Settings for the FastAPI chatbot backend."""

    model_config = _BASE_CONFIG

    REQUIRED: ClassVar[Tuple[str, ...]] = ("LLAMA_BASE_URL",)

    LLAMA_BASE_URL: str = Field(default="")
    LLAMA_MODEL: str = Field(default="local-model")
    LLAMA_REASONING_EFFORT: str = Field(default="")
    MCP_SERVER_URL: str = Field(default="http://ec-conversational-mcp:9000/mcp")
    FAQ_MODEL_URL: str = Field(default="")
    FAQ_MODEL_TIMEOUT: float = Field(default=10.0, gt=0.0)
    FAQ_MODEL_USE_LLM_SELECTOR: bool = Field(default=False)
    LIST_OF_TAGS_WILL_GO_TO_LLM: List[str] = Field(
        default=["greetings", "salam_dao", "goodbye", "unable_to_answer"]
    )
    ASR_TTS_URL: str = Field(default="")
    ASR_TIMEOUT: float = Field(default=60.0)
    ASR_LANGUAGE: str = Field(default="bn")
    ASR_DUMP_DIR: str = Field(default="")
    TRACE_DIR: str = Field(default="")
    TRACE_TTL_DAYS: int = Field(default=0, ge=0)
    TRACE_SWEEP_HOURS: int = Field(default=6, ge=1)
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


class McpSettings(_Settings):
    """Settings for the FastMCP server (src/mcp)."""

    model_config = _BASE_CONFIG

    REQUIRED: ClassVar[Tuple[str, ...]] = ("TOP_SIMILAR_API_URL", "TAG_ANSWER_URL")

    TOP_SIMILAR_API_URL: str = Field(default="")
    TOP_SIMILAR_TIMEOUT: float = Field(default=10.0)

    TAG_ANSWER_URL: str = Field(default="")
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
