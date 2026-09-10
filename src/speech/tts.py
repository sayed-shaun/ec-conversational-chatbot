"""Speech out: reply text to the TTS service, audio back.

The mirror image of asr.py, and proxied for the same reasons. Text handed to
this client should already have been through transform.for_speech; this module
only moves bytes.
"""

from contextlib import asynccontextmanager
from typing import AsyncIterator, Tuple

import httpx

from src.core.config import chatbot_settings as settings
from src.core.logger import get_logger

logger = get_logger(__name__)


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
        """Build the synthesis request body.

        `description` is included only when set: the service rejects some
        fields given as empty strings, and omitting an unset optional
        field is the safer default.
        """
        payload = {
            "input": input_text,
            "voice": voice,
            "response_format": response_format,
        }
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


tts_client = TtsClient(settings.ASR_TTS_URL)
