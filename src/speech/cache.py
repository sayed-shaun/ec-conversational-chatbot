"""
A cache of already-synthesised speech, addressed by the words it says.

Synthesis is the slowest thing in a spoken turn by a wide margin -- measured
against the live service, between 6 and 20 seconds for one FAQ answer, where
the rest of the turn is under a second. But the bot almost never says anything
new: the smart bot answers out of a fixed dataset, one canned answer per tag,
so the same few hundred sentences are spoken over and over. Rendering them
once ahead of time turns that wait into a file read.

The key is the finished spoken text, not the tag. Two reasons. The tag is not
known here -- /tts receives text and nothing else -- and keying on the words
means anything repeated is a hit, including the constant closing question the
smart bot appends to every answer, and any phrase the LLM fallback happens to
repeat. It also makes a stale entry impossible: change the dataset wording or
the transform, and the text changes, so the key changes and the old file is
simply never asked for again.

Populated by scripts/generate_audio.py, which is also where the encoding
happens. Nothing here writes: a miss is served live and not stored, so the API
container needs no encoder, and the cache only ever holds text someone
deliberately rendered.
"""

import hashlib
import os
from typing import Optional, Tuple

from src.core.config import chatbot_settings as settings
from src.core.logger import get_logger

logger = get_logger(__name__)

#: Formats an entry may be stored in, and what to serve them as. Tried in
#: order, so the smallest wins when a text was rendered more than once.
FORMATS = (
    (".mp3", "audio/mpeg"),
    (".wav", "audio/wav"),
)


def key_for(text: str, voice: str) -> str:
    """The cache key for one utterance in one voice.

    The voice is part of the key because the same sentence in another voice is
    a different recording; a cache that ignored it would play the wrong one
    after a voice change rather than re-rendering.
    """
    digest = hashlib.sha256()
    digest.update(voice.encode("utf-8"))
    digest.update(b"\n")
    digest.update(text.encode("utf-8"))
    return digest.hexdigest()


class SpeechCache:
    """Looks up pre-rendered audio on disk. Read-only by design."""

    def __init__(self, directory: str) -> None:
        self.directory = directory

    @property
    def enabled(self) -> bool:
        return bool(self.directory)

    def path_for(self, text: str, voice: str, suffix: str) -> str:
        """Where an entry lives. Used by the generator to write, and by
        lookup() to read, so both agree on the layout by construction."""
        return os.path.join(self.directory, key_for(text, voice) + suffix)

    def lookup(self, text: str, voice: str) -> Optional[Tuple[bytes, str]]:
        """Return (audio, content_type) for an already-rendered utterance.

        None means "synthesise it live" -- a miss, a cache that was never
        generated, or an unreadable file. It never raises: a broken cache must
        degrade to the behaviour that existed before there was one, not fail
        the request.
        """
        if not self.enabled:
            return None

        for suffix, content_type in FORMATS:
            path = self.path_for(text, voice, suffix)
            try:
                with open(path, "rb") as handle:
                    audio = handle.read()
            except FileNotFoundError:
                continue
            except OSError as exc:
                logger.warning("unreadable cache entry %s: %s", path, exc)
                continue
            if audio:
                return audio, content_type

        return None


speech_cache = SpeechCache(settings.TTS_CACHE_DIR)
