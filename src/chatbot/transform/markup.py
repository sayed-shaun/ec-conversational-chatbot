"""Markdown out, so the voice does not read asterisks and hashes aloud."""

import re

from src.chatbot.transform.common import collapse_space

_CODE_FENCE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`]+)`")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_MARKS = re.compile(r"[#*_>~]")


def strip_markdown(text: str) -> str:
    """Remove markdown so the voice does not read asterisks and hashes."""
    plain = _CODE_FENCE.sub(" ", text)
    plain = _INLINE_CODE.sub(r"\1", plain)
    plain = _IMAGE.sub(" ", plain)
    plain = _LINK.sub(r"\1", plain)
    plain = _MARKS.sub("", plain)
    return collapse_space(plain)
