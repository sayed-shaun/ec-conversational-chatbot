"""
Client for the upstream EC smart bot (BanglaBERT + FAISS + keyword booster).

This is the first half of the hybrid: the smart API owns the knowledge base
and answers the great majority of turns from it directly, word for word, with
no generation involved. Only when it explicitly declines does the local LLM
get the turn -- see `SmartReply.declined` and src/chatbot/chat.py.

The API is stateful per conversation in a pass-the-transcript way: it takes a
`messages` JSON string and a `chat_id`, and returns the transcript with this
turn appended. That returned string is what must come back on the next turn,
because it carries the per-turn `tag` the API uses for its own repeat and
follow-up handling -- a transcript rebuilt from role/content alone would
silently lose it. So it is checkpointed verbatim alongside the LLM history.
"""

import json
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from src.core.config import chatbot_settings as settings
from src.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class SmartReply:
    """One turn's answer from the smart API.

    `declined` is the routing decision this whole module exists to produce.
    It is true when the API said in so many words that it has no answer
    (`response_tag == DECLINE_TAG`), and also when the call failed -- an
    unreachable knowledge base is still a turn with no answer in it, and
    falling through to the LLM keeps the bot talking while it is down.
    `error` distinguishes the two for the logs and the trace.
    """

    text: str = ""
    tag: str = ""
    probability: Optional[float] = None
    source: str = ""
    messages: str = ""
    is_relevant: bool = True
    error: str = ""

    @property
    def declined(self) -> bool:
        if self.error or not self.text.strip():
            return True
        return self.tag == SmartBotClient.DECLINE_TAG


class SmartBotClient:
    """Calls POST {base}/ec_bot/smart/ for one conversational turn.

    Never raises: a transport or protocol failure comes back as a SmartReply
    carrying `error`, which reads as a decline. The caller's job is to route,
    not to handle HTTP.
    """

    #: The API's own name for "I have no answer for this". Confirmed against
    #: the live service: an off-topic question returns this tag with
    #: prediction_source 'llm_selector_declined'.
    DECLINE_TAG = "unable_to_answer"

    def __init__(self, base_url: str, timeout: float, use_llm_selector: bool) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.use_llm_selector = use_llm_selector

    @property
    def enabled(self) -> bool:
        """Whether the hybrid path is configured at all.

        With SMART_BOT_URL unset the service behaves exactly as it did before
        the hybrid existed -- every turn goes to the LLM. That keeps this a
        deployment choice rather than a code change.
        """
        return bool(self.base_url)

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/ec_bot/smart/"

    async def ask(self, question: str, messages: str, chat_id: str) -> SmartReply:
        """Ask the smart API one question within a conversation.

        `messages` is the string this method returned as `SmartReply.messages`
        on the previous turn, or "" to start a conversation.
        """
        payload = {"question": question, "messages": messages or "", "chat_id": chat_id}
        params = {"use_llm_selector": str(self.use_llm_selector).lower()}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.endpoint, json=payload, params=params
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "smart API returned %s chat_id=%s", exc.response.status_code, chat_id
            )
            return SmartReply(error=f"smart API HTTP {exc.response.status_code}")
        except httpx.HTTPError as exc:
            logger.warning("smart API unreachable chat_id=%s: %s", chat_id, exc)
            return SmartReply(error=f"smart API unreachable: {exc}")
        except json.JSONDecodeError as exc:
            logger.warning("smart API sent non-JSON chat_id=%s: %s", chat_id, exc)
            return SmartReply(error="smart API sent a malformed response")

        if not isinstance(data, dict):
            logger.warning("smart API sent %s, expected an object", type(data).__name__)
            return SmartReply(error="smart API sent an unexpected shape")

        return self._parse(data)

    @staticmethod
    def _parse(data: dict) -> SmartReply:
        """Shape one response body into a SmartReply.

        Every field is read defensively. The API's documented fields are
        stable, but a decline that arrived as a KeyError here would surface as
        a 500 instead of a fallback, which is the opposite of what the hybrid
        is for.
        """
        return SmartReply(
            text=str(data.get("response") or ""),
            tag=str(data.get("response_tag") or ""),
            probability=_as_float(data.get("probability")),
            source=str(data.get("prediction_source") or ""),
            messages=str(data.get("messages") or ""),
            is_relevant=bool(data.get("is_relevant", True)),
        )


def _as_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


smart_client = SmartBotClient(
    settings.SMART_BOT_URL,
    settings.SMART_BOT_TIMEOUT,
    settings.SMART_BOT_USE_LLM_SELECTOR,
)
