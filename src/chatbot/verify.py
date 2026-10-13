"""Answer check: does a retrieved entry really ask what the user asked?

The search scores every match 0.96-0.99, wrong ones included, so the score cannot
say "nothing here answers this". "রোমানিয়া কি দূতাবাস আছে" came back as the Rome
entry, and "মিয়ামি" as Malaysia. After the search the model reads the user's
question against the matched questions and picks the one that means the same, or
none. The reply is then that entry's dataset answer, word for word; the model
never writes it.
"""

import re
from typing import List, Optional

from src.chatbot.client import openai_client
from src.core.config import chatbot_settings as settings
from src.core.logger import get_logger

logger = get_logger(__name__)

NO_MATCH_REPLY = (
    "দুঃখিত, এই বিষয়ে নির্দিষ্ট উত্তর আমার কাছে নেই। অনুগ্রহ করে ০ চেপে "
    "সরাসরি আমাদের প্রতিনিধির সাথে কথা বলুন।"
)

_PROMPT = (
    "ব্যবহারকারীর সাম্প্রতিক কথা:\n{context}\n\n"
    "ব্যবহারকারীর পূর্ণ প্রশ্ন: {question}\n\n"
    "নিচে তথ্যভান্ডারের কয়েকটি সংরক্ষিত প্রশ্ন ও তাদের উত্তরের শুরু। মনোযোগ দিয়ে পড়ে ঠিক কোনটি "
    "ব্যবহারকারীর প্রশ্নের উত্তর দেয় বেছে নাও।\n"
    "- ব্যবহারকারীর পরিস্থিতি মিলতে হবে: বিষয়, সেবার নাম, দেশে না বিদেশে, বয়স, কোন ধাপে আছেন "
    "(আবেদনের আগে না পরে)।\n"
    "- দেশ, শহর, সংখ্যা বা বিষয় আলাদা হলে মেলে না; শুধু শব্দ বা নামের কিছুটা মিল থাকলেই হবে না।\n"
    "- ব্যবহারকারী যা বলেননি তা ধরে নেবে না। আগের কথা শুধু বুঝতে সাহায্য করবে, নতুন তথ্য "
    "যোগ করবে না।\n"
    "- একাধিক মিললে যেটি বেশি নির্দিষ্টভাবে মেলে সেটি নাও।\n\n"
    "{options}\n\n"
    "শুধু একটি সংখ্যা লিখুন। কোনোটিই ঠিক না মিললে ০ লিখুন।"
)


_DECLINE_PROMPT = (
    "তুমি বাংলাদেশ নির্বাচন কমিশনের এনআইডি ও ভোটার সেবার সহকারী। ব্যবহারকারীর প্রশ্নের সরাসরি "
    "উত্তর আমাদের তথ্যভান্ডারে নেই। নিচের প্রশ্নগুলো সবচেয়ে কাছের, কিন্তু সেগুলো ব্যবহারকারীর "
    "প্রশ্নের উত্তর নয়।\n\nব্যবহারকারীর সাম্প্রতিক কথা:\n{context}\n\n"
    "ব্যবহারকারীর প্রশ্ন: {question}\n\nকাছের প্রশ্ন:\n{options}\n\n"
    "এক-দুই বাক্যে স্বাভাবিক বাংলায় বলো যে ব্যবহারকারী যে নির্দিষ্ট বিষয়, দেশ বা শহরের কথা "
    "জিজ্ঞাসা করেছেন (নাম উল্লেখ করে) সে সম্পর্কে আমাদের কাছে তথ্য নেই। তথ্যভান্ডারে স্পষ্ট "
    "না থাকলে \"নেই\" বা \"হয় না\" বলে কিছু নিশ্চিত করবে না, শুধু বলবে তথ্য নেই। শেষে "
    "০ চেপে সরাসরি আমাদের প্রতিনিধির সাথে কথা বলতে বলো। কাছের প্রশ্নের উত্তর বানিয়ে বলবে না।"
)

_BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")


def _candidates(result: dict) -> List[dict]:
    """Best match first, then the alternatives, each with its question and answer."""
    best = {
        "tag": result.get("best_tag"),
        "question": result.get("best_question"),
        "answer": result.get("best_answer"),
        "score": result.get("best_score"),
    }
    rest = [
        {
            "tag": alt.get("tag"),
            "question": alt.get("matched_question"),
            "answer": alt.get("answer"),
            "score": alt.get("cosine_similarity"),
        }
        for alt in result.get("alternatives") or []
    ]
    found = [c for c in [best, *rest] if c["tag"] and c["question"]]
    return found[: settings.ANSWER_CHECK_CANDIDATES]


def _start(answer: Optional[str], limit: int = 140) -> str:
    """The first part of an answer on one line, enough to tell what it is about."""
    text = " ".join((answer or "").split())
    return text[:limit] + ("…" if len(text) > limit else "")


def _parse(reply: str, limit: int) -> Optional[int]:
    """The chosen number, 0 for none, or None when the reply holds no number."""
    match = re.search(r"\d+", (reply or "").translate(_BN_DIGITS))
    if not match:
        return None
    number = int(match.group())
    return number if 0 <= number <= limit else None


async def _decline_reply(question: str, context: str, candidates: List[dict]) -> str:
    """A short, natural no-information reply that names what the user asked about.

    Falls back to the fixed sorry if the model gives nothing usable.
    """
    options = "\n".join(f"- {c['question']}" for c in candidates[:3])
    prompt = _DECLINE_PROMPT.format(
        context=context or question, question=question, options=options
    )
    try:
        response = await openai_client.async_client.chat.completions.create(
            model=openai_client.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=160,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        text = (response.choices[0].message.content or "").strip()
    except Exception:
        logger.exception("decline reply failed; using the fixed sorry")
        return NO_MATCH_REPLY
    return text or NO_MATCH_REPLY


async def check_answer(result: dict, question: str, context: str) -> dict:
    """The search result with its answer swapped for the entry the model picked.

    When the model picks none, the reply becomes a sorry and `confident` is false.
    If the check cannot run (model error, no usable reply) the search's own best
    answer stands, so a failing check never takes the bot down.
    """
    if not isinstance(result, dict) or result.get("error"):
        return result
    candidates = _candidates(result)
    if len(candidates) < 1:
        return result

    options = "\n".join(
        f"{i}. প্রশ্ন: {c['question']}\n   উত্তরের শুরু: {_start(c['answer'])}"
        for i, c in enumerate(candidates, 1)
    )
    prompt = _PROMPT.format(
        context=context or question, question=question, options=options
    )
    try:
        response = await openai_client.async_client.chat.completions.create(
            model=openai_client.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=8,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        choice = _parse(response.choices[0].message.content, len(candidates))
    except Exception:
        logger.exception("answer check failed; keeping the search's best answer")
        return result
    if choice is None:
        logger.warning("answer check gave no usable number; keeping the best answer")
        return result

    if choice == 0:
        logger.info("answer check: no candidate matches %r", question)
        return {
            **result,
            "confident": False,
            "best_answer": await _decline_reply(question, context, candidates),
            "check": "none",
        }

    picked = candidates[choice - 1]
    if choice != 1:
        logger.info(
            "answer check: picked #%d %s over %s",
            choice,
            picked["tag"],
            candidates[0]["tag"],
        )
    return {
        **result,
        "best_tag": picked["tag"],
        "best_answer": picked["answer"],
        "best_score": picked["score"],
        "check": choice,
    }
