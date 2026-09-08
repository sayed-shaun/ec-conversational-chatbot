"""
The chat engine.

A Chat instance is one conversation: it holds that session's transcript and
drives a user turn to a final reply, calling tools as the model asks for them.
Load one per request with Chat.load(), which restores the transcript from the
checkpointer.

The prompt text lives in prompt.py and the tool catalogue in tools.py.
"""

import json
from typing import AsyncIterator, Dict, List

from src.chatbot.checkpointer import checkpointer
from src.chatbot.client import openai_client
from src.chatbot.prompt import FALLBACK_REPLY, SYSTEM_PROMPT
from src.chatbot.sanitize import StreamScrubber, scrub
from src.chatbot.tools import TOOLS, run_tool, tool_summary
from src.core.config import chatbot_settings as settings
from src.core.logger import get_logger

logger = get_logger(__name__)


class Chat:
    """One conversation, identified by its session id."""

    def __init__(self, session_id: str, history: List[dict]) -> None:
        self.session_id = session_id
        self.history = history

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
        history = await checkpointer.load(session_id)
        chat = cls(session_id, history or cls.new_history())
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
        """Trim and checkpoint the transcript."""
        self.trim()
        await checkpointer.save(self.session_id, self.history)

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
        return cleaned or FALLBACK_REPLY

    async def send(self, message: str, params: dict | None = None) -> str:
        """Run one turn and return the assistant's final reply text."""
        self.history.append({"role": "user", "content": message})

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

        Event types yielded:
          reasoning    - a chunk of the model's thinking (not part of the reply)
          tool_call    - the model decided to call a tool (name + arguments)
          tool_result  - condensed result of that call
          token        - a chunk of the actual answer text
          done         - final assembled reply
          error        - something failed mid-turn
        """
        self.history.append({"role": "user", "content": message})

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
                reply_text = scrubber.emitted.strip()
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
        yield {"type": "done", "reply": reply_text}
