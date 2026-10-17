"""Answer check: does a retrieved entry really ask what the user asked?

The search scores wrong matches as high as right ones (0.96-0.99), so the score
cannot say "nothing here answers this". After the search the model reads the
user's question against the matched questions and picks the one that means the
same, or none. The reply is still that entry's dataset answer, word for word.
"""

import re
from typing import List, Optional

from src.chatbot.client import openai_client
from src.core.config import chatbot_settings as settings
from src.core.replies import NO_INFO_REPLY
from src.core.logger import get_logger

logger = get_logger(__name__)

MAX_CANDIDATES = 8

PROMPT = (
    "ব্যবহারকারীর প্রশ্ন: {question}\n\n"
    "তথ্যভান্ডারের সংরক্ষিত প্রশ্ন, সার্চের মিল অনুযায়ী সাজানো:\n{options}\n\n"
    "কোন সংরক্ষিত প্রশ্নটি ব্যবহারকারীর প্রশ্নের একই বিষয় ও একই বিবরণ (দেশ, শহর, বয়স, "
    "সংখ্যা) নিয়ে? শুধু শব্দ বা নামের কিছুটা মিল থাকলেই হবে না; বিষয় বা বিবরণ আলাদা হলে "
    "মেলে না। বানান ভুল, ভিন্ন বানান বা উচ্চারণ অনুযায়ী লেখা শব্দ এবং বাড়তি কথা (যেমন অনুযোগ বা "
    "সম্বোধন) উপেক্ষা করবে, অর্থ দেখবে। ১ নম্বর ঠিক মিললে সেটিই নাও।\n"
    "শুধু একটি সংখ্যা লিখুন। কোনোটিই না মিললে ০ লিখুন।"
)

BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")


def candidates(result: dict) -> List[dict]:
    """The best match, then the alternatives, as {tag, question, answer, score}."""
    best = {
        "tag": result.get("best_tag"),
        "question": result.get("best_question"),
        "answer": result.get("best_answer"),
        "score": result.get("best_score"),
    }
    others = [
        {
            "tag": alt.get("tag"),
            "question": alt.get("matched_question"),
            "answer": alt.get("answer"),
            "score": alt.get("cosine_similarity"),
        }
        for alt in result.get("alternatives") or []
    ]
    found = [c for c in [best, *others] if c["tag"] and c["question"]]
    return found[:MAX_CANDIDATES]


def parse_choice(reply: str, limit: int) -> Optional[int]:
    """The number the model chose (0 for none), or None if it gave no usable one."""
    match = re.search(r"\d+", (reply or "").translate(BN_DIGITS))
    if not match:
        return None
    choice = int(match.group())
    return choice if choice <= limit else None


async def check_answer(result: dict, question: str) -> dict:
    """The search result with its answer swapped for the entry the model picked.

    If the model picks none, the reply becomes NO_INFO_REPLY and `confident` is
    false. If the check cannot run, the search's own answer stands.
    """
    if not settings.ANSWER_CHECK or not isinstance(result, dict) or result.get("error"):
        return result
    found = candidates(result)
    if not found:
        return result

    options = "\n".join(f"{i}. {c['question']}" for i, c in enumerate(found, 1))
    try:
        response = await openai_client.async_client.chat.completions.create(
            model=openai_client.model,
            messages=[
                {"role": "user", "content": PROMPT.format(question=question, options=options)}
            ],
            temperature=0,
            max_tokens=8,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        choice = parse_choice(response.choices[0].message.content, len(found))
    except Exception:
        logger.exception("answer check failed; keeping the search's best answer")
        return result
    if choice is None:
        return result

    if choice == 0:
        logger.info("answer check: no match for %r", question)
        return {**result, "confident": False, "best_answer": NO_INFO_REPLY}

    picked = found[choice - 1]
    return {
        **result,
        "best_tag": picked["tag"],
        "best_answer": picked["answer"],
        "best_score": picked["score"],
    }
