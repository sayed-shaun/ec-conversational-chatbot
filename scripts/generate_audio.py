#!/usr/bin/env python3
"""
Render every answer in the FAQ dataset to an audio file, once.

The dataset is fixed -- one canned answer per tag -- so the bot says the same
few hundred sentences over and over, and synthesising them live costs 6 to 20
seconds each against the live service. This renders them ahead of time.

Serving them is not this repo's job: caching lives in the TTS service. So the
usual run is --warm, which simply asks the service to say every answer once
and throws the audio away -- the point is the entry it leaves in that cache,
not the bytes coming back. Without --warm the audio is written here instead,
one file per tag, which is for auditioning a voice or handing the clips to
someone, not for serving.

Either way a manifest records the exact text each answer speaks.

That text is the part only this repo can produce, and it is not the dataset
entry:

  * the smart bot appends a constant closing line to every answer it serves;
  * transform.for_speech then rewrites the result for a voice -- digits into
    Bangla words, initialisms respelled, markdown gone.

It matters for whoever builds the cache: POST /api/v1/tts sends the service
exactly this text, so a cache keyed on what the service receives has to be
keyed on these strings, character for character. The manifest is there so that
can be checked rather than assumed -- `spoken` is what arrives at the service.

One call per distinct text is enough: the service caches on the text and the
voice, not the output format, so warming it once serves both the buffered wav
a typed turn asks for and the PCM stream voice mode asks for. The dataset's
1379 tags share only 892 distinct answers, so that is what actually gets sent.

Usage:

    python scripts/generate_audio.py --warm             # fill the service's cache
    python scripts/generate_audio.py                    # write files here instead
    python scripts/generate_audio.py --out ./audio      # choose the directory
    python scripts/generate_audio.py --limit 20         # a sample, to audition a voice
    python scripts/generate_audio.py --manifest-only    # just the text, no synthesis
    python scripts/generate_audio.py --force            # re-render everything

Re-runs are cheap either way: a tag whose file already exists is skipped, and
a --warm pass over an already-warm cache is a few seconds of cache hits, so an
interrupted run just resumes and a dataset edit only costs what changed.
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

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.config import chatbot_settings as settings  # noqa: E402
from src.speech import transform  # noqa: E402
from src.speech.tts import tts_client  # noqa: E402

#: What the smart bot adds to the end of every answer it serves. Confirmed
#: against the live API: its `response` is the dataset entry followed by
#: exactly this. Rendering the answer without it would produce audio for text
#: no citizen ever hears.
CLOSING = " \n\nআপনাকে আর কোন তথ্য দিয়ে সহযোগিতা করতে পারি?"


def load_dataset(path: str) -> Dict[str, str]:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise SystemExit(f"{path}: expected an object of tag -> answer")
    return {t: a for t, a in data.items() if isinstance(a, str) and a.strip()}


def spoken_text(answer: str, closing: bool) -> str:
    """The exact words the citizen hears, and so what reaches the TTS service."""
    return transform.for_speech(answer + CLOSING if closing else answer)


def encode(wav: bytes, fmt: str, bitrate: str) -> bytes:
    """Compress one WAV. The dataset is roughly 1.7 GB of WAV against 120 MB of
    MP3, and speech at 48 kbps is indistinguishable over a phone."""
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
) -> Tuple[str, str, int]:
    """Synthesise and write one tag's file. Returns (tag, status, bytes)."""
    path = os.path.join(args.out, f"{tag}.{args.format}")

    if os.path.exists(path) and not args.force:
        return tag, "skip", os.path.getsize(path)

    async with sem:
        try:
            wav, _ = await tts_client.synthesize(text, args.voice, "wav", "")
        except Exception as exc:  # noqa: BLE001 - one bad entry must not end the run
            return tag, f"error: {type(exc).__name__}: {exc}"[:120], 0

    try:
        audio = await asyncio.to_thread(encode, wav, args.format, args.bitrate)
    except Exception as exc:  # noqa: BLE001
        return tag, f"error: {exc}"[:120], 0

    # Written beside the target and moved into place, so a run interrupted
    # mid-write cannot leave a truncated file that later looks complete.
    tmp = path + ".part"
    with open(tmp, "wb") as handle:
        handle.write(audio)
    os.replace(tmp, path)

    return tag, "done", len(audio)


