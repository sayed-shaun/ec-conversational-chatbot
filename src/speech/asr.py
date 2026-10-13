"""Speech in: audio to the Bengali ASR service, transcript back.

Proxied through this app rather than called from the browser, so the page
talks to one origin and the ASR host stays an internal detail -- see
ASR_TTS_URL in core/config.py.
"""

import httpx

from src.core.config import chatbot_settings as settings
from src.core.logger import get_logger

logger = get_logger(__name__)


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

    The mirror image of tts.TtsClient: proxied through this app so the
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
        shape tts.TtsClient's /v1/audio/speech uses, so both halves of the
        voice path speak one API.

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


asr_client = AsrClient(
    settings.ASR_TTS_URL, settings.ASR_TIMEOUT, settings.ASR_LANGUAGE
)
