"""
Answer a turn straight from the FAQ model when it is sure, skipping the LLM.

The FAQ model's `/qa` retrieves with e5 and, when its reranker runs, picks a
tag again independently. If both land on the same tag the match is trusted
and the stored answer is returned as is -- no tool call, no generation, so no
paraphrase and no chance of the model changing a fee. Anything else (no
agreement, no reranker, a low-confidence match, a service error) returns None
and the turn goes to the LLM, which searches and writes the answer itself.
"""

import asyncio
from typing import List, Optional

import requests

from src.core.config import chatbot_settings as settings
from src.core.logger import get_logger

logger = get_logger(__name__)

# Tags that hold small talk or a refusal, not an FAQ answer. Their stored text
# differs from the greeting and fallback wording the prompt requires.
NON_FAQ_TAGS = {"greetings", "goodbye", "unable_to_answer"}


def agreed(result: dict) -> bool:
    """True when retrieval and the reranker chose the same confident tag."""
    tag = result.get("tag")
    return bool(
        result.get("confident")
        and result.get("reranked")
        and tag
        and tag == result.get("retrieval_tag") == result.get("rerank_tag")
        and tag not in NON_FAQ_TAGS
        and (result.get("answer") or "").strip()
    )


def qa_history(history: List[dict]) -> List[dict]:
    """The transcript as /qa's `history`: plain question/answer pairs, so its
    rewrite service can resolve follow-ups like "কত টাকা লাগবে?"."""
    turns: List[dict] = []
    pending: Optional[str] = None
    for msg in history:
        role = msg.get("role")
        if role == "user":
            pending = msg.get("content") or ""
        elif role == "assistant" and not msg.get("tool_calls") and pending:
            turns.append(
                {"question": pending, "answer": msg.get("content") or "", "confident": True}
            )
            pending = None
    return turns


def _post(question: str, history: List[dict]) -> dict:
    response = requests.post(
        settings.FAQ_MODEL_URL.rstrip("/") + "/qa",
        json={"question": question, "history": history, "rerank": True},
        timeout=settings.FAQ_MODEL_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


async def try_direct(question: str, history: List[dict]) -> Optional[dict]:
    """Return the /qa result if it can be served directly, else None."""
    if not settings.FAQ_MODEL_URL:
        return None
    try:
        result = await asyncio.to_thread(_post, question, qa_history(history))
    except Exception as exc:
        logger.warning("direct /qa failed, falling back to the LLM: %s", exc)
        return None
    return result if agreed(result) else None
