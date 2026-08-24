"""
v1 HTTP routes. This module is the transport layer only: it validates the
request, delegates to the chat engine in src.chatbot.chat, and shapes the
response. Conversation state, prompting, and the tool-calling loop live in
the engine.
"""

import json
import uuid

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from src.api.v1.schemas import ChatRequest, ChatResponse, ResetRequest, ResetResponse
from src.chatbot.chat import Chat
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
