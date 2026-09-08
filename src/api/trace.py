"""On-disk record of every turn: what was asked, and what came back.

A typed turn is one chat request. A spoken turn is three -- ASR, chat, TTS --
arriving as independent HTTP calls, so the browser tags all of them with the
same `turn_id` and this module joins them into one record.

Each turn becomes three files under a date-stamped directory:

    data/tracing/<name>.json     question, reply, timings, sizes
    data/tracing/asr/<name>.wav  what the microphone uploaded (voice only)
    data/tracing/tts/<name>.wav  what was played back (voice only)

where <name> is `<timestamp>_<question>_<short id>`, e.g.

    2026-09-07_13-50-58_এনআইডি-সংশোধনের-ফি-কত_742272f9

so the directory sorts chronologically and says what each turn was about
without opening anything. The short id is the head of the turn id, and is what
lets the TTS half find the file the ASR half already started -- by then the
question is several HTTP calls behind us.

A typed turn leaves only the JSON; there is no audio to keep. The `mode` field
says which kind of turn it was.

The JSON sits at the root so a turn can be read at a glance, with the audio
kept to one side; both `audio` fields hold the path relative to that root, so
a record always says where to find its own sound.

The JSON is written when the ASR half lands and updated in place when the TTS
half follows, so a turn that never reaches TTS -- an empty transcript, a failed
answer -- still leaves its half of the record rather than vanishing.

Best-effort throughout: a recording of a conversation must never be able to
break the conversation, so every error is logged and swallowed.
"""

import glob
import json
import os
import re
import struct
import tempfile
from datetime import datetime, timezone
from typing import Optional

from src.core.config import chatbot_settings as settings
from src.core.logger import get_logger

logger = get_logger(__name__)


def enabled() -> bool:
    return bool(settings.TRACE_DIR)


def _safe_id(turn_id: str) -> str:
    """Keep a client-supplied id from escaping the log directory."""
    keep = [c for c in turn_id if c.isalnum() or c in "-_"]
    return "".join(keep)[:64] or "unknown"


# Characters a filename must not carry. The first group would break the path
# outright; the rest are illegal on Windows, and these files get copied around.
_FORBIDDEN = re.compile(r'[/\\\x00-\x1f<>:"|?*]')

# Bengali is three bytes a character in UTF-8, so a generous character count
# would still overrun the 255-byte limit on a filename component once the
# timestamp and id are added.
_SLUG_BYTES = 90


def _slug(text: str) -> str:
    """Turn a question into something safe, readable and short enough."""
    text = _FORBIDDEN.sub("", text or "")
    text = re.sub(r"\s+", "-", text.strip())
    text = re.sub(r"-{2,}", "-", text).strip("-.")
    while len(text.encode("utf-8")) > _SLUG_BYTES:
        text = text[:-1]
    return text.strip("-.") or "no-text"


# turn_id -> filename stem, so the halves of one turn agree on where to write.
# Bounded because a long-running server would otherwise remember every turn it
# has ever seen; a dropped entry costs one directory lookup, nothing more.
_stems: dict = {}
_STEMS_MAX = 2000


def _stem(turn_id: str, question: str = None) -> str:
    """The filename (without extension) for this turn."""
    tid = _safe_id(turn_id)
    cached = _stems.get(tid)
    if cached:
        return cached

    short = tid[:8]
    # A later half of a turn this process did not start -- after a restart, or
    # once the cache has rolled over. The short id is in the name for exactly
    # this: recover the stem rather than split the turn across two records.
    if question is None:
        found = glob.glob(os.path.join(settings.TRACE_DIR, f"*_{short}.json"))
        if found:
            stem = os.path.basename(sorted(found)[0])[: -len(".json")]
            _stems[tid] = stem
            return stem

    # Local time, punctuated, so the name reads as a date and matches the
    # clock of whoever is looking at the directory. Still sorts oldest-first.
    stamp = f"{datetime.now(timezone.utc).astimezone():%Y-%m-%d_%H-%M-%S}"
    stem = f"{stamp}_{_slug(question)}_{short}" if question else f"{stamp}_{short}"
    if len(_stems) >= _STEMS_MAX:
        _stems.clear()
    _stems[tid] = stem
    return stem


def _root(*subdirs: str) -> str:
    """Ensure the trace root (and any subdirectory) exists, and return it."""
    path = os.path.join(settings.TRACE_DIR, *subdirs)
    os.makedirs(path, exist_ok=True)
    try:
        os.chmod(path, 0o755)
    except OSError:
        pass
    return path


