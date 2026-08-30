"""Daily dataset refresh for the vector index.

Fetches tag_answer.json (tag -> answer) and question_tag.csv (question, tag
paraphrase pairs) from GitHub (TAG_ANSWER_URL / QUESTION_TAG_CSV_URL /
GITHUB_TOKEN), joins them into {tag, question, answer} entries, embeds them,
and replaces faq_entries wholesale -- the same join a one-off script would
do, just repeated on a schedule so an edit landed upstream reaches search
without a manual /index upload.

Call `start_scheduler()` once at server startup to run this every day at
REINDEX_HOUR_UTC via APScheduler (REINDEX_ENABLED=false disables it).
`reindex_once()` is also called directly by the manual POST /reindex
endpoint.
"""

import csv
import io
import json
import threading

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src.core.config import vector_settings as settings
from src.core.logger import get_logger
from src.vector import db
from src.vector.embeddings import embed_passages

logger = get_logger(__name__)

_scheduler = BackgroundScheduler(timezone="UTC")

_lock = threading.Lock()


def _fetch(url: str) -> str:
    headers = {}
    if settings.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"
    response = requests.get(url, headers=headers, timeout=settings.REINDEX_FETCH_TIMEOUT)
    response.raise_for_status()
    return response.text


def _build_entries() -> list[tuple[str, str, str]]:
    """Join tag_answer.json + question_tag.csv into (tag, question, answer)
    rows, one per question paraphrase whose tag has a known answer.

    The CSV's leading UTF-8 BOM is stripped before parsing -- left in, it
    glues onto the first header cell ("﻿question") and silently breaks
    every row.get("question") lookup below.
    """
    tag_answer = json.loads(_fetch(settings.TAG_ANSWER_URL))
    csv_text = _fetch(settings.QUESTION_TAG_CSV_URL).lstrip("﻿")
    reader = csv.DictReader(io.StringIO(csv_text))

    entries: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in reader:
        question = (row.get("question") or "").strip()
        tag = (row.get("tag") or "").strip()
        if not question or not tag:
            continue
        answer = tag_answer.get(tag)
        if answer is None:
            continue
        key = (tag, question)
        if key in seen:
            continue
        seen.add(key)
        entries.append((tag, question, answer))
    return entries


def reindex_once() -> int:
    """Fetch, join, embed, and replace faq_entries. Returns the row count.

    Not locked itself -- callers (below) hold _lock for the duration of the
    call, so this can't run concurrently with itself.
    """
    entries = _build_entries()
    if not entries:
        logger.warning("reindex fetched zero usable entries; leaving faq_entries untouched")
        return db.row_count()

    logger.info("reindexing %d entries from %s", len(entries), settings.QUESTION_TAG_CSV_URL)
    vectors = embed_passages([question for _, question, _ in entries])
    rows = [
        (tag, question, answer, vector)
        for (tag, question, answer), vector in zip(entries, vectors)
    ]
    written = db.replace_all(rows)
    logger.info("reindex complete: %d rows", written)
    return written


def trigger_background() -> bool:
    """Kick off a reindex on a background thread, if one isn't already
    running. Returns whether it was started.

    _lock is acquired here, synchronously, in the caller's thread -- not
    inside the spawned thread -- so two rapid calls can't both see the lock
    free and both start a run; the second sees it already held.
    """
    if not _lock.acquire(blocking=False):
        return False

    def _run() -> None:
        try:
            reindex_once()
        except Exception:
            logger.exception("triggered reindex failed")
        finally:
            _lock.release()

    threading.Thread(target=_run, daemon=True).start()
    return True


def _scheduled_reindex() -> None:
    if not _lock.acquire(blocking=False):
        logger.info("reindex already in progress (manual trigger); skipping scheduled run")
        return
    try:
        reindex_once()
    except Exception:
        logger.exception("scheduled reindex failed")
    finally:
        _lock.release()


def start_scheduler() -> None:
    """Start the daily reindex job, if configured to.

    misfire_grace_time=None plus coalesce=True means a missed run (e.g. the
    process was down at 03:00) fires once on the next startup instead of
    stacking up backlogged runs.
    """
    if not settings.REINDEX_ENABLED:
        return
    _scheduler.add_job(
        _scheduled_reindex,
        trigger=CronTrigger(hour=settings.REINDEX_HOUR_UTC, minute=0),
        id="daily_reindex",
        misfire_grace_time=None,
        coalesce=True,
        max_instances=1,
    )
    _scheduler.start()
    logger.info("scheduled daily reindex at %02d:00 UTC", settings.REINDEX_HOUR_UTC)
