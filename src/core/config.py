"""
Central configuration for every EC FAQ service, loaded from environment
variables (and an optional local .env for standalone/dev runs). Modules
should import the settings object they need from here instead of calling
os.getenv directly, so every knob is declared, typed, and validated in
one place.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_CONFIG = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    case_sensitive=False,
    extra="ignore",
)

class ChatbotSettings(BaseSettings):
    """Settings for the FastAPI chatbot backend (src/chatbot)."""

    model_config = BASE_CONFIG

    LLAMA_BASE_API: str = Field(
        default="",
        description="OpenAI-compatible llama-server API. Set in .env; required.",
    )

    LLAMA_TEMPERATURE: float = Field(default=0.2, ge=0.0, le=2.0)
    TRACE_DIR: str = Field(default="")
    TRACE_TTL_DAYS: int = Field(default=0, ge=0)
    TRACE_SWEEP_HOURS: int = Field(default=6, ge=1)
    ANSWER_CHECK: bool = Field(default=True)
    ANSWER_CHECK_CANDIDATES: int = Field(default=8, ge=1)
    LLAMA_THINKING: bool = Field(
        default=False,
        description=(
            "The one reasoning switch. Off asks the model not to think before "
            "answering, by sending enable_thinking=false (needs llama-server --jinja)."
        ),
    )

    MCP_SERVER_API: str = Field(
        default="http://ec-faq-mcp:9000/mcp",
        description="Streamable HTTP endpoint of the MCP server, inside the Docker network.",
    )

    CORS_ALLOW_ORIGINS: str = Field(
        default="*",
        description=(
            "Comma-separated origins allowed to call this API cross-origin, "
            "e.g. when the UI is hosted separately from this "
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


class SpeechSettings(BaseSettings):
    """Settings for the voice path: the speech service behind /api/v1/asr and
    /api/v1/tts (src/speech)."""

    model_config = BASE_CONFIG

    SPEECH_API: str = Field(
        default="",
        description=(
            "Base URL of the speech service (/v1/audio/transcriptions and "
            "/v1/audio/speech). The browser never calls it: this app proxies, so "
            "the page talks to one origin and the host stays internal."
        ),
    )
    ASR_TIMEOUT: float = Field(
        default=60.0,
        description="Seconds to wait for the speech service to transcribe one clip.",
    )
    TTS_MAX_CHARS: int = Field(
        default=3000,
        ge=1,
        description="Longest text sent to text-to-speech; the rest is cut.",
    )


class McpSettings(BaseSettings):
    """Settings for the FastMCP server (src/mcp)."""

    model_config = BASE_CONFIG

    TOPK_API: str = Field(
        default="",
        description=(
            "POST endpoint returning the nearest FAQ questions, each with its "
            "tag, cosine_similarity and the tag's answer. Set in .env; required."
        ),
    )
    TOPK_TIMEOUT: float = Field(
        default=10.0,
        description="Timeout in seconds for calls to TOPK_API.",
    )
    TOPK_ROWS: int = Field(
        default=100,
        ge=1,
        le=100,
        description=(
            "Questions asked of TOPK_API per search. Many questions share a tag, "
            "so a large number is needed to see enough distinct tags."
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


chatbot_settings = ChatbotSettings()
speech_settings = SpeechSettings()
mcp_settings = McpSettings()
