"""
Central configuration for every EC FAQ service, loaded from environment
variables (and an optional local .env for standalone/dev runs). Modules
should import the settings object they need from here instead of calling
os.getenv directly, so every knob is declared, typed, and validated in
one place.
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
    file sits beside the process; from a checkout it lives in src/faq_mcp/.
    """
    candidates = [
        os.path.join(_SRC_DIR, "faq_mcp", "tag_answer.json"),
        os.path.join(os.getcwd(), "tag_answer.json"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return candidates[0]


class ChatbotSettings(BaseSettings):
    """Settings for the FastAPI chatbot backend (src/chatbot)."""

    model_config = _BASE_CONFIG

    llama_base_url: str = Field(
        default="http://172.31.60.228:8080/v1",
        description="Base URL of the OpenAI-compatible llama-server API.",
    )
    llama_model: str = Field(
        default="local-model",
        description=(
            "Model name sent in chat-completion requests " "(llama-server usually ignores it)."
        ),
    )

    mcp_server_url: str = Field(
        default="http://mcp-server:9000/mcp",
        description="Streamable HTTP endpoint of the EC FAQ MCP server.",
    )

    max_history_turns: int = Field(
        default=12,
        ge=1,
        description="How many past user+assistant turns to keep per session before trimming.",
    )
    max_tool_hops: int = Field(
        default=3,
        ge=1,
        description="Safety cap on tool-call round-trips per single user turn.",
    )

    session_db_path: str = Field(
        default="/data/sessions.db",
        description=(
            "SQLite file holding conversation checkpoints. "
            "Mount a volume at its directory to keep them."
        ),
    )

    session_ttl_minutes: int = Field(
        default=60,
        description=(
            "Clear a conversation after this many idle minutes. "
            "0 or less keeps transcripts until reset explicitly."
        ),
    )
    session_sweep_minutes: int = Field(
        default=10,
        ge=1,
        description="How often the background sweeper purges idle sessions.",
    )

    api_host: str = Field(
        default="0.0.0.0",
        description="Interface uvicorn binds for the chatbot API.",
    )
    api_port: int = Field(
        default=8000,
        description="Port uvicorn binds for the chatbot API.",
    )

    static_dir: str = Field(
        default="static",
        description="Directory served at /static, holding the test chat UI.",
    )


class McpSettings(BaseSettings):
    """Settings for the FastMCP server (src/faq_mcp)."""

    model_config = _BASE_CONFIG

    top_similar_api_url: str = Field(
        default="http://172.31.60.228:8002/ec_bot/top_similar/",
        description=(
            "POST endpoint returning top-k similar questions " "with tag + cosine_similarity."
        ),
    )
    top_similar_timeout: float = Field(
        default=10.0,
        description="Timeout in seconds for calls to top_similar_api_url.",
    )

    tag_answer_url: str = Field(
        default=(
            "https://raw.githubusercontent.com/Synesis-IT-PLC/ec-faq-bot/"
            "development/full_dataset/tag_answer.json"
        ),
        description="Raw URL of the tag -> answer JSON, fetched at startup.",
    )
    tag_answer_url_timeout: float = Field(
        default=15.0,
        description="Timeout in seconds for the startup fetch of tag_answer_url.",
    )
    github_token: str = Field(
        default="",
        description="GitHub token for tag_answer_url; required while the repo is private.",
    )
    tag_answer_path: str = Field(
        default_factory=_default_tag_answer_path,
        description="Local fallback copy of the tag -> Bengali answer JSON file.",
    )
    tag_answer_allow_local_fallback: bool = Field(
        default=True,
        description="If the live fetch fails, load tag_answer_path instead of failing startup.",
    )
    confidence_threshold: float = Field(
        default=0.55,
        ge=0.0,
        le=1.0,
        description="Minimum cosine_similarity for a match to be considered reliable.",
    )

    mcp_transport: str = Field(
        default="http",
        description=(
            "'http' (Streamable HTTP, for Docker/network use) " "or 'stdio' (local MCP clients)."
        ),
    )
    mcp_host: str = Field(default="0.0.0.0")
    mcp_port: int = Field(default=9000)
    mcp_path: str = Field(default="/mcp")


chatbot_settings = ChatbotSettings()
mcp_settings = McpSettings()
