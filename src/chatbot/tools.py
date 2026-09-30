"""
The tool catalogue: what the model may call, how each call is executed, and
how its result is condensed for the live UI.

The schema here is what gets sent to llama-server in every chat-completion
request. Execution goes through the MCP client, so this module is the seam
between "the model asked for something" and "the MCP server did it".
"""

from src.chatbot.client import mcp_client
from src.core.logger import get_logger

logger = get_logger(__name__)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_ec_services",
            "description": (
                "Search the EC NID/voter FAQ knowledge base for the closest "
                "matching question(s) and return the canonical answer plus "
                "alternatives. Use this for any factual question about NID "
                "cards, voter registration, corrections, fees, postal "
                "ballots, etc. Do not use it for greetings or small talk."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": (
                            "The user's question, verbatim or lightly cleaned up."
                        ),
                    },
                    "top_k": {
                        "type": "integer",
                        "description": (
                            "How many nearest-neighbour candidates to fetch."
                        ),
                        "default": 10,
                    },
                },
                "required": ["question"],
            },
        },
    }
]


def _has_bengali(text: str) -> bool:
    return any("\u0980" <= ch <= "\u09ff" for ch in text or "")


async def run_tool(
    name: str, args: dict, fallback_question: str, params: dict | None = None
) -> dict:
    """Execute one tool call. `params` holds the UI's retrieval overrides,
    which win over whatever top_k the model happened to ask for."""
    if name == "search_ec_services":
        question = args.get("question") or fallback_question
        # The model sometimes translates a Bangla question into English before
        # searching, and the FAQ model handles English badly (it can return a
        # confident but unrelated tag). Rewrites that stay in Bangla are kept,
        # since they carry context from earlier turns.
        if _has_bengali(fallback_question) and not _has_bengali(question):
            logger.warning("model translated the search query; using the user's text")
            question = fallback_question
        overrides = dict(params or {})
        # The model sometimes asks for top_k=1, which leaves the search
        # nothing to rank; never let it go below the default depth.
        top_k = overrides.pop("top_k", None) or max(args.get("top_k") or 10, 10)
        return await mcp_client.search_ec_services(
            question, top_k, **overrides
        )
    logger.warning("model requested unknown tool: %s", name)
    return {"error": f"unknown tool: {name}"}


def tool_summary(name: str, result: dict) -> dict:
    """Condense a tool result into something small enough to show live in the
    UI without dumping the whole Bengali answer into a status line."""
    if not isinstance(result, dict):
        return {"name": name}
    if result.get("error"):
        return {"name": name, "error": result["error"]}

    alts = result.get("alternatives") or []
    return {
        "name": name,
        "confident": result.get("confident"),
        "best_tag": result.get("best_tag"),
        "best_score": result.get("best_score"),
        "threshold": result.get("confidence_threshold"),
        "alternatives": len(alts),
        "candidates": [
            {"tag": a.get("tag"), "score": a.get("cosine_similarity")} for a in alts[:5]
        ],
    }
