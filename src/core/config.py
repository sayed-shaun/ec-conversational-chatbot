"""
Central configuration for every EC service, loaded from environment variables
(and an optional local .env for standalone/dev runs). Modules should import the
settings object they need from here instead of calling os.getenv directly, so
every knob is declared, typed, and validated in one place.

No host, endpoint or credential belonging to a deployment is written here.
Defaults cover only values that are the same everywhere -- timeouts, limits,
container-internal names -- so this file can be read by anyone without
disclosing where the services run. Anything deployment-specific defaults to
empty and comes from the environment; see .env.example.

Both settings objects are built at import, so a field one service needs
cannot be a required field without breaking the others. Each service instead
calls check_required() for its own settings at startup, which names what is
missing.

Field names are UPPERCASE to match the environment variables they're read
from 1:1, since pydantic-settings' case-insensitive matching means that
mapping already holds either way -- writing it out avoids having to mentally
lower-case an env var name to find its field, or vice versa.
"""

import os
from typing import ClassVar, List, Tuple

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
    """Base for every service's settings.

    REQUIRED names the variables that have no sensible default because they
    identify a deployment. They are declared with an empty default so that
    importing this module never fails for a service that does not need them,
    and checked by the service that does, at startup.
    """

    REQUIRED: ClassVar[Tuple[str, ...]] = ()

    def check_required(self) -> None:
        """Raise if a deployment-specific variable was left unset."""
        missing = [
            name for name in self.REQUIRED if not str(getattr(self, name, "")).strip()
        ]
        if missing:
            raise RuntimeError(
                "missing required environment variable(s): "
                + ", ".join(missing)
                + ". Set them in .env -- see .env.example."
            )


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


class ChatbotSettings(_Settings):
    """Settings for the FastAPI chatbot backend (src/chatbot).

    LLAMA_MODEL is sent but usually ignored by llama-server; the OpenAI
    client just requires a value. LLAMA_REASONING_EFFORT='none' suppresses
    most of the thinking pass on a reasoning model (the bulk of the delay
    before the first answer token); it's unreliable through the streaming
    path, so prefer llama-server's own --reasoning off instead.
    SESSION_TTL_MINUTES=0 (or less) keeps transcripts until reset
    explicitly.

    TRACE_DIR is empty by default, which disables tracing. Enabling it
    records each turn's question, reply and -- for a voice turn -- both
    sides of the audio, with the question text in the filename. That is a
    citizen's own words and voice on disk, so TRACE_TTL_DAYS defaults to
    7 and the recordings expire on their own; 0 keeps them forever, which
    is a deliberate choice to make rather than something to inherit from
    a default.

    SMART_BOT_URL is the base of the upstream EC smart bot and turns the
    hybrid path on: every turn is put to that API first, and only a turn
    it declines reaches the local LLM. Left empty (the default) there is
    no hybrid and every turn goes to the LLM, exactly as before.
    SMART_BOT_USE_LLM_SELECTOR forwards the API's own use_llm_selector
    query flag, which lets its selector arbitrate candidate disagreements
    rather than always serving the fused ranker's top hit.

    LIST_OF_TAGS_WILL_GO_TO_LLM is the whole set of answers the LLM
    writes instead of the smart bot, as a JSON list. "unable_to_answer"
    is in it because that is the API saying it has none; the greeting
    and farewell tags are in it because the dataset answers hello and
    goodbye with one fixed line each, which reads as canned to someone
    making small talk, and nothing about small talk needs the verbatim
    guarantee the dataset exists to provide. The list is exhaustive -- a
    tag removed from it is served from the dataset again, including
    "unable_to_answer".
    """

    model_config = _BASE_CONFIG

    REQUIRED: ClassVar[Tuple[str, ...]] = ("LLAMA_BASE_URL",)

    LLAMA_BASE_URL: str = Field(default="")
    LLAMA_MODEL: str = Field(default="local-model")
    LLAMA_REASONING_EFFORT: str = Field(default="")
    MCP_SERVER_URL: str = Field(default="http://ec-conversational-mcp:9000/mcp")
    SMART_BOT_URL: str = Field(default="")
    SMART_BOT_TIMEOUT: float = Field(default=60.0)
    SMART_BOT_USE_LLM_SELECTOR: bool = Field(default=True)
    LIST_OF_TAGS_WILL_GO_TO_LLM: List[str] = Field(
        default=["greetings", "salam_dao", "goodbye", "unable_to_answer"]
    )
    ASR_TTS_URL: str = Field(default="")
    ASR_TIMEOUT: float = Field(default=60.0)
    ASR_LANGUAGE: str = Field(default="bn")
    ASR_DUMP_DIR: str = Field(default="")
    TRACE_DIR: str = Field(default="")
    TRACE_TTL_DAYS: int = Field(default=7, ge=0)
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
    """Settings for the FastMCP server (src/mcp).

    TOP_SIMILAR_API_URL is the embedding-search endpoint the tool queries;
    it has no default because it names a deployment. GITHUB_TOKEN is
    required while
    Synesis-IT-PLC/ec-faq-bot is private. TAG_ANSWER_REFRESH_SECONDS=0
    disables polling and only fetches once at startup. MCP_TRANSPORT is
    'http' (Streamable HTTP, for Docker/network use) or 'stdio' (local MCP
    clients).
    """

    model_config = _BASE_CONFIG

    REQUIRED: ClassVar[Tuple[str, ...]] = ("TOP_SIMILAR_API_URL",)

    TOP_SIMILAR_API_URL: str = Field(default="")
    TOP_SIMILAR_TIMEOUT: float = Field(default=10.0)

    TAG_ANSWER_URL: str = Field(
        default=(
            "https://raw.githubusercontent.com/Synesis-IT-PLC/ec-faq-bot/"
            "development/full_dataset/tag_answer.json"
        )
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