# Field order in the written JSON: when it happened and how long it took,
# then the conversation itself, then the detail behind it. A person reading a
# record should get the answer from the first four lines and never have to
# scroll for it.
_ORDER = (
    "when",
    "mode",
    "took",
    "heard",
    "replied",
    "spoken",
    "stages",
    "tools",
    "audio",
    "voice",
    "ids",
)


def _ordered(record: dict) -> dict:
    known = {k: record[k] for k in _ORDER if k in record}
    known.update({k: v for k, v in record.items() if k not in _ORDER})
    return known


def _write_atomic(path: str, data: bytes) -> None:
    """Write via a temp file in the same directory, then rename.

    A reader tailing the log never sees a half-written record, and a crash
    mid-write leaves the previous version rather than a truncated one.
    """
    directory = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        # mkstemp creates 0600, and this runs as root inside the container
        # while the directory is a bind mount from the host -- which would
        # leave every trace unreadable to the person who wants to read it.
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load(path: str) -> dict:
    try:
        with open(path, "rb") as handle:
            return json.loads(handle.read().decode("utf-8"))
    except (OSError, ValueError):
        return {}


def _save(path: str, record: dict) -> None:
    _write_atomic(
        path, json.dumps(_ordered(record), ensure_ascii=False, indent=2).encode()
    )


def _when(dt: datetime = None) -> str:
    """A timestamp a person can read against their own clock.

    Local time, not UTC: the container is given TZ, so this matches the wall
    clock of whoever is reading. Seconds are enough -- microseconds only made
    the four timestamps in a record harder to compare.
    """
    dt = (dt or datetime.now(timezone.utc)).astimezone()
    offset = dt.strftime("%z")  # +0600
    return dt.strftime("%Y-%m-%d %H:%M:%S ") + f"{offset[:3]}:{offset[3:]}"


def _secs(ms: float) -> str:
    return f"{ms / 1000:.2f} s"


def _size(nbytes: int) -> str:
    if nbytes >= 1024 * 1024:
        return f"{nbytes / 1024 / 1024:.1f} MB"
    return f"{max(nbytes, 0) // 1024} KB"


