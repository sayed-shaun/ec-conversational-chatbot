"""
Outbound clients.

Two things this service talks to, one class each:

- `OpenAIClient` — the `openai` SDK pointed at llama-server's
  OpenAI-compatible /v1 endpoint, for both one-shot and streaming
  completions.
- `McpClient` — the EC FAQ MCP server (Streamable HTTP, FastMCP), for the
  `search_ec_services` tool.

Module-level `openai_client` and `mcp_client` instances are built from
settings at import, so callers just use them.
"""

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

import httpx
from fastmcp import Client
from openai import AsyncOpenAI, OpenAI

from src.core.config import chatbot_settings as settings
from src.core.logger import get_logger

logger = get_logger(__name__)


class OpenAIClient:
    """Chat completions against llama-server.

    Holds a sync client for one-shot calls and an async client for streaming.
    Streaming has to be async: iterating a sync stream would block the event
    loop and stall every other request the server is handling.
    """

    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url
        self.model = model
        self.client = OpenAI(base_url=base_url, api_key="not-needed")
        self.async_client = AsyncOpenAI(base_url=base_url, api_key="not-needed")

    def _kwargs(
        self,
        messages: List[dict],
        tools: Optional[List[dict]],
        tool_choice: str,
        stream: bool,
    ) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }
        if stream:
            kwargs["stream"] = True
        if settings.LLAMA_REASONING_EFFORT:
            kwargs["reasoning_effort"] = settings.LLAMA_REASONING_EFFORT
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice
        return kwargs

    def chat_completion(
        self,
        messages: List[dict],
        tools: Optional[List[dict]] = None,
        tool_choice: str = "auto",
    ) -> Any:
        """Send one chat-completion request and return the assistant message.

        Raises whatever the SDK raises; callers decide how to degrade.
        """
        logger.debug(
            "chat completion model=%s messages=%d tools=%d",
            self.model,
            len(messages),
            len(tools or []),
        )
        completion = self.client.chat.completions.create(
            **self._kwargs(messages, tools, tool_choice, stream=False)
        )
        return completion.choices[0].message

    async def chat_completion_stream(
        self,
        messages: List[dict],
        tools: Optional[List[dict]] = None,
        tool_choice: str = "auto",
    ) -> Any:
        """Open a streaming chat completion and return the async chunk iterator.

        Chunk deltas carry three interesting fields, and llama-server may send
        any combination of them: `reasoning_content` (the model thinking out
        loud), `content` (the actual answer), and `tool_calls` (streamed
        incrementally -- id and name arrive first, then argument fragments).
        """
        logger.debug(
            "stream completion model=%s messages=%d tools=%d",
            self.model,
            len(messages),
            len(tools or []),
        )
        return await self.async_client.chat.completions.create(
            **self._kwargs(messages, tools, tool_choice, stream=True)
        )


class McpClient:
    """Calls tools on the EC FAQ MCP server.

    A fresh session per call is simple and robust for a low/medium traffic FAQ
    bot; swap for a persistent client if you need lower latency at higher
    volume.
    """

    def __init__(self, server_url: str) -> None:
        self.server_url = server_url

    async def call_tool(self, name: str, arguments: dict) -> dict:
        """Invoke one MCP tool. Never raises: failures come back as
        `{"error": ...}` so the LLM can see what went wrong and say so."""
        try:
            async with Client(self.server_url) as client:
                result = await client.call_tool(name, arguments)
                if result.data is not None:
                    return result.data
                logger.warning("empty tool result from MCP server")
                return {"error": "empty tool result from MCP server"}
        except Exception as exc:
            logger.exception("MCP server call failed")
            return {"error": f"could not reach MCP server: {exc}"}

    async def search_ec_services(self, question: str, top_k: int = 10, **overrides) -> dict:
        """Search the FAQ knowledge base via the MCP `search_ec_services` tool."""
        arguments = {"question": question, "top_k": top_k}
        arguments.update({k: v for k, v in overrides.items() if v is not None})
        return await self.call_tool("search_ec_services", arguments)


