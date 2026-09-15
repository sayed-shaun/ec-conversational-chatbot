"""
The chat engine.

A Chat instance is one conversation: it holds that session's transcript and
drives a user turn to a final reply, calling tools as the model asks for them.
Load one per request with Chat.load(), which restores the transcript from the
checkpointer.

The engine is hybrid, and the order matters. Every turn goes first to the
upstream smart bot (src/chatbot/smart.py), which answers out of the knowledge
base verbatim. Only a turn that API explicitly declines -- or cannot be
reached for -- falls through to the local LLM and its tool loop. So the LLM is
the backstop for what the knowledge base has no entry for, not the front door;
with SMART_BOT_URL unset there is no front door and every turn goes to the LLM
as it did before.

A smart-answered turn is still written into the LLM transcript, so a later
fallback sees the whole conversation rather than starting mid-thread. The
smart API's own transcript is opaque and rides alongside in `smart_messages`.

The prompt text lives in prompt.py and the tool catalogue in tools.py.
"""

import json
import re
from typing import AsyncIterator, Dict, List

from src.chatbot.checkpointer import checkpointer
from src.chatbot.client import openai_client
from src.chatbot.prompt import (
    ACKNOWLEDGED_REPLY,
    ENGLISH_SLIP_REPLY,
    FALLBACK_REPLY,
    GREETING_OPENERS,
    SYSTEM_PROMPT,
)
from src.chatbot.sanitize import StreamScrubber, scrub
from src.chatbot.smart import SmartReply, smart_client
from src.chatbot.tools import TOOLS, run_tool, tool_summary
from src.core.config import chatbot_settings as settings
from src.core.logger import get_logger

logger = get_logger(__name__)

# Any Bengali character. One is enough to say the model answered in Bengali.
_BENGALI = re.compile(r"[\u0980-\u09FF]")


#: Name the smart-bot lookup reports itself under in the stream. It is not a
#: model-callable tool, but it is a retrieval step with a tag and a score, so
#: it rides the same tool_call/tool_result events and the existing UI renders
#: it with no change.
SMART_STEP = "ec_bot_smart"


