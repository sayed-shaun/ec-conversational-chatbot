"""
EC FAQ MCP Server (built with FastMCP: https://github.com/jlowin/fastmcp)
--------------------------------------------------------------------------
Exposes a single MCP tool, `search_faq`, that:

  1. Sends the user's question to the external top-k embedding-search API
     (TOPK_API, e.g. http://<host>:8888/api/v1/topk). It returns the nearest
     FAQ questions, each with its `tag`, `cosine_similarity` and the tag's
     canonical Bengali `answer`.
  2. De-duplicates results by `tag` (keeping the highest-ranked hit per tag)
     and leaves out tags the API has no answer for.
  3. Returns a compact, ready-to-use payload: the single best answer plus a
     list of alternatives, so the calling LLM doesn't have to guess.

Served over Streamable HTTP at `/mcp` so it's reachable from other
containers (e.g. the chatbot service) as well as from any MCP client
(Claude Desktop, Claude Code, Cursor, etc.) that supports HTTP transport.
For local stdio use instead, set MCP_TRANSPORT=stdio.

All configuration lives in src/core/config.py (Settings, pydantic-settings) —
see that file for every available environment variable.
"""

import requests
from fastmcp import FastMCP

from src.core.config import mcp_settings as settings
from src.core.logger import get_logger

logger = get_logger(__name__)

NOT_FOUND_ANSWER = (
    "দুঃখিত, এই বিষয়ে নির্দিষ্ট উত্তর পাওয়া যায়নি। " "০ চেপে সরাসরি আমাদের প্রতিনিধির সাথে কথা বলুন।"
)

mcp = FastMCP(name="ec-faq-search")


@mcp.tool
def search_faq(
    question: str,
    top_k: int = 30,
    min_score: float | None = None,
    min_score_ratio: float = 1.0,
    handle_unknown: bool = True,
    show_candidates: bool = True,
) -> dict:
    """Search the EC (Bangladesh Election Commission) NID/voter FAQ knowledge
    base for the closest matching question(s) to a user's query, and resolve
    each match to its canonical Bengali answer.

    Always call this for factual questions about NID cards, voter
    registration, corrections, fees, postal ballots, etc. Do not call it for
    plain greetings or small talk.

    Args:
        question: The user's raw question, in Bengali or English.
        top_k: How many nearest-neighbour candidates to retrieve (default 30).
        min_score: Minimum cosine similarity for the best match to count as
            reliable. Overrides settings.CONFIDENCE_THRESHOLD for this call.
        min_score_ratio: Required margin between the best and second-best
            match: the best must score at least `second_best * ratio` to be
            treated as confident. 1.0 (the default) demands no margin.
        handle_unknown: When the best match is not confident, replace the
            answer with an explicit "I don't know, press 0" instead of
            returning a probably-wrong answer.
        show_candidates: Include the `alternatives` list in the result.

    Returns:
        A dict containing:
          - input_question: the original question
          - confident: bool, whether the best match cleared min_score and
                       the min_score_ratio margin
          - best_tag / best_answer / best_score: the top unique match
          - alternatives: list of other unique {tag, answer, cosine_similarity}
                          found within the top_k results (empty when
                          show_candidates is false)
    """
    try:
        response = requests.post(
            settings.TOPK_API,
            json={"question": question, "top_k": settings.TOPK_ROWS},
            timeout=settings.TOPK_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        return {
            "error": f"top-k API unreachable or errored: {exc}",
            "input_question": question,
        }

    matches = data.get("top_similar", [])
    if not matches:
        return {
            "error": "no matches returned by the top-k API",
            "input_question": data.get("input_question", question),
        }

    # One entry per tag, best-ranked first. The answer comes with the rows; a tag's
    # rows can disagree on whether it has one, so take the first row that does.
    # A tag with no answer anywhere cannot be served and is left out.
    by_tag: dict = {}
    for match in matches:
        tag = match.get("tag")
        if not tag:
            continue
        entry = by_tag.setdefault(
            tag,
            {
                "tag": tag,
                "matched_question": match.get("question"),
                "cosine_similarity": match.get("cosine_similarity"),
                "answer": None,
            },
        )
        if not entry["answer"] and match.get("answer"):
            entry["answer"] = match["answer"]
    enriched = [e for e in by_tag.values() if e["answer"]][:top_k]
    skipped = len(by_tag) - len([e for e in by_tag.values() if e["answer"]])
    if skipped:
        logger.info("skipped %d tag(s) the API has no answer for", skipped)
    if not enriched:
        return {
            "error": "the top-k API returned no tag with an answer",
            "input_question": data.get("input_question", question),
        }

    best = enriched[0]
    best_score = best.get("cosine_similarity") or 0.0

    threshold = settings.CONFIDENCE_THRESHOLD if min_score is None else min_score

    runner_up = 0.0
    if len(enriched) > 1:
        runner_up = enriched[1].get("cosine_similarity") or 0.0
    clears_margin = best_score >= runner_up * min_score_ratio

    confident = best_score >= threshold and clears_margin

    best_answer = best["answer"]
    if not confident and handle_unknown:
        best_answer = NOT_FOUND_ANSWER

    return {
        "input_question": data.get("input_question", question),
        "confident": confident,
        "CONFIDENCE_THRESHOLD": threshold,
        "min_score_ratio": min_score_ratio,
        "runner_up_score": runner_up,
        "best_tag": best["tag"],
        "best_question": best.get("matched_question"),
        "best_answer": best_answer,
        "best_score": best_score,
        "alternatives": enriched[1:] if show_candidates else [],
    }


@mcp.tool
def health() -> dict:
    """Basic liveness check for this MCP server."""
    return {"status": "ok"}


def main() -> None:
    """Run the MCP server over the transport selected by MCP_TRANSPORT."""
    if settings.MCP_TRANSPORT == "stdio":
        logger.info("starting MCP server on stdio")
        mcp.run(transport="stdio")
    else:
        logger.info(
            "starting MCP server http://%s:%s%s",
            settings.MCP_HOST,
            settings.MCP_PORT,
            settings.MCP_PATH,
        )
        mcp.run(
            transport="http",
            host=settings.MCP_HOST,
            port=settings.MCP_PORT,
            path=settings.MCP_PATH,
        )


if __name__ == "__main__":
    main()
