"""
The chat engine.

A Chat instance is one conversation: it holds that session's transcript and
drives a user turn to a final reply, calling tools as the model asks for them.
Load one per request with Chat.load(), which restores the transcript from the
checkpointer.

The prompt text lives in prompt.py and the tool catalogue in tools.py.
"""

import json
import time
from typing import AsyncIterator, Dict, List

from src.chatbot.checkpointer import checkpointer
from src.chatbot.client import openai_client
from src.chatbot.prompt import FALLBACK_REPLY, SYSTEM_PROMPT
from src.chatbot.verify import check_answer
from src.chatbot.tools import TOOLS, run_tool, tool_summary
from src.core.config import chatbot_settings as settings
from src.core.logger import get_logger

logger = get_logger(__name__)


def exact_answer(result: dict) -> str:
    """The reply for a search_faq result: the dataset's best answer, verbatim.

    The model is not asked to compose a final reply. An unconfident match
    already carries the "press 0" answer (see the MCP server), and a failed
    search gets the generic fallback.
    """
    if not isinstance(result, dict) or result.get("error"):
        return FALLBACK_REPLY
    return result.get("best_answer") or FALLBACK_REPLY


class Chat:
    """One conversation, identified by its session id."""

    def __init__(self, session_id: str, history: List[dict]) -> None:
        self.session_id = session_id
        self.history = history
        self.last_tag = ""
        self.ended = False

    @staticmethod
    def new_history() -> List[dict]:
        """A fresh transcript: just the system prompt."""
        return [{"role": "system", "content": SYSTEM_PROMPT}]

    def refresh_prompt(self) -> None:
        """Put the current system prompt at the head of the transcript, so a
        session saved under an older prompt follows today's rules."""
        system = {"role": "system", "content": SYSTEM_PROMPT}
        if self.history and self.history[0].get("role") == "system":
            self.history[0] = system
        else:
            self.history.insert(0, system)

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
        """Keep the system prompt plus the last MAX_HISTORY_TURNS user questions,
        each with everything that followed it (tool calls, results, the reply),
        so the context window doesn't grow unbounded over a long chat.

        A turn is one user question, however many messages it took to answer.
        The window always starts on a user message, so it never cuts between an
        assistant `tool_calls` message and the `tool` results answering it; an
        orphaned `tool` message is rejected by the chat-completions API.
        """
        system_msg, rest = self.history[0], self.history[1:]
        users = [i for i, m in enumerate(rest) if m.get("role") == "user"]
        if len(users) <= settings.MAX_HISTORY_TURNS:
            return
        self.history = [system_msg] + rest[users[-settings.MAX_HISTORY_TURNS]:]

    def recent_user_text(self, turns: int = 3) -> str:
        """The last few things the user said, as context for the answer check."""
        users = [m["content"] for m in self.history if m.get("role") == "user"]
        return "\n".join(users[-turns:])

    async def checked(self, name: str, args: dict, result: dict, message: str) -> dict:
        """Run the answer check on a search result; other tools pass through."""
        if name != "search_faq" or not settings.ANSWER_CHECK:
            return result
        return await check_answer(
            result, args.get("question") or message, self.recent_user_text()
        )

    async def save(self) -> None:
        """Checkpoint the transcript, or end the chat when it has used up its
        MAX_HISTORY_TURNS questions: the stored history is deleted and `ended`
        tells the caller to start the next question as a new session."""
        self.trim()
        asked = sum(1 for m in self.history if m.get("role") == "user")
        if asked >= settings.MAX_HISTORY_TURNS:
            self.ended = True
            await checkpointer.delete(self.session_id)
            return
        await checkpointer.save(self.session_id, self.history)

    async def send(self, message: str, params: dict | None = None) -> str:
        """Run one turn and return the assistant's final reply text."""
        self.history.append({"role": "user", "content": message})

        reply_text = ""
        for hop in range(settings.MAX_TOOL_HOPS):
            exact = None
            try:
                msg = await openai_client.chat_completion(self.history, tools=TOOLS)
            except Exception:
                logger.exception("llama-server call failed session=%s", self.session_id)
                reply_text = FALLBACK_REPLY
                self.history.append({"role": "assistant", "content": reply_text})
                break

            if not msg.tool_calls:
                reply_text = msg.content or ""
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
                result = await self.checked(tool_call.function.name, args, result, message)
                self.history.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                if tool_call.function.name == "search_faq":
                    exact = exact_answer(result)
                    self.last_tag = (result.get("best_tag") or "") if result.get("confident") else ""

            if exact is not None:
                reply_text = exact
                self.history.append({"role": "assistant", "content": reply_text})
                break
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

        timings: Dict[str, float] = {}
        served_tag = ""

        def spent(stage: str, since: float) -> None:
            timings[stage] = timings.get(stage, 0) + (time.perf_counter() - since) * 1000

        reply_text = ""
        for hop in range(settings.MAX_TOOL_HOPS):
            content_parts: List[str] = []
            pending: Dict[int, dict] = {}
            streamed_any_token = False
            exact = None

            llm_started = time.perf_counter()
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
                        streamed_any_token = True
                        yield {"type": "token", "text": delta.content}

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
                spent("llm", llm_started)
                logger.exception(
                    "llama-server stream failed session=%s", self.session_id
                )
                if streamed_any_token:
                    yield {"type": "error", "message": str(exc)}
                    reply_text = "".join(content_parts)
                else:
                    reply_text = FALLBACK_REPLY
                    yield {"type": "token", "text": reply_text}
                self.history.append({"role": "assistant", "content": reply_text})
                break

            spent("llm", llm_started)

            if not pending:
                reply_text = "".join(content_parts)
                self.history.append({"role": "assistant", "content": reply_text})
                break

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

                tool_started = time.perf_counter()
                result = await run_tool(tc["name"], args, message, params)
                spent("search", tool_started)
                check_started = time.perf_counter()
                result = await self.checked(tc["name"], args, result, message)
                spent("check", check_started)
                yield {"type": "tool_result", **tool_summary(tc["name"], result)}

                self.history.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                if tc["name"] == "search_faq":
                    exact = exact_answer(result)
                    # Only an answer the search and the check both stood behind is
                    # worth caching as speech; a decline or a model reply has no tag.
                    served_tag = (result.get("best_tag") or "") if result.get("confident") else ""

            if exact is not None:
                reply_text = exact
                self.history.append({"role": "assistant", "content": reply_text})
                yield {"type": "token", "text": reply_text}
                break
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
        yield {
            "type": "done",
            "reply": reply_text,
            "tag": served_tag,
            "ended": self.ended,
            "timings": {stage: round(ms) for stage, ms in timings.items()},
        }
