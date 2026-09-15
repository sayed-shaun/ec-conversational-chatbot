"""Trailing silence cut off a clip before the ASR is asked to read it.

The ASR's segmenter weighs how much of a clip is speech against how much is
not, so padding does not merely waste bytes -- it changes the answer.
Measured against this very service: a 0.9s "হ্যালো" transcribes correctly
with no padding and returns an empty string once 2.5s of trailing silence is
appended, and the shortest word tested, "হ্যাঁ", already fails at 1.0s. Long
sentences survive either way, carrying enough speech to transcribe
regardless.

Every endpointer leaves that padding behind. It cannot know an utterance is
over until silence has run for a beat, so the beat is always on the end of
the clip -- which is why this has to be cut somewhere, and why the browser
was already cutting it before upload. A phone caller reaches the same ASR
through Asterisk, whose endpointing leaves the same hangover and which
cannot trim anything itself. Doing it here is what makes "হ্যাঁ" and "না"
transcribable on a call, and those are most of what a caller says.

Only WAV is handled, because that is what can be decoded without pulling in
a media stack: the browser re-encodes to WAV before upload, and Asterisk
writes it natively. Anything else is passed through untouched rather than
guessed at -- an unreadable clip should reach the ASR as it was sent, not be
mangled on the way.

Trimming twice has to be harmless, because the browser trims before it
uploads and this runs on everything. It is not free by nature -- a second
pass re-reads the noise floor of a clip that is now almost all speech, and
shaves the margin again -- so a trim that would remove less than
_MIN_REMOVED_SECONDS is not made at all. Padding worth cutting is far larger
than that, and it makes the second pass a no-op rather than a nibble at the
end of a word.
"""

import io
import struct
import wave
from typing import List, Optional

# 20ms windows. One sample says nothing about whether speech is present, and
# a zero crossing mid-vowel would cut a word in half.
_WINDOW_SECONDS = 0.02

# Kept either side of a loud window. Cutting flush against one clips a soft
# onset and the decay of a final consonant, both of which the model needs to
# identify the word.
_MARGIN_SECONDS = 0.15

# A silence shorter than this between two runs of speech is kept, so a
# natural pause between words does not become a splice the model hears as
# two unrelated fragments. Leading and trailing silence still goes.
_BRIDGE_SECONDS = 0.30

_PEAK_RATIO = 0.10
_NOISE_RATIO = 3.0
_FLOOR = 1e-4

# The percentile taken as the clip's own noise level -- a low percentile
# rather than the minimum, since a single near-zero window would drag the
# estimate to nothing.
_NOISE_PERCENTILE = 0.2

# Below this, the clip is left exactly as it arrived. Comfortably above the
# margin a second pass would take off, and far below the padding an
# endpointer leaves -- which is a second or more, and the whole point.
_MIN_REMOVED_SECONDS = 0.25


def _speech_windows(energies: List[float], rate: int, window: int) -> List[bool]:
    """Which windows to keep, by energy against the clip's own levels."""
    peak = max(energies)
    if peak <= 0:
        return []

    ordered = sorted(energies)
    noise = ordered[int(len(ordered) * _NOISE_PERCENTILE)]
    # Both terms are needed. Peak-relative alone sets the bar under the noise
    # when speech is loud -- a 0.22 peak gives 0.013, below a 0.009 noise
    # floor, so noise counts as speech. Noise-relative alone drifts up with a
    # loud room and starts eating quiet speech.
    bar = max(peak * _PEAK_RATIO, noise * _NOISE_RATIO, _FLOOR)

    margin = max(1, round(rate * _MARGIN_SECONDS / window))
    keep = [False] * len(energies)
    for index, energy in enumerate(energies):
        if energy <= bar:
            continue
        for near in range(max(0, index - margin), min(len(energies), index + margin + 1)):
            keep[near] = True

    bridge = max(1, round(rate * _BRIDGE_SECONDS / window))
    index = 0
    while index < len(keep):
        if keep[index]:
            index += 1
            continue
        end = index
        while end < len(keep) and not keep[end]:
            end += 1
        # Only a gap BETWEEN speech is bridged: one that starts at the very
        # beginning, or runs to the very end, is the padding being cut.
        if index > 0 and end < len(keep) and end - index <= bridge:
            for gap in range(index, end):
                keep[gap] = True
        index = end

    return keep


def _extract(samples: List[int], rate: int) -> Optional[List[int]]:
    """The speech in `samples`, or None if the clip holds none."""
    window = max(1, round(rate * _WINDOW_SECONDS))
    energies = []
    for start in range(0, len(samples), window):
        block = samples[start : start + window]
        energies.append((sum(s * s for s in block) / len(block)) ** 0.5)
    if not energies:
        return None

    keep = _speech_windows(energies, rate, window)
    if not any(keep):
        return None

    out: List[int] = []
    for index, wanted in enumerate(keep):
        if wanted:
            out.extend(samples[index * window : (index + 1) * window])
    return out or None


def trim_silence(audio: bytes, filename: str = "") -> bytes:
    """Cut the silence around the speech in a WAV clip.

    Returns `audio` unchanged when the clip is not 16-bit PCM WAV, when it
    holds no speech, or when anything about it cannot be read -- the ASR
    deciding a clip is empty is a better failure than this module deciding
    it for them.
    """
    if not audio:
        return audio

    try:
        with wave.open(io.BytesIO(audio), "rb") as clip:
            channels = clip.getnchannels()
            width = clip.getsampwidth()
            rate = clip.getframerate()
            frames = clip.readframes(clip.getnframes())
    except (wave.Error, EOFError, ValueError):
        return audio

    # Mono 16-bit only. A µ-law or stereo clip would need converting before
    # the energies meant anything, and converting it is how a clip comes
    # back to the ASR as something other than what was sent.
    if channels != 1 or width != 2 or not frames:
        return audio

    samples = list(struct.unpack(f"<{len(frames) // 2}h", frames[: len(frames) // 2 * 2]))
    speech = _extract(samples, rate)
    if speech is None:
        return audio
    if len(samples) - len(speech) < rate * _MIN_REMOVED_SECONDS:
        return audio

    out = io.BytesIO()
    with wave.open(out, "wb") as written:
        written.setnchannels(1)
        written.setsampwidth(2)
        written.setframerate(rate)
        written.writeframes(struct.pack(f"<{len(speech)}h", *speech))
    return out.getvalue()
