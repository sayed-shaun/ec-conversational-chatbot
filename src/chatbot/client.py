"""
Outbound clients.

Two things this service talks to, one class each:

- `OpenAIClient` — the `openai` SDK pointed at llama-server's
  OpenAI-compatible /v1 endpoint, for both one-shot and streaming
  completions.
- `McpClient` — the EC FAQ MCP server (Streamable HTTP, FastMCP), for the
  `search_faq` tool.

Module-level `openai_client` and `mcp_client` instances are built from
settings at import, so callers just use them.
"""

from typing import Any, Dict, List, Optional

from fastmcp import Client
from openai import AsyncOpenAI, OpenAI

from src.core.config import chatbot_settings as settings
from src.core.logger import get_logger

logger = get_logger(__name__)


class OpenAIClient:
    """Chat completions against llama-server.

    Holds a sync client for one-shot calls and an async client for streaming.
    Streaming has to be async: iterating a sync stream would block the event
    loop and stall every other request the server is handling.
    """

    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url
        self.model = model
        self.client = OpenAI(base_url=base_url, api_key="not-needed")
        self.async_client = AsyncOpenAI(base_url=base_url, api_key="not-needed")

    def _kwargs(
        self,
        messages: List[dict],
        tools: Optional[List[dict]],
        tool_choice: str,
        stream: bool,
    ) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }
        if stream:
            kwargs["stream"] = True
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice
        return kwargs

    def chat_completion(
        self,
        messages: List[dict],
        tools: Optional[List[dict]] = None,
        tool_choice: str = "auto",
    ) -> Any:
        """Send one chat-completion request and return the assistant message.

        Raises whatever the SDK raises; callers decide how to degrade.
        """
        logger.debug(
            "chat completion model=%s messages=%d tools=%d",
            self.model,
            len(messages),
            len(tools or []),
        )
        completion = self.client.chat.completions.create(
            **self._kwargs(messages, tools, tool_choice, stream=False)
        )
        return completion.choices[0].message

    async def chat_completion_stream(
        self,
        messages: List[dict],
        tools: Optional[List[dict]] = None,
        tool_choice: str = "auto",
    ) -> Any:
        """Open a streaming chat completion and return the async chunk iterator.

        Chunk deltas carry three interesting fields, and llama-server may send
        any combination of them: `reasoning_content` (the model thinking out
        loud), `content` (the actual answer), and `tool_calls` (streamed
        incrementally -- id and name arrive first, then argument fragments).
        """
        logger.debug(
            "stream completion model=%s messages=%d tools=%d",
            self.model,
            len(messages),
            len(tools or []),
        )
        return await self.async_client.chat.completions.create(
            **self._kwargs(messages, tools, tool_choice, stream=True)
        )


class McpClient:
    """Calls tools on the EC FAQ MCP server.

    A fresh session per call is simple and robust for a low/medium traffic FAQ
    bot; swap for a persistent client if you need lower latency at higher
    volume.
    """

    def __init__(self, server_url: str) -> None:
        self.server_url = server_url

    async def call_tool(self, name: str, arguments: dict) -> dict:
        """Invoke one MCP tool. Never raises: failures come back as
        `{"error": ...}` so the LLM can see what went wrong and say so."""
        try:
            async with Client(self.server_url) as client:
                result = await client.call_tool(name, arguments)
                if result.data is not None:
                    return result.data
                logger.warning("empty tool result from MCP server")
                return {"error": "empty tool result from MCP server"}
        except Exception as exc:
            logger.exception("MCP server call failed")
            return {"error": f"could not reach MCP server: {exc}"}

    async def search_faq(self, question: str, top_k: int = 10, **overrides) -> dict:
        """Search the FAQ knowledge base via the MCP `search_faq` tool."""
        arguments = {"question": question, "top_k": top_k}
        arguments.update({k: v for k, v in overrides.items() if v is not None})
        return await self.call_tool("search_faq", arguments)


openai_client = OpenAIClient(settings.llama_base_url, settings.llama_model)
mcp_client = McpClient(settings.mcp_server_url)
