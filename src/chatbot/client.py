"""Clients for llama-server (OpenAI API) and the EC FAQ MCP server."""

from typing import Any, Dict, List, Optional

from fastmcp import Client
from openai import AsyncOpenAI

from src.core.config import chatbot_settings as settings
from src.core.logger import get_logger

logger = get_logger(__name__)


class OpenAIClient:
    """Chat completions against llama-server."""

    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url
        self.model = model
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
        if settings.LLAMA_REASONING_EFFORT:
            kwargs["reasoning_effort"] = settings.LLAMA_REASONING_EFFORT
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice
        return kwargs

    async def chat_completion_stream(
        self,
        messages: List[dict],
        tools: Optional[List[dict]] = None,
        tool_choice: str = "auto",
    ) -> Any:
        """Open a streaming chat completion and return the async chunk iterator."""
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
    """Calls tools on the EC FAQ MCP server."""

    def __init__(self, server_url: str) -> None:
        self.server_url = server_url

    async def call_tool(self, name: str, arguments: dict) -> dict:
        """Invoke one MCP tool; failures come back as {"error": ...}."""
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

    async def search_ec_services(self, question: str, top_k: int = 10, **overrides) -> dict:
        """Search the FAQ knowledge base via the MCP `search_ec_services` tool."""
        arguments = {"question": question, "top_k": top_k}
        arguments.update({k: v for k, v in overrides.items() if v is not None})
        return await self.call_tool("search_ec_services", arguments)


openai_client = OpenAIClient(settings.LLAMA_BASE_URL, settings.LLAMA_MODEL)
mcp_client = McpClient(settings.MCP_SERVER_URL)