async def warm_one(
    tag: str, text: str, args, sem: asyncio.Semaphore
) -> Tuple[str, str, int]:
    """Ask the service to say one answer, so its cache holds the result.

    The audio is read and dropped: this exists for the entry it leaves behind.
    x-cache tells us whether the service had it already, which is what makes a
    re-run legible -- a second pass should be all HITs.

    The tag goes with it, because the service caches a tagged reply and
    declines to cache an untagged one. It is also why this walks tags rather
    than distinct texts: if the service keys on the tag, every tag needs its
    own call, and if it keys on the text, the tags that share an answer come
    back as instant hits costing a round trip and no synthesis. Sending per
    tag is correct either way.
    """
    payload = {
        "input": text,
        "voice": args.voice,
        "response_format": "wav",
        "tag": tag,
    }
    async with sem:
        try:
            async with httpx.AsyncClient(timeout=args.timeout) as client:
                resp = await client.post(
                    f"{settings.ASR_TTS_URL.rstrip('/')}/v1/audio/speech", json=payload
                )
                resp.raise_for_status()
                status = "hit" if resp.headers.get("x-cache") == "HIT" else "warmed"
                return tag, status, len(resp.content)
        except Exception as exc:  # noqa: BLE001 - one bad entry must not end the run
            return tag, f"error: {type(exc).__name__}: {exc}"[:120], 0


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--dataset", default=None,
                        help="path to tag_answer.json (default: look in the repo)")
    parser.add_argument("--out", default="audio", help="output directory")
    parser.add_argument("--voice", default="Aditi")
    parser.add_argument("--format", default="mp3", choices=["mp3", "wav"])
    parser.add_argument("--bitrate", default="48k")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0, help="render only the first N")
    parser.add_argument("--force", action="store_true", help="re-render existing files")
    parser.add_argument(
        "--warm",
        action="store_true",
        help="fill the TTS service's cache instead of writing files here",
    )
    parser.add_argument("--timeout", type=float, default=180.0,
                        help="seconds to wait for one synthesis")
    parser.add_argument(
        "--manifest-only",
        action="store_true",
        help="write the spoken text and stop, without synthesising",
    )
    parser.add_argument(
        "--no-closing",
        action="store_true",
        help="render the bare answer, without the closing line",
    )
    args = parser.parse_args()

    dataset_path = args.dataset or _find_dataset()
    data = load_dataset(dataset_path)
    items = sorted(data.items())
    if args.limit:
        items = items[: args.limit]

    texts = {tag: spoken_text(answer, not args.no_closing) for tag, answer in items}
    os.makedirs(args.out, exist_ok=True)

    if args.manifest_only:
        _write_manifest(texts, args)
        print(f"wrote {len(texts)} spoken texts to {args.out}/manifest.json")
        return 0

    if args.warm:
        return await _warm(texts, args)

    if args.format == "mp3" and not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg is required for --format mp3 (or use --format wav)")

    print(f"dataset   : {dataset_path} ({len(data)} entries)")
    print(f"rendering : {len(items)}  voice={args.voice}  format={args.format}")
    print(f"output    : {os.path.abspath(args.out)}")
    print(f"service   : {settings.ASR_TTS_URL}\n")

    sem = asyncio.Semaphore(args.concurrency)
    started = time.perf_counter()
    done = skipped = failed = 0
    total_bytes = 0

    tasks = [
        asyncio.create_task(render_one(tag, texts[tag], args, sem)) for tag, _ in items
    ]
    for n, task in enumerate(asyncio.as_completed(tasks), 1):
        tag, status, size = await task
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

    _write_manifest(texts, args)

    print(f"\nrendered {done}, skipped {skipped}, failed {failed} "
          f"in {(time.perf_counter()-started)/60:.1f} min, "
          f"{total_bytes/1024/1024:.0f} MB total")
    print(f"manifest: {os.path.join(args.out, 'manifest.json')}")
    return 1 if failed else 0


async def _warm(texts: Dict[str, str], args) -> int:
    """Ask the service to say every tag's answer once.

    Per tag rather than per distinct answer, because the tag is what the
    service caches under. The dataset repeats itself heavily -- 1379 tags
    share 892 answers -- so the duplicates cost a round trip and a cache hit
    rather than a synthesis, which is cheap enough to be worth the certainty.
    """
    distinct = len(set(texts.values()))
    print(f"warming   : {len(texts)} tags ({distinct} distinct answers)")
    print(f"service   : {settings.ASR_TTS_URL}")
    print(f"voice     : {args.voice}   concurrency={args.concurrency}\n")

    sem = asyncio.Semaphore(args.concurrency)
    started = time.perf_counter()
    warmed = hits = failed = 0

    tasks = [
        asyncio.create_task(warm_one(tag, text, args, sem))
        for tag, text in sorted(texts.items())
    ]
    for n, task in enumerate(asyncio.as_completed(tasks), 1):
        _, status, _ = await task
        if status == "warmed":
            warmed += 1
        elif status == "hit":
            hits += 1
        else:
            failed += 1
            if failed <= 10:
                print(f"  [{n}/{len(tasks)}] {status}")
        if n % 25 == 0 or n == len(tasks):
            rate = n / max(time.perf_counter() - started, 1e-9)
            left = (len(tasks) - n) / rate if rate else 0
            print(f"  [{n}/{len(tasks)}] warmed={warmed} already={hits} "
                  f"failed={failed}  ~{left/60:.0f} min left")

    print(f"\nwarmed {warmed}, already cached {hits}, failed {failed} "
          f"in {(time.perf_counter()-started)/60:.1f} min")
    if failed:
        print("re-run to retry the failures; cached entries come back as hits")
    return 1 if failed else 0


def _find_dataset() -> str:
    """Locate tag_answer.json the same way the MCP service does."""
    for candidate in (
        os.path.join("data", "tag_answer.json"),
        os.path.join("src", "mcp", "tag_answer.json"),
        getattr(settings, "TAG_ANSWER_PATH", ""),
    ):
        if candidate and os.path.exists(candidate):
            return candidate
    raise SystemExit("could not find tag_answer.json; pass --dataset")


def _write_manifest(texts: Dict[str, str], args) -> None:
    """Record what each file says.

    `spoken` is the payload POST /api/v1/tts sends to the TTS service for that
    tag, character for character. Anything keying a cache on the text the
    service receives has to key on this, so it is written out rather than left
    to be re-derived.
    """
    manifest = {
        "voice": args.voice,
        "format": args.format,
        "closing": not args.no_closing,
        "entries": {
            tag: {"file": f"{tag}.{args.format}", "spoken": text}
            for tag, text in sorted(texts.items())
        },
    }
    path = os.path.join(args.out, "manifest.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
