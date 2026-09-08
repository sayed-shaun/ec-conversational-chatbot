"""Punctuation the voice can and cannot say.

A comma earns its place, as the voice pauses on it, and so does a daṛi. The
rest is either read aloud as a word or swallowed as a glitch, so it goes.

Two marks need judgement rather than deletion. A slash carries meaning --
"উপজেলা/থানা" means "or" -- and becomes that word. A hyphen is kept when it
joins a compound such as রি-ইস্যু and removed when a space on one side shows
it was left behind by a dropped English word.
"""

import re

from src.speech.transform.common import collapse_space

_SLASH_BETWEEN_WORDS = re.compile(r"(?<=\S)\s*/\s*(?=\S)")

_ORPHAN_HYPHEN = re.compile(r"\s+-+|-+\s+")

_UNSPEAKABLE = re.compile(r"[()\[\]{}\"'“”‘’:;|<>+=*_~^\\@#$%&]")


def punctuation_for_speech(text: str) -> str:
    text = _SLASH_BETWEEN_WORDS.sub(" বা ", text)
    text = _ORPHAN_HYPHEN.sub(" ", text)
    text = _UNSPEAKABLE.sub(" ", text)
    text = re.sub(r"\s+([।,?!])", r"\1", text)
    text = re.sub(r"([।,?!])\1+", r"\1", text)
    return collapse_space(text)
