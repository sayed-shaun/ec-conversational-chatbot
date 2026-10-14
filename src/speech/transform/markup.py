"""Markdown out, so the voice does not read asterisks and hashes aloud."""

import re

from src.speech.transform.common import collapse_space

CODE_FENCE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE = re.compile(r"`([^`]+)`")
IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
MARKS = re.compile(r"[#*_>~]")


def strip_markdown(text: str) -> str:
    """Remove markdown so the voice does not read asterisks and hashes."""
    plain = CODE_FENCE.sub(" ", text)
    plain = INLINE_CODE.sub(r"\1", plain)
    plain = IMAGE.sub(" ", plain)
    plain = LINK.sub(r"\1", plain)
    plain = MARKS.sub("", plain)
    return collapse_space(plain)
