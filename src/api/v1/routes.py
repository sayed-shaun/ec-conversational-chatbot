"""
v1 HTTP routes. This module is the transport layer only: it validates the
request, delegates to the chat engine in src.chatbot.chat, and shapes the
response. Conversation state, prompting, and the tool-calling loop live in
the engine.
"""

import json
import uuid

import httpx
from fastapi import APIRouter, File, HTTPException, Response, UploadFile
from fastapi.responses import StreamingResponse

from src.api.v1.schemas import (
    AsrResponse,
    ChatRequest,
    ChatResponse,
    ResetRequest,
    ResetResponse,
    TtsRequest,
)
from src.chatbot.chat import Chat
from src.chatbot.client import asr_client, tts_client
from src.core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    session_id = req.session_id or str(uuid.uuid4())
    logger.info("chat request session=%s chars=%d", session_id, len(req.message))

    params = req.params.model_dump() if req.params else None
    chat = await Chat.load(session_id)
    reply = await chat.send(req.message, params)

    return ChatResponse(session_id=session_id, reply=reply)


def _sse(payload: dict) -> str:
    """Encode one event as a Server-Sent Events frame."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    """Same as /chat, but streams the turn as SSE so the browser can render
    thinking, tool calls, and answer tokens as they happen."""
    session_id = req.session_id or str(uuid.uuid4())
    params = req.params.model_dump() if req.params else None
    logger.info("stream request session=%s chars=%d", session_id, len(req.message))

    async def events():
        yield _sse({"type": "start", "session_id": session_id})
        try:
            chat = await Chat.load(session_id)
            async for event in chat.stream(req.message, params):
                yield _sse(event)
        except Exception as exc:
            logger.exception("stream turn failed session=%s", session_id)
            yield _sse({"type": "error", "message": str(exc)})
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/reset", response_model=ResetResponse)
async def reset(req: ResetRequest) -> ResetResponse:
    session_id = req.session_id or str(uuid.uuid4())
    await Chat.reset(session_id)
    logger.info("session reset session=%s", session_id)

    return ResetResponse(session_id=session_id)


@router.post("/asr", response_model=AsrResponse)
async def asr(file: UploadFile = File(...)) -> AsrResponse:
    """Transcribe one uploaded clip, server-side.

    The speech-in half of the voice path; POST /tts below is speech-out. Both
    are proxied for the same reason -- the browser holds a MediaRecorder Blob
    and should talk to one origin, and the model host stays internal.

    Errors mirror /tts: 502 for a failing or unreachable service, so a caller
    can tell "the model said no" apart from "the model is not there".
    """
    audio = await file.read()
    if not audio:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        text = await asr_client.transcribe(audio, file.filename or "audio.webm")
    except httpx.HTTPStatusError as exc:
        logger.warning("ASR service returned %s", exc.response.status_code)
        raise HTTPException(status_code=502, detail="ASR service error") from exc
    except httpx.HTTPError as exc:
        logger.warning("ASR service unreachable: %s", exc)
        raise HTTPException(status_code=502, detail="ASR service unreachable") from exc

    logger.info("transcribed %d bytes -> %d chars", len(audio), len(text))
    return AsrResponse(text=text)


@router.post("/tts")
async def tts(req: TtsRequest) -> Response:
    """Proxy to the TTS service, server-side.

    The browser calls this instead of the TTS service directly because that
    service has no CORS support -- a UI hosted on a different origin (e.g.
    Vercel) would have the request blocked by the browser otherwise. This
    app's own CORSMiddleware (CORS_ALLOW_ORIGINS) covers this route like any
    other.
    """
    try:
        audio, content_type = await tts_client.synthesize(
            req.input, req.voice, req.response_format
        )
    except httpx.HTTPStatusError as exc:
        logger.warning("TTS service returned %s", exc.response.status_code)
        raise HTTPException(status_code=502, detail="TTS service error") from exc
    except httpx.HTTPError as exc:
        logger.warning("TTS service unreachable: %s", exc)
        raise HTTPException(status_code=502, detail="TTS service unreachable") from exc

    return Response(content=audio, media_type=content_type)
