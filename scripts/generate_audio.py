#!/usr/bin/env python3
"""
Render every answer in the FAQ dataset to speech, once, ahead of time.

Why this exists: synthesis is the slowest part of a spoken turn by a wide
margin -- 6 to 20 seconds for one answer against the live service, where the
rest of the turn is under a second -- and the bot almost never says anything
new. The smart bot answers out of a fixed dataset, one canned answer per tag,
so the same few hundred sentences are spoken over and over. Rendering them
once turns that wait into a file read (see src/speech/cache.py).

What gets rendered is the text the citizen actually hears, which is not the
raw dataset entry:

  * the smart bot appends a constant closing question to every answer, so it
    is appended here too, otherwise every single entry would miss;
  * transform.for_speech then rewrites it for a voice -- digits into Bangla
    words, initialisms respelled, markdown gone.

That second step is the reason this job lives in this repo rather than on the
TTS service. The service is a stateless text-to-audio endpoint with no notion
of the dataset, the tags, or how a fee should be read aloud; rendering there
would bake "২৩০" into the audio as digits instead of "দুইশ ত্রিশ".

Usage:

    python scripts/generate_audio.py                    # render what is missing
    python scripts/generate_audio.py --force            # re-render everything
    python scripts/generate_audio.py --limit 20         # a sample, to check a voice
    python scripts/generate_audio.py --format wav       # skip the encode step

Re-runs are cheap: an entry whose audio already exists is skipped, so an
interrupted run resumes, and a dataset edit renders only what changed. The key
is the spoken text, so changing an answer or the transform makes a new entry
and quietly abandons the old one -- use --prune to delete what is no longer
reachable.
"""

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from typing import Dict, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.config import chatbot_settings as settings  # noqa: E402
from src.speech import transform  # noqa: E402
from src.speech.cache import key_for, speech_cache  # noqa: E402
from src.speech.tts import tts_client  # noqa: E402

#: What the smart bot adds to the end of every answer it serves. Confirmed
#: against the live API: its `response` is the dataset entry followed by
#: exactly this. Rendering the answer without it would key the cache on text
#: the citizen never hears, and every lookup would miss.
CLOSING = " \n\nআপনাকে আর কোন তথ্য দিয়ে সহযোগিতা করতে পারি?"


def load_dataset(path: str) -> Dict[str, str]:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise SystemExit(f"{path}: expected an object of tag -> answer")
    return {t: a for t, a in data.items() if isinstance(a, str) and a.strip()}


def spoken_text(answer: str, closing: bool) -> str:
    """The exact words the citizen hears, and so the cache key."""
    return transform.for_speech(answer + CLOSING if closing else answer)


def encode(wav: bytes, fmt: str, bitrate: str) -> bytes:
    """Compress one WAV, because 1379 of them is 1.7 GB and speech does not
    need it -- the same clip is about 50 KB as MP3.

    ffmpeg is required only here, in the generator. The API container never
    encodes: it serves whatever this wrote, so it needs no codec installed.
    """
    if fmt == "wav":
        return wav

    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "wav", "-i", "pipe:0",
         "-codec:a", "libmp3lame", "-b:a", bitrate, "-f", "mp3", "pipe:1"],
        input=wav, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(
            "ffmpeg failed: " + proc.stderr.decode("utf-8", "replace")[:200]
        )
    return proc.stdout


