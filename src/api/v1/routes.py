"""
v1 HTTP routes. This module is the transport layer only: it validates the
request, delegates to the chat engine in src.chatbot.chat, and shapes the
response. Conversation state, prompting, and the tool-calling loop live in
the engine.
"""

import json
import os
import time
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
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
from src.chatbot import trace
from src.core.config import chatbot_settings as settings
from src.core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    session_id = req.session_id or str(uuid.uuid4())
    logger.info(
        "chat request session=%s mode=%s chars=%d",
        session_id,
        req.mode,
        len(req.message),
    )

    params = req.params.model_dump() if req.params else None
    started = time.perf_counter()
    chat = await Chat.load(session_id, req.mode)
    reply = await chat.send(req.message, params)

    if req.turn_id:
        trace.record_chat(
            req.turn_id,
            session_id,
            req.mode,
            req.message,
            reply,
            (time.perf_counter() - started) * 1000,
        )

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
    logger.info(
        "stream request session=%s mode=%s chars=%d",
        session_id,
        req.mode,
        len(req.message),
    )

    async def events():
        yield _sse({"type": "start", "session_id": session_id})
        # Collected on the way past so the finished turn can be traced without
        # buffering it: the browser still receives each event as it happens.
        started = time.perf_counter()
        reply = ""
        tools: list = []
        try:
            chat = await Chat.load(session_id, req.mode)
            async for event in chat.stream(req.message, params):
                if event.get("type") == "done":
                    reply = event.get("reply") or ""
                elif event.get("type") == "tool_result":
                    tools.append(
                        {
                            "tag": event.get("best_tag"),
                            "score": event.get("best_score"),
                            "confident": event.get("confident"),
                            "error": event.get("error"),
                        }
                    )
                yield _sse(event)
        except Exception as exc:
            logger.exception("stream turn failed session=%s", session_id)
            yield _sse({"type": "error", "message": str(exc)})
        if req.turn_id:
            trace.record_chat(
                req.turn_id,
                session_id,
                req.mode,
                req.message,
                reply,
                (time.perf_counter() - started) * 1000,
                tools,
            )
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
async def asr(
    file: UploadFile = File(...),
    turn_id: str = Form(default=""),
    session_id: str = Form(default=""),
) -> AsrResponse:
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

    started = time.perf_counter()
    try:
        text = await asr_client.transcribe(audio, file.filename or "audio.webm")
    except httpx.HTTPStatusError as exc:
        logger.warning("ASR service returned %s", exc.response.status_code)
        raise HTTPException(status_code=502, detail="ASR service error") from exc
    except httpx.HTTPError as exc:
        logger.warning("ASR service unreachable: %s", exc)
        raise HTTPException(status_code=502, detail="ASR service unreachable") from exc

    logger.info("transcribed %d bytes -> %d chars", len(audio), len(text))

    if settings.ASR_DUMP_DIR:
        _dump_clip(audio, file.filename or "audio.webm", text)

    if turn_id:
        trace.record_asr(
            turn_id,
            session_id or None,
            audio,
            file.filename or "audio.webm",
            text,
            (time.perf_counter() - started) * 1000,
        )

    return AsrResponse(text=text)


def _dump_clip(audio: bytes, filename: str, text: str) -> None:
    """Write one received clip and its transcript to ASR_DUMP_DIR.

    Best-effort by design: a debug aid must never be able to fail the request
    it is instrumenting, so every error here is swallowed and logged.
    """
    try:
        os.makedirs(settings.ASR_DUMP_DIR, exist_ok=True)
        ext = os.path.splitext(filename)[1] or ".bin"
        stem = f"{datetime.now(timezone.utc):%H%M%S}-{len(audio)}b-{len(text)}c"
        path = os.path.join(settings.ASR_DUMP_DIR, stem + ext)
        with open(path, "wb") as handle:
            handle.write(audio)
        with open(os.path.join(settings.ASR_DUMP_DIR, stem + ".txt"), "w") as handle:
            handle.write(text)
        logger.info("dumped clip %s", path)
    except OSError as exc:
        logger.warning("could not dump clip: %s", exc)