_AUDIO_MIMES = {
    "webm": "audio/webm",
    "mp4": "audio/mp4",
    "m4a": "audio/mp4",
    "ogg": "audio/ogg",
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
}


def _audio_mime(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return _AUDIO_MIMES.get(ext, "application/octet-stream")


class AsrClient:
    """Sends audio to the Bengali ASR service and returns the transcript.

    The mirror image of TtsClient below: proxied through this app so the
    browser talks to one origin, and so the ASR host stays an internal
    detail. Multipart upload rather than the base64 JSON route, because the
    browser already holds a Blob from MediaRecorder.
    """

    def __init__(
        self, base_url: str, timeout: float = 60.0, language: str = ""
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.language = language

    async def transcribe(self, audio: bytes, filename: str = "audio.webm") -> str:
        """Return the transcript for one clip. Raises httpx errors on failure.

        Uses the service's OpenAI-compatible /v1/audio/transcriptions, which
        already joins its internal segments into one utterance -- the same
        shape TtsClient's /v1/audio/speech uses, so both halves of the voice
        path speak one API.

        Sends the audio under its real MIME type rather than a generic
        octet-stream, so a service that dispatches its decoder on content type
        (rather than sniffing the extension) gets the Opus path right.
        """
        data = {"language": self.language} if self.language else None
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/v1/audio/transcriptions",
                files={"file": (filename, audio, _audio_mime(filename))},
                data=data,
            )
            resp.raise_for_status()
            return resp.json().get("text", "")


class TtsClient:
    """Forwards speech-synthesis requests to the TTS service server-side.

    Proxied through this app rather than letting the browser call the TTS
    host directly, so the page talks to one origin and the model host stays
    internal -- see ASR_TTS_URL's docstring in core/config.py.
    """

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def synthesize(
        self,
        input_text: str,
        voice: str = "Aditi",
        response_format: str = "wav",
        description: str = "",
    ) -> Tuple[bytes, str]:
        """Returns (audio_bytes, content_type). Raises httpx errors on failure."""
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self.base_url}/v1/audio/speech",
                json=self._payload(input_text, voice, response_format, description),
            )
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "audio/wav")
            return resp.content, content_type

    @staticmethod
    def _payload(
        input_text: str, voice: str, response_format: str, description: str
    ) -> dict:
        payload = {
            "input": input_text,
            "voice": voice,
            "response_format": response_format,
        }
        # Only sent when set: the service rejects some fields as empty strings,
        # and an absent optional field is the safer default.
        if description:
            payload["description"] = description
        return payload

    @asynccontextmanager
    async def stream(
        self,
        input_text: str,
        voice: str = "Aditi",
        description: str = "",
    ) -> AsyncIterator[httpx.Response]:
        """Open a streaming synthesis request, yielding the live response.

        Always raw PCM: the service refuses stream=true for WAV, because a WAV
        header must declare a total length that is unknown until the last
        clause is synthesised. Callers get the real format from the response's
        own x-audio-* headers rather than assuming one.

        Streaming exists because the wait is otherwise dominated by synthesis:
        for one measured 468-character reply, the first audio byte arrives
        after 2.2s streaming versus 12.6s buffered. Generation runs about 2.7x
        faster than playback, so once playback starts it does not catch up.
        """
        payload = self._payload(input_text, voice, "pcm", description)
        payload["stream"] = True
        client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=120.0))
        try:
            async with client.stream(
                "POST", f"{self.base_url}/v1/audio/speech", json=payload
            ) as resp:
                resp.raise_for_status()
                yield resp
        finally:
            await client.aclose()


openai_client = OpenAIClient(settings.LLAMA_BASE_URL, settings.LLAMA_MODEL)
asr_client = AsrClient(
    settings.ASR_TTS_URL, settings.ASR_TIMEOUT, settings.ASR_LANGUAGE
)
mcp_client = McpClient(settings.MCP_SERVER_URL)
tts_client = TtsClient(settings.ASR_TTS_URL)
