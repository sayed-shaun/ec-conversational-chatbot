"""Request/response models for the v1 HTTP API."""

from typing import Optional

from pydantic import BaseModel, Field


class SearchParams(BaseModel):
    """Retrieval knobs the UI's parameter panel can override per request.

    These are forwarded to the `search_faq` MCP tool. Anything left unset
    falls back to the tool's own defaults (and, for min_score, to the
    server-side CONFIDENCE_THRESHOLD).
    """

    top_k: int = Field(default=10, ge=1, le=50)
    min_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    min_score_ratio: float = Field(default=1.0, ge=0.0)
    handle_unknown: bool = True
    show_candidates: bool = True


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str
    params: Optional[SearchParams] = None


class ResetRequest(BaseModel):
    """Reset takes only a session id — no message is needed."""

    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str


class ResetResponse(BaseModel):
    session_id: str
    status: str = "reset"


class TtsRequest(BaseModel):
    """Mirrors the shape the browser already sends to the TTS service's own
    OpenAI-style /v1/audio/speech, so the frontend barely changes."""

    input: str
    voice: str = "Aditi"
    response_format: str = "wav"


class AsrResponse(BaseModel):
    """Transcript of one uploaded clip."""

    text: str