async def render_one(
    tag: str, text: str, args, sem: asyncio.Semaphore
) -> Tuple[str, str, int, float]:
    """Synthesise and store one entry. Returns (tag, status, bytes, seconds)."""
    suffix = "." + args.format
    path = speech_cache.path_for(text, args.voice, suffix)

    if os.path.exists(path) and not args.force:
        return tag, "skip", os.path.getsize(path), 0.0

    started = time.perf_counter()
    async with sem:
        try:
            wav, _ = await tts_client.synthesize(text, args.voice, "wav", "")
        except Exception as exc:  # noqa: BLE001 - one bad entry must not end the run
            return tag, f"error: {type(exc).__name__}: {exc}"[:120], 0, 0.0

    try:
        audio = await asyncio.to_thread(encode, wav, args.format, args.bitrate)
    except Exception as exc:  # noqa: BLE001
        return tag, f"error: {exc}"[:120], 0, 0.0

    # Written beside the target and moved into place, so a run interrupted
    # mid-write cannot leave a truncated file that later reads as a cache hit
    # and plays half an answer.
    tmp = path + ".part"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp, "wb") as handle:
        handle.write(audio)
    os.replace(tmp, path)

    return tag, "done", len(audio), time.perf_counter() - started


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--dataset", default=None,
                        help="path to tag_answer.json (default: look beside the repo)")
    parser.add_argument("--voice", default="Aditi")
    parser.add_argument("--format", default="mp3", choices=["mp3", "wav"])
    parser.add_argument("--bitrate", default="48k")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0, help="render only the first N")
    parser.add_argument("--force", action="store_true", help="re-render existing")
    parser.add_argument("--prune", action="store_true",
                        help="delete cache files the dataset no longer reaches")
    parser.add_argument(
        "--no-closing",
        action="store_true",
        help="render the bare answer, without the closing line",
    )
    args = parser.parse_args()

    dataset_path = args.dataset or _find_dataset()
    if not speech_cache.enabled:
        raise SystemExit("TTS_CACHE_DIR is empty; set it before generating")
    if args.format == "mp3" and not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg is required for --format mp3 (or use --format wav)")

    data = load_dataset(dataset_path)
    items = sorted(data.items())
    if args.limit:
        items = items[: args.limit]

    texts = {tag: spoken_text(answer, not args.no_closing) for tag, answer in items}
    os.makedirs(speech_cache.directory, exist_ok=True)

    print(f"dataset   : {dataset_path} ({len(data)} entries)")
    print(f"rendering : {len(items)}  voice={args.voice}  format={args.format}")
    print(f"cache     : {speech_cache.directory}")
    print(f"service   : {settings.ASR_TTS_URL}\n")

    sem = asyncio.Semaphore(args.concurrency)
    started = time.perf_counter()
    done = skipped = failed = 0
    total_bytes = 0

    tasks = [
        asyncio.create_task(render_one(tag, texts[tag], args, sem)) for tag, _ in items
    ]
    for n, task in enumerate(asyncio.as_completed(tasks), 1):
        tag, status, size, _ = await task
        total_bytes += size
        if status == "done":
            done += 1
        elif status == "skip":
            skipped += 1
        else:
            failed += 1
            print(f"  [{n}/{len(tasks)}] {tag}: {status}")
        if n % 25 == 0 or n == len(tasks):
            rate = n / max(time.perf_counter() - started, 1e-9)
            left = (len(tasks) - n) / rate if rate else 0
            print(f"  [{n}/{len(tasks)}] done={done} skip={skipped} fail={failed} "
                  f"{total_bytes/1024/1024:.0f} MB  ~{left/60:.0f} min left")

    if args.prune:
        _prune(set(texts.values()), args.voice, args.format)

    _write_manifest(texts, args)

    print(f"\nrendered {done}, skipped {skipped}, failed {failed} "
          f"in {(time.perf_counter()-started)/60:.1f} min, "
          f"{total_bytes/1024/1024:.0f} MB total")
    return 1 if failed else 0


def _find_dataset() -> str:
    """Locate tag_answer.json the same way the MCP service does."""
    for candidate in (
        os.path.join("data", "tag_answer.json"),
        os.path.join("src", "mcp", "tag_answer.json"),
        settings.TAG_ANSWER_PATH if hasattr(settings, "TAG_ANSWER_PATH") else "",
    ):
        if candidate and os.path.exists(candidate):
            return candidate
    raise SystemExit("could not find tag_answer.json; pass --dataset")


def _prune(live: set, voice: str, fmt: str) -> None:
    """Delete entries the current dataset no longer asks for."""
    keep = {key_for(text, voice) + "." + fmt for text in live}
    removed = 0
    for name in os.listdir(speech_cache.directory):
        if name.endswith(".part") or name == "manifest.json":
            continue
        if name not in keep:
            os.remove(os.path.join(speech_cache.directory, name))
            removed += 1
    print(f"pruned {removed} unreachable file(s)")


def _write_manifest(texts: Dict[str, str], args) -> None:
    """Record what was rendered, for ops.

    The cache itself is content-addressed and needs no index; this is so a
    human can answer "is this tag rendered, and which file is it" without
    recomputing hashes by hand.
    """
    manifest = {
        "voice": args.voice,
        "format": args.format,
        "closing": not args.no_closing,
        "entries": {
            tag: {"key": key_for(text, args.voice), "chars": len(text)}
            for tag, text in sorted(texts.items())
        },
    }
    path = os.path.join(speech_cache.directory, "manifest.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