def _wav_seconds(data: bytes) -> Optional[float]:
    """Length of a RIFF/WAVE buffer, or None if it is some other format.

    Duration is the thing a person actually wants to know about a clip; the
    byte count on its own says nothing.
    """
    try:
        if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
            return None
        at = 12
        rate = channels = bits = None
        while at + 8 <= len(data):
            chunk = data[at:at + 4]
            size = int.from_bytes(data[at + 4:at + 8], "little")
            body = data[at + 8:at + 8 + size]
            if chunk == b"fmt " and len(body) >= 16:
                channels = int.from_bytes(body[2:4], "little")
                rate = int.from_bytes(body[4:8], "little")
                bits = int.from_bytes(body[14:16], "little")
            elif chunk == b"data" and rate and channels and bits:
                return len(body) / (rate * channels * (bits // 8))
            at += 8 + size + (size % 2)
    except (IndexError, ZeroDivisionError, ValueError):
        return None
    return None


def _audio_entry(path: str, data: bytes, seconds: Optional[float]) -> dict:
    entry = {"file": path, "size": _size(len(data))}
    if seconds:
        entry["length"] = f"{seconds:.2f} s"
    return entry


def wav_header(pcm_bytes: int, sample_rate: int, channels: int) -> bytes:
    """A 16-bit PCM WAV header.

    The streaming TTS route relays headerless samples -- a WAV header has to
    declare a length nothing knows until synthesis ends -- so the length is
    filled in here, where the whole reply has already gone past.
    """
    byte_rate = sample_rate * channels * 2
    return (
        b"RIFF"
        + struct.pack("<I", 36 + pcm_bytes)
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, channels * 2, 16)
        + b"data"
        + struct.pack("<I", pcm_bytes)
    )


def _touch(record: dict, turn_id: str, session_id, mode: str = None) -> dict:
    """Fill in the parts every record carries, whichever half arrived."""
    record.setdefault("when", _when())
    if mode:
        record["mode"] = mode
    ids = record.setdefault("ids", {})
    ids["turn"] = _safe_id(turn_id)
    if session_id:
        ids["session"] = session_id
    return record


def _retotal(record: dict) -> None:
    """Sum the stages into `took`.

    The stages run one after another -- transcribe, then answer, then speak --
    so their sum is the server-side wait behind one turn. It excludes the time
    the microphone spent listening and the network in between, which no part
    of this process can see.
    """
    stages = record.get("stages") or {}
    total = 0.0
    for value in stages.values():
        try:
            total += float(str(value).split()[0])
        except (ValueError, IndexError):
            pass
    record["took"] = f"{total:.2f} s"


def record_asr(
    turn_id: str,
    session_id: Optional[str],
    audio: bytes,
    filename: str,
    text: str,
    ms: float,
) -> None:
    """Save the uploaded clip and its transcript."""
    if not enabled():
        return
    try:
        root = _root()
        stem = _stem(turn_id, text)
        ext = os.path.splitext(filename)[1] or ".bin"
        audio_name = os.path.join("asr", f"{stem}{ext}")
        _write_atomic(os.path.join(_root("asr"), f"{stem}{ext}"), audio)

        path = os.path.join(root, f"{stem}.json")
        record = _touch(_load(path), turn_id, session_id, "voice")
        record["heard"] = text
        record.setdefault("stages", {})["transcribe"] = _secs(ms)
        record.setdefault("audio", {})["in"] = _audio_entry(
            audio_name, audio, _wav_seconds(audio)
        )
        _retotal(record)
        _save(path, record)
    except OSError as exc:
        logger.warning("could not record ASR turn %s: %s", turn_id, exc)


def record_tts(
    turn_id: str,
    session_id: Optional[str],
    text: str,
    voice: str,
    audio: bytes,
    streamed: bool,
    sample_rate: Optional[int] = None,
    channels: Optional[int] = None,
    ms: float = 0.0,
) -> None:
    """Save the synthesised reply and the text it was made from.

    `audio` is a finished file on the buffered path and raw PCM on the
    streaming one; the streaming case is given a WAV header so both land as
    something a player can open.
    """
    if not enabled():
        return
    try:
        root = _root()
        stem = _stem(turn_id)
        if streamed:
            body = wav_header(len(audio), sample_rate or 44100, channels or 1) + audio
        else:
            body = audio
        audio_name = os.path.join("tts", f"{stem}.wav")
        _write_atomic(os.path.join(_root("tts"), f"{stem}.wav"), body)

        path = os.path.join(root, f"{stem}.json")
        record = _touch(_load(path), turn_id, session_id, "voice")
        # Only when it differs from the reply. The browser strips markdown and
        # spells numbers out before speaking, so the two usually match -- and
        # repeating a long answer verbatim is the kind of noise that makes a
        # record tiring to read. When they do differ, that difference is
        # exactly what you came to the file for.
        if text.strip() != (record.get("replied") or "").strip():
            record["spoken"] = text
        else:
            record.pop("spoken", None)
        record.setdefault("stages", {})["speak"] = _secs(ms)
        record.setdefault("audio", {})["out"] = _audio_entry(
            audio_name, body, _wav_seconds(body)
        )
        record["voice"] = voice
        _retotal(record)
        _save(path, record)
    except OSError as exc:
        logger.warning("could not record TTS turn %s: %s", turn_id, exc)


def record_chat(
    turn_id: str,
    session_id: Optional[str],
    mode: str,
    question: str,
    reply: str,
    ms: float,
    tools: Optional[list] = None,
) -> None:
    """Save the question and the answer for one turn, typed or spoken.

    For a spoken turn this is the middle of the three calls, and sits between
    the `asr` and `tts` halves of the same record: `asr.text` is what the
    model was asked, `chat.reply` is what it wrote, and `tts.input` is that
    same reply after the browser strips markdown and spells numbers out.
    Keeping all three makes it possible to tell a mishearing apart from a bad
    answer apart from a bad reading.
    """
    if not enabled():
        return
    try:
        root = _root()
        stem = _stem(turn_id, question)
        path = os.path.join(root, f"{stem}.json")
        record = _touch(_load(path), turn_id, session_id, mode)
        record.setdefault("heard", question)
        record["replied"] = reply
        if record.get("spoken", "").strip() == reply.strip():
            record.pop("spoken", None)
        record.setdefault("stages", {})["answer"] = _secs(ms)
        if tools:
            record["tools"] = tools
        _retotal(record)
        _save(path, record)
    except OSError as exc:
        logger.warning("could not record chat turn %s: %s", turn_id, exc)
