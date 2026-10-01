"""EC FAQ MCP server exposing one tool, search_ec_services."""

import requests
from fastmcp import FastMCP

from src.core.config import mcp_settings as settings
from src.core.logger import get_logger
from src.mcp.data_fetch import TAG_ANSWERS, start_refresh_thread

logger = get_logger(__name__)

NOT_FOUND_ANSWER = (
    "দুঃখিত, এই বিষয়ে নির্দিষ্ট উত্তর পাওয়া যায়নি। ০ চেপে সরাসরি আমাদের প্রতিনিধির সাথে কথা বলুন।"
)

MAX_CANDIDATES = 5
RETRIEVAL_DEPTH = 30

mcp = FastMCP(name="ec-conversational-search")


@mcp.tool
def search_ec_services(
    question: str,
    top_k: int = 10,
    min_score: float | None = None,
    min_score_ratio: float = 1.0,
    handle_unknown: bool = True,
    show_candidates: bool = True,
) -> dict:
    """Search the EC NID/voter FAQ and return up to five candidate answers, one per tag.

    Call this for any factual question about NID cards, voter registration,
    corrections, fees or postal voting; not for greetings or small talk. The
    candidates are ranked by text similarity only: pick the one whose
    matched_question means the same as the user's question.
    """
    try:
        response = requests.post(
            settings.TOP_SIMILAR_API_URL,
            json={"question": question, "top_k": max(top_k, RETRIEVAL_DEPTH)},
            timeout=settings.TOP_SIMILAR_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        return {
            "error": f"top_similar API unreachable or errored: {exc}",
            "input_question": question,
        }

    matches = data.get("top_similar", [])
    if not matches:
        return {
            "error": "no matches returned by top_similar API",
            "input_question": data.get("input_question", question),
        }

    seen_tags = set()
    unique_matches = []
    for match in matches:
        tag = match.get("tag")
        if tag and tag not in seen_tags:
            seen_tags.add(tag)
            unique_matches.append(match)

    enriched = [
        {
            "tag": match["tag"],
            "matched_question": match.get("question"),
            "cosine_similarity": match.get("cosine_similarity"),
            "answer": TAG_ANSWERS.get(match["tag"], NOT_FOUND_ANSWER),
        }
        for match in unique_matches
    ]

    top = enriched[0]
    top_score = top.get("cosine_similarity") or 0.0

    threshold = settings.CONFIDENCE_THRESHOLD if min_score is None else min_score

    runner_up = 0.0
    if len(enriched) > 1:
        runner_up = enriched[1].get("cosine_similarity") or 0.0
    clears_margin = top_score >= runner_up * min_score_ratio

    confident = top_score >= threshold and clears_margin

    base = {
        "input_question": data.get("input_question", question),
        "confident": confident,
        "CONFIDENCE_THRESHOLD": threshold,
        "top_tag": top["tag"],
        "top_score": top_score,
    }
    if not confident and handle_unknown:
        return {**base, "answer": NOT_FOUND_ANSWER, "candidates": []}

    candidates = [
        {"rank": rank, **item} for rank, item in enumerate(enriched[:MAX_CANDIDATES], 1)
    ]
    return {
        **base,
        "instruction": (
            "candidates are the closest knowledge-base entries, ranked by text "
            "similarity only -- the top one is not necessarily the right one. "
            "Choose the single candidate whose matched_question means the same "
            "as the user's question (mind distinctions such as present vs "
            "permanent address, or a different country) and answer from that "
            "candidate alone. Do not merge candidates about different topics."
        ),
        "candidates": candidates if show_candidates else candidates[:1],
    }


@mcp.tool
def health() -> dict:
    """Liveness check, including how many answers tag_answer.json loaded."""
    return {"status": "ok", "tag_count": len(TAG_ANSWERS)}


def main() -> None:
    """Run the MCP server over the transport selected by MCP_TRANSPORT."""
    start_refresh_thread()
    if settings.MCP_TRANSPORT == "stdio":
        logger.info("starting MCP server on stdio tags=%d", len(TAG_ANSWERS))
        mcp.run(transport="stdio")
    else:
        logger.info(
            "starting MCP server http://%s:%s%s tags=%d",
            settings.MCP_HOST,
            settings.MCP_PORT,
            settings.MCP_PATH,
            len(TAG_ANSWERS),
        )
        mcp.run(
            transport="http",
            host=settings.MCP_HOST,
            port=settings.MCP_PORT,
            path=settings.MCP_PATH,
        )


if __name__ == "__main__":
    main()
