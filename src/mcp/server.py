"""
EC FAQ MCP Server (built with FastMCP: https://github.com/jlowin/fastmcp)
--------------------------------------------------------------------------
Exposes a single MCP tool, `search_faq`, that:

  1. Sends the user's question to the `top_similar` embedding-search API
     (self-hosted by the ec-conversational-vector/pgvector service by
     default -- see TOP_SIMILAR_API_URL) and gets back the top_k nearest
     questions with their `tag` and `cosine_similarity`.
  2. De-duplicates results by `tag` (keeping the highest-ranked hit per tag).
  3. Looks up the canonical Bengali answer for each unique tag in
     `tag_answer.json`.
  4. Returns a compact, ready-to-use payload: the single best answer plus a
     list of alternatives, so the calling LLM doesn't have to guess.

Served over Streamable HTTP at `/mcp` so it's reachable from other
containers (e.g. the chatbot service) as well as from any MCP client
(Claude Desktop, Claude Code, Cursor, etc.) that supports HTTP transport.
For local stdio use instead, set MCP_TRANSPORT=stdio.

The knowledge base is fetched live from GitHub at startup and optionally
kept fresh on an interval (see data_fetch.py: TAG_ANSWER_URL, GITHUB_TOKEN,
TAG_ANSWER_REFRESH_SECONDS), falling back to the bundled tag_answer.json
if the live fetch fails.

All configuration lives in src/core/config.py (Settings, pydantic-settings) —
see that file for every available environment variable.
"""

import requests
from fastmcp import FastMCP

from src.core.config import mcp_settings as settings
from src.core.logger import get_logger
from src.mcp.data_fetch import TAG_ANSWERS, start_refresh_thread

logger = get_logger(__name__)

NOT_FOUND_ANSWER = (
    "দুঃখিত, এই বিষয়ে নির্দিষ্ট উত্তর পাওয়া যায়নি। " "১০৫-এ কল করে সরাসরি প্রতিনিধির সাথে কথা বলুন।"
)

mcp = FastMCP(name="ec-faq-search")


@mcp.tool
def search_faq(
    question: str,
    top_k: int = 10,
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
        top_k: How many nearest-neighbour candidates to retrieve (default 10).
        min_score: Minimum cosine similarity for the best match to count as
            reliable. Overrides settings.CONFIDENCE_THRESHOLD for this call.
        min_score_ratio: Required margin between the best and second-best
            match: the best must score at least `second_best * ratio` to be
            treated as confident. 1.0 (the default) demands no margin.
        handle_unknown: When the best match is not confident, replace the
            answer with an explicit "I don't know, call 105" instead of
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
            settings.TOP_SIMILAR_API_URL,
            json={"question": question, "top_k": top_k},
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
        "confidence_threshold": threshold,
        "min_score_ratio": min_score_ratio,
        "runner_up_score": runner_up,
        "best_tag": best["tag"],
        "best_answer": best_answer,
        "best_score": best_score,
        "alternatives": enriched[1:] if show_candidates else [],
    }


@mcp.tool
def health() -> dict:
    """Basic liveness check for this MCP server, including whether
    tag_answer.json loaded correctly."""
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
