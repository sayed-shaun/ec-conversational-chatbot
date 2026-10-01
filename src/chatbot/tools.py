"""Tools the model may call, how each call runs, and its summary for the UI."""

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


async def run_tool(
    name: str, args: dict, fallback_question: str, params: dict | None = None
) -> dict:
    """Execute one tool call."""
    if name == "search_ec_services":
        overrides = dict(params or {})
        top_k = overrides.pop("top_k", None) or args.get("top_k", 10)
        return await mcp_client.search_ec_services(
            args.get("question", fallback_question), top_k, **overrides
        )
    logger.warning("model requested unknown tool: %s", name)
    return {"error": f"unknown tool: {name}"}


def tool_summary(name: str, result: dict) -> dict:
    """Condense a tool result for the live UI."""
    if not isinstance(result, dict):
        return {"name": name}
    if result.get("error"):
        return {"name": name, "error": result["error"]}

    cands = result.get("candidates") or []
    return {
        "name": name,
        "confident": result.get("confident"),
        "best_tag": result.get("top_tag"),
        "best_score": result.get("top_score"),
        "threshold": result.get("CONFIDENCE_THRESHOLD"),
        "alternatives": max(len(cands) - 1, 0),
        "candidates": [
            {"tag": c.get("tag"), "score": c.get("cosine_similarity")}
            for c in cands[:5]
        ],
    }
