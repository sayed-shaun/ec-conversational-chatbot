"""Loads and keeps the tag -> answer knowledge base fresh.

`TAG_ANSWERS` is fetched live from GitHub (TAG_ANSWER_URL / GITHUB_TOKEN) at
import time, falling back to the bundled tag_answer.json if that fails. Call
`start_refresh_thread()` once at server startup to also poll for updates on
an interval (TAG_ANSWER_REFRESH_SECONDS), so an edit pushed to GitHub reaches
a running server without a restart.
"""

import json
import threading
import time

import requests

from src.core.config import mcp_settings as settings
from src.core.logger import get_logger

logger = get_logger(__name__)


def _fetch_tag_answers() -> dict:
    """Fetch the tag -> answer knowledge base from settings.tag_answer_url.

    Raw GitHub URLs for a private repo need a token; pass one via
    GITHUB_TOKEN. Raises on any transport, auth, or JSON error.
    """
    headers = {"Accept": "application/vnd.github.raw, application/json"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"

    response = requests.get(
        settings.tag_answer_url,
        headers=headers,
        timeout=settings.tag_answer_url_timeout,
    )
    response.raise_for_status()

    data = response.json()
    if not isinstance(data, dict) or not data:
        raise ValueError(
            f"expected a non-empty tag -> answer object, got {type(data).__name__}"
        )
    return data


def _load_local_tag_answers() -> dict:
    with open(settings.tag_answer_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_local_copy(data: dict) -> None:
    try:
        with open(settings.tag_answer_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        logger.warning("could not write local fallback copy", exc_info=True)


def _load_tag_answers() -> dict:
    """Load the knowledge base at startup: live from GitHub, with the bundled
    copy as a fallback so a network blip can't take the server down.

    A successful live fetch is also written through to tag_answer_path, so
    every restart syncs the on-disk copy immediately rather than waiting for
    the next periodic refresh tick."""
    try:
        data = _fetch_tag_answers()
        logger.info("fetched %d tags from %s", len(data), settings.tag_answer_url)
        _write_local_copy(data)
        return data
    except Exception as exc:
        if not settings.tag_answer_allow_local_fallback:
            logger.error("live tag_answer fetch failed and fallback is disabled")
            raise
        logger.warning(
            "live tag_answer fetch failed (%s); falling back to %s",
            exc,
            settings.tag_answer_path,
        )

    data = _load_local_tag_answers()
    logger.info("loaded %d tags from local fallback", len(data))
    return data


TAG_ANSWERS = _load_tag_answers()


def _refresh_tag_answers() -> None:
    """Re-fetch tag_answer_url and update TAG_ANSWERS in place, also
    overwriting the local fallback copy so a later restart sees it too."""
    try:
        data = _fetch_tag_answers()
    except Exception:
        logger.warning("periodic tag_answer_url refetch failed", exc_info=True)
        return

    if data == TAG_ANSWERS:
        return

    TAG_ANSWERS.clear()
    TAG_ANSWERS.update(data)
    logger.info("tag_answer_url refreshed (%d tags)", len(data))
    _write_local_copy(data)


def _refresh_loop() -> None:
    while True:
        time.sleep(settings.tag_answer_refresh_seconds)
        _refresh_tag_answers()


def start_refresh_thread() -> None:
    """Start polling for tag_answer_url updates, if configured to."""
    if settings.tag_answer_refresh_seconds <= 0:
        return
    threading.Thread(target=_refresh_loop, daemon=True).start()
    logger.info(
        "refreshing tag_answer_url every %ss", settings.tag_answer_refresh_seconds
    )