class Chat:
    """One conversation, identified by its session id."""

    def __init__(
        self, session_id: str, history: List[dict], smart_messages: str = ""
    ) -> None:
        self.session_id = session_id
        self.history = history
        self.smart_messages = smart_messages
        #: Which engine produced the most recent reply, "smart" or "llm", for
        #: the API response and the logs. Callers should read it only after a
        #: send() or a finished stream().
        self.last_source = ""
        #: The knowledge-base tag behind the most recent reply, or "" when the
        #: LLM wrote it. It goes out with the reply so the voice path can hand
        #: it to the TTS service, which caches a tagged answer and declines to
        #: cache anything else -- an LLM answer is new wording every time, so
        #: caching it would only evict the canned answers that do repeat.
        self.last_tag = ""

    @staticmethod
    def new_history() -> List[dict]:
        """A fresh transcript: just the system prompt."""
        return [{"role": "system", "content": SYSTEM_PROMPT}]

    def refresh_prompt(self) -> None:
        """Put the current system prompt at the head of the transcript.

        Done on every turn rather than once when the session began, because the
        transcript is checkpointed to SQLite: a prompt frozen at session
        creation would outlive an edit to prompt.py, and a running session
        would keep answering under wording that no longer exists in the repo.
        """
        if self.history and self.history[0].get("role") == "system":
            self.history[0] = {"role": "system", "content": SYSTEM_PROMPT}
        else:
            self.history.insert(0, {"role": "system", "content": SYSTEM_PROMPT})

    @classmethod
    async def load(cls, session_id: str) -> "Chat":
        """Restore a conversation from the checkpointer, or start a new one."""
        history, smart_messages = await checkpointer.load(session_id)
        chat = cls(session_id, history or cls.new_history(), smart_messages)
        chat.refresh_prompt()
        return chat

    @staticmethod
    async def reset(session_id: str) -> None:
        """Drop a session's stored transcript."""
        await checkpointer.delete(session_id)

    def trim(self) -> None:
        """Keep the system prompt plus only the most recent turns, so the
        context window doesn't grow unbounded over a long chat.

        The window is deliberately not a plain tail slice. A raw slice can cut
        between an assistant `tool_calls` message and the `tool` results
        answering it, and an orphaned `tool` message is rejected by the
        chat-completions API, which would break every later request in this
        session. So the window is walked forward until it starts on a plain
        user message.
        """
        system_msg, rest = self.history[0], self.history[1:]
        max_messages = settings.MAX_HISTORY_TURNS * 2
        if len(rest) <= max_messages:
            return

        rest = rest[-max_messages:]
        start = 0
        while start < len(rest) and rest[start].get("role") != "user":
            start += 1
        self.history = [system_msg] + rest[start:]

    async def save(self) -> None:
        """Trim and checkpoint both transcripts."""
        self.trim()
        await checkpointer.save(self.session_id, self.history, self.smart_messages)

    def _clean(self, text: str) -> str:
        """Strip any tool-name talk out of a finished reply.

        The model is asked not to mention the tool, but does anyway often
        enough that the prompt cannot be the only line of defence. If that
        removes the entire reply there is nothing worth showing, so the
        canned fallback stands in.
        """
        cleaned = scrub(text).strip()
        if cleaned != (text or "").strip():
            logger.warning(
                "scrubbed tool-name talk from reply session=%s", self.session_id
            )
        return self._in_bengali(self._no_reopening(cleaned)) or FALLBACK_REPLY

    def _no_reopening(self, text: str) -> str:
        """Keep the opening greeting to the opening.

        Rule 8 mandates one sentence for a greeting and rule 8a forbids it
        afterwards, but the model writes it anyway for a bare "আচ্ছা" often
        enough that the prompt cannot be the only line of defence -- it was
        one turn in two before this. Offering to help someone who has just
        acknowledged an answer restarts the conversation: they acknowledge
        again, and on a phone line the call cannot end.

        Only an exact match is replaced. Anything the model has written
        around the sentence is a real reply and is left alone.
        """
        stripped = (text or "").strip()
        if stripped not in GREETING_OPENERS:
            return text
        if not any(turn.get("role") == "assistant" for turn in self.history):
            return text
        logger.info("greeting reopened a live turn session=%s", self.session_id)
        return ACKNOWLEDGED_REPLY

    def _in_bengali(self, text: str) -> str:
        """Keep an English reply from reaching a citizen.

        Every reply is Bengali: the prompt says so in the strongest terms it
        has, and the model mostly obeys. Where it slips is the farewell --
        "You're welcome. Goodbye." went out to someone who had written
        Bengali throughout. Down a phone line that is worse than on screen,
        because the TTS voice is Bengali and the caller hears it attempting
        English.

        A reply with no Bengali character anywhere is the test. One Bengali
        word is enough to pass, which is what leaves an ordinary answer alone
        -- they carry English inside them all the time, a URL or an
        initialism, and none of that is the model answering in English.
        """
        stripped = (text or "").strip()
        if not stripped or _BENGALI.search(stripped):
            return text
        logger.warning(
            "reply came back with no Bengali, replacing: %r session=%s",
            stripped[:80],
            self.session_id,
        )
        return ENGLISH_SLIP_REPLY

    async def _ask_smart(self, message: str) -> SmartReply | None:
        """Put this turn to the smart API, or None if the hybrid is off."""
        if not smart_client.enabled:
            return None

        reply = await smart_client.ask(message, self.smart_messages, self.session_id)
        logger.info(
            "smart turn session=%s tag=%s source=%s declined=%s",
            self.session_id,
            reply.tag or "-",
            reply.source or "-",
            reply.declined,
        )
        return reply

    def _accept_smart(self, message: str, reply: SmartReply) -> str:
        """Take the smart API's answer as this turn's reply.

        The turn is mirrored into the LLM transcript as an ordinary
        user/assistant exchange. That is what keeps a later fallback coherent:
        the model inherits everything the citizen has already been told, and
        cannot ask again for something answered three turns ago.

        The API's own transcript is kept verbatim -- it is the only thing that
        carries the per-turn tag its follow-up handling reads.
        """
        self.smart_messages = reply.messages or self.smart_messages
        self.history.append({"role": "user", "content": message})
        self.history.append({"role": "assistant", "content": reply.text})
        self.last_source = "smart"
        self.last_tag = reply.tag
        return reply.text

    def _decline_smart(self, reply: SmartReply | None) -> None:
        """Note why a turn is going on to the LLM."""
        if reply is None:
            return
        logger.info(
            "falling back to LLM session=%s reason=%s",
            self.session_id,
            reply.error or reply.tag or "empty reply",
        )

    @staticmethod
    def _smart_events(message: str, reply: SmartReply) -> List[dict]:
        """Render one smart lookup as the stream events the UI already knows.

        `confident` drives the tick or the warning triangle in the browser, so
        it has to mean "this answer is being used", not "the call succeeded" --
        a decline is exactly the not-confident case, and it is what tells the
        viewer why the LLM is now taking over.
        """
        return [
            {
                "type": "tool_call",
                "name": SMART_STEP,
                "arguments": json.dumps({"question": message}, ensure_ascii=False),
            },
            {
                "type": "tool_result",
                "name": SMART_STEP,
                "confident": not reply.declined,
                "best_tag": reply.tag or None,
                "best_score": reply.probability,
                "error": reply.error or None,
            },
        ]

    async def send(self, message: str, params: dict | None = None) -> str:
        """Run one turn and return the assistant's final reply text.

        The smart API gets first refusal; the LLM loop below runs only for a
        turn it declined.
        """
        smart = await self._ask_smart(message)
        if smart is not None and not smart.declined:
            reply_text = self._accept_smart(message, smart)
            await self.save()
            return reply_text

        self._decline_smart(smart)
        self.history.append({"role": "user", "content": message})
        self.last_source = "llm"
        self.last_tag = ""

        reply_text = ""
        for hop in range(settings.MAX_TOOL_HOPS):
            try:
                msg = openai_client.chat_completion(self.history, tools=TOOLS)
            except Exception:
                logger.exception("llama-server call failed session=%s", self.session_id)
                reply_text = FALLBACK_REPLY
                self.history.append({"role": "assistant", "content": reply_text})
                break

            if not msg.tool_calls:
                reply_text = self._clean(msg.content or "")
                self.history.append({"role": "assistant", "content": reply_text})
                break

            self.history.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
                }
            )

            for tool_call in msg.tool_calls:
                try:
                    args = json.loads(tool_call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}

                logger.info(
                    "tool call hop=%d name=%s session=%s",
                    hop + 1,
                    tool_call.function.name,
                    self.session_id,
                )
                result = await run_tool(tool_call.function.name, args, message, params)
                self.history.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
        else:
            logger.warning(
                "hit MAX_TOOL_HOPS=%d without a final reply session=%s",
                settings.MAX_TOOL_HOPS,
                self.session_id,
            )
            reply_text = FALLBACK_REPLY
            self.history.append({"role": "assistant", "content": reply_text})

        await self.save()
        return reply_text

    async def stream(
        self, message: str, params: dict | None = None
    ) -> AsyncIterator[dict]:
        """Run one turn, yielding events as they happen so the caller can push
        them to the browser instead of making the user wait for the whole
        answer.

        A turn the smart API answers yields its lookup as a tool_call /
        tool_result pair, then the answer as a single token event, then done.
        A turn it declines yields the same pair (marked not confident) and then
        the full LLM stream below.

        Event types yielded:
          reasoning    - a chunk of the model's thinking (not part of the reply)
          tool_call    - the model decided to call a tool (name + arguments)
          tool_result  - condensed result of that call
          token        - a chunk of the actual answer text
          done         - final assembled reply
          error        - something failed mid-turn
        """
        smart = await self._ask_smart(message)
        if smart is not None:
            for event in self._smart_events(message, smart):
                yield event

        if smart is not None and not smart.declined:
            reply_text = self._accept_smart(message, smart)
            # The smart API returns a finished answer rather than a stream, so
            # there is nothing to chunk: one token event carries it, and the
            # browser renders it the same way it renders a streamed one.
            yield {"type": "token", "text": reply_text}
            await self.save()
            yield {
                "type": "done",
                "reply": reply_text,
                "source": "smart",
                "tag": self.last_tag,
            }
            return

        self._decline_smart(smart)
        self.history.append({"role": "user", "content": message})
        self.last_source = "llm"
        self.last_tag = ""

        reply_text = ""
        for hop in range(settings.MAX_TOOL_HOPS):
            content_parts: List[str] = []
            pending: Dict[int, dict] = {}
            streamed_any_token = False
            scrubber = StreamScrubber()

            try:
                stream = await openai_client.chat_completion_stream(
                    self.history, tools=TOOLS
                )
                async for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if delta is None:
                        continue

                    reasoning = getattr(delta, "reasoning_content", None)
                    if reasoning:
                        yield {"type": "reasoning", "text": reasoning}

                    if delta.content:
                        content_parts.append(delta.content)
                        safe = scrubber.feed(delta.content)
                        if safe:
                            streamed_any_token = True
                            yield {"type": "token", "text": safe}

                    for tc in delta.tool_calls or []:
                        slot = pending.setdefault(
                            tc.index, {"id": None, "name": "", "arguments": ""}
                        )
                        if tc.id:
                            slot["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                slot["name"] = tc.function.name
                            if tc.function.arguments:
                                slot["arguments"] += tc.function.arguments
            except Exception as exc:
                logger.exception(
                    "llama-server stream failed session=%s", self.session_id
                )
                if streamed_any_token:
                    yield {"type": "error", "message": str(exc)}
                    tail = scrubber.flush()
                    if tail:
                        yield {"type": "token", "text": tail}
                    reply_text = scrubber.emitted
                else:
                    reply_text = FALLBACK_REPLY
                    yield {"type": "token", "text": reply_text}
                self.history.append({"role": "assistant", "content": reply_text})
                break

            if not pending:
                tail = scrubber.flush()
                if tail:
                    yield {"type": "token", "text": tail}
                reply_text = self._in_bengali(
                    self._no_reopening(scrubber.emitted.strip())
                )
                if not reply_text:
                    reply_text = FALLBACK_REPLY
                    yield {"type": "token", "text": reply_text}
                self.history.append({"role": "assistant", "content": reply_text})
                break

            tail = scrubber.flush()
            if tail:
                yield {"type": "token", "text": tail}

            ordered = [pending[i] for i in sorted(pending)]
            self.history.append(
                {
                    "role": "assistant",
                    "content": "".join(content_parts),
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": tc["arguments"],
                            },
                        }
                        for tc in ordered
                    ],
                }
            )

            for tc in ordered:
                logger.info(
                    "tool call hop=%d name=%s session=%s (stream)",
                    hop + 1,
                    tc["name"],
                    self.session_id,
                )
                yield {
                    "type": "tool_call",
                    "name": tc["name"],
                    "arguments": tc["arguments"],
                }

                try:
                    args = json.loads(tc["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}

                result = await run_tool(tc["name"], args, message, params)
                yield {"type": "tool_result", **tool_summary(tc["name"], result)}

                self.history.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
        else:
            logger.warning(
                "hit MAX_TOOL_HOPS=%d without a final reply session=%s (stream)",
                settings.MAX_TOOL_HOPS,
                self.session_id,
            )
            reply_text = FALLBACK_REPLY
            self.history.append({"role": "assistant", "content": reply_text})
            yield {"type": "token", "text": reply_text}

        await self.save()
        yield {"type": "done", "reply": reply_text, "source": "llm", "tag": ""}