@router.post("/tts")
async def tts(req: TtsRequest) -> Response:
    """Proxy to the TTS service, server-side.

    The browser calls this instead of the TTS service directly because that
    service has no CORS support -- a UI hosted on a different origin (e.g.
    Vercel) would have the request blocked by the browser otherwise. This
    app's own CORSMiddleware (CORS_ALLOW_ORIGINS) covers this route like any
    other.
    """
    if req.stream:
        return await _stream_tts(req)

    started = time.perf_counter()
    try:
        audio, content_type = await tts_client.synthesize(
            req.input, req.voice, req.response_format, req.description
        )
    except httpx.HTTPStatusError as exc:
        logger.warning("TTS service returned %s", exc.response.status_code)
        raise HTTPException(status_code=502, detail="TTS service error") from exc
    except httpx.HTTPError as exc:
        logger.warning("TTS service unreachable: %s", exc)
        raise HTTPException(status_code=502, detail="TTS service unreachable") from exc

    if req.turn_id:
        trace.record_tts(
            req.turn_id,
            req.session_id,
            req.input,
            req.voice,
            audio,
            streamed=False,
            ms=(time.perf_counter() - started) * 1000,
        )

    return Response(content=audio, media_type=content_type)


# Describe the PCM on the wire. The browser is handed headerless samples, so
# without these it cannot know the rate or width to play them at; they are
# forwarded from the upstream response rather than hardcoded, so a change of
# voice or model on the service does not silently detune playback here.
_PCM_HEADERS = ("x-audio-sample-rate", "x-audio-channels", "x-audio-format")


async def _stream_tts(req: TtsRequest) -> StreamingResponse:
    """Relay the TTS service's PCM stream straight through to the browser.

    The point is time-to-first-sound: the reply starts playing while the rest
    is still being synthesised. So the upstream connection has to stay open
    across the response, which means entering the stream here and handing the
    still-open body to StreamingResponse rather than returning a finished one.

    An upstream failure is only detectable before the first chunk -- once a
    200 and some bytes have gone to the browser the status line is spent, so a
    mid-stream error can only end the audio early, and the client falls back.
    """
    stream_cm = tts_client.stream(req.input, req.voice, req.description)
    try:
        resp = await stream_cm.__aenter__()
    except httpx.HTTPStatusError as exc:
        logger.warning("TTS stream returned %s", exc.response.status_code)
        raise HTTPException(status_code=502, detail="TTS service error") from exc
    except httpx.HTTPError as exc:
        logger.warning("TTS stream unreachable: %s", exc)
        raise HTTPException(status_code=502, detail="TTS service unreachable") from exc

    headers = {k: resp.headers[k] for k in _PCM_HEADERS if k in resp.headers}

    # Tee the samples on their way past. The reply cannot be recorded before
    # it is sent -- that would buffer the whole thing and give up the
    # time-to-first-sound this route exists for -- so it is collected while
    # relaying and written once the stream ends. Bounded by TTS_MAX_CHARS on
    # the client, a few megabytes at worst.
    recording = bytearray() if req.turn_id and trace.enabled() else None
    started = time.perf_counter()

    async def body():
        try:
            async for chunk in resp.aiter_bytes():
                if recording is not None:
                    recording.extend(chunk)
                yield chunk
        finally:
            await stream_cm.__aexit__(None, None, None)
            if recording:
                trace.record_tts(
                    req.turn_id,
                    req.session_id,
                    req.input,
                    req.voice,
                    bytes(recording),
                    streamed=True,
                    sample_rate=int(headers.get("x-audio-sample-rate", 0)) or None,
                    channels=int(headers.get("x-audio-channels", 0)) or None,
                    ms=(time.perf_counter() - started) * 1000,
                )

    return StreamingResponse(
        body(),
        media_type=resp.headers.get("content-type", "audio/pcm"),
        headers=headers,
    )
