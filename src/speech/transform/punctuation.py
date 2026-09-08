"""Punctuation the voice can and cannot say.

A comma earns its place: the voice pauses on it, and so does a daṛi. The rest
is either read out as a word or swallowed as a glitch, so it goes.
"""

import re

from src.speech.transform.common import collapse_space

# The slash is the one that changes meaning: "উপজেলা/থানা" means "or", and that
# is how it should sound.
_SLASH_BETWEEN_WORDS = re.compile(r"(?<=\S)\s*/\s*(?=\S)")

# A hyphen with a space on one side is left over from a dropped English word
# ("Al-Sadu Street" losing "Sadu"). A hyphen with no space around it is part of
# a Bengali compound -- রি-ইস্যু -- and must survive.
_ORPHAN_HYPHEN = re.compile(r"\s+-+|-+\s+")

_UNSPEAKABLE = re.compile(r"[()\[\]{}\"'“”‘’:;|<>+=*_~^\\@#$%&]")


def punctuation_for_speech(text: str) -> str:
    text = _SLASH_BETWEEN_WORDS.sub(" বা ", text)
    text = _ORPHAN_HYPHEN.sub(" ", text)
    text = _UNSPEAKABLE.sub(" ", text)
    # A sentence that lost its only content leaves a dangling daṛi behind.
    text = re.sub(r"\s+([।,?!])", r"\1", text)
    text = re.sub(r"([।,?!])\1+", r"\1", text)
    return collapse_space(text)
