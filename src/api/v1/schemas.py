"""Request/response models for the v1 HTTP API."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class SearchParams(BaseModel):
    """Retrieval knobs the UI's parameter panel can override per request.

    These are forwarded to the `search_ec_services` MCP tool. Anything left unset
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
    # Which surface asked, so the engine can pick the matching system prompt
    # (see src/chatbot/prompt.py). Per-request rather than per-session: the UI
    # keeps one session id whether the user types or talks. Defaults to "text",
    # so a caller that predates this field behaves exactly as before.
    mode: Literal["text", "voice"] = "text"
    # Groups this turn's calls in the trace. A typed turn is just this one
    # request; a spoken turn is ASR, then this, then TTS, all sharing the id.
    turn_id: Optional[str] = None


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
    # The service streams only as raw PCM -- a WAV header has to declare a
    # total length that is not known until the last clause is synthesised. The
    # route below swaps the format accordingly, so a caller only asks for
    # streaming and does not have to know that.
    stream: bool = False
    description: str = ""
    # Ties this reply to the ASR request that prompted it, so the two halves
    # land in one record. See src/api/trace.py.
    turn_id: Optional[str] = None
    session_id: Optional[str] = None


class AsrResponse(BaseModel):
    """Transcript of one uploaded clip."""

    text: str
