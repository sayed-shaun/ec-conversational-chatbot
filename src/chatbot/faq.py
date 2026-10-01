"""Ask the EC smart bot (/ec_bot/smart/verbose/) to answer a turn directly."""

import re
from dataclasses import dataclass
from typing import Optional

import httpx

from src.core.config import chatbot_settings as settings
from src.core.logger import get_logger

logger = get_logger(__name__)

_CANNED_CLOSER = re.compile(r"\s*আপনাকে আর কোন তথ্য দিয়ে সহযোগিতা করতে পারি\?\s*$")


@dataclass
class SmartAnswer:
    text: str
    tag: str
    probability: Optional[float]
    messages: str


async def ask_smart(question: str, messages: str, chat_id: str) -> Optional[SmartAnswer]:
    """The smart bot's answer if both models agree on it, else None."""
    if not settings.SMART_BOT_URL:
        return None
    url = settings.SMART_BOT_URL.rstrip("/") + "/ec_bot/smart/verbose/"
    params = {"use_llm_selector": str(settings.SMART_BOT_USE_LLM_SELECTOR).lower()}
    body = {"question": question, "messages": messages, "chat_id": chat_id}
    try:
        async with httpx.AsyncClient(timeout=settings.SMART_BOT_TIMEOUT) as client:
            response = await client.post(url, json=body, params=params)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("smart API failed, using the LLM: %s", exc)
        return None

    tag = str(data.get("response_tag") or "")
    agreement = (data.get("trace") or {}).get("agreement") or {}
    agreed = bool(agreement.get("e5_bb_agreed") and agreement.get("e5_bb_comparable"))
    text = _CANNED_CLOSER.sub("", str(data.get("response") or "")).strip()
    use = agreed and bool(text) and tag not in settings.LIST_OF_TAGS_WILL_GO_TO_LLM
    logger.info(
        "smart turn chat_id=%s tag=%s source=%s agreed=%s direct=%s",
        chat_id, tag, data.get("prediction_source"), agreed, use,
    )
    if not use:
        return None
    return SmartAnswer(text, tag, data.get("probability"), str(data.get("messages") or ""))
