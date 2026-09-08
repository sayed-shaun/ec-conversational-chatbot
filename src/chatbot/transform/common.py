"""Helpers the other speech stages share.

Small on purpose. Anything used by exactly one stage lives in that stage's
module instead, so each file can be read on its own.
"""

import re

# Presence of Bengali, not majority: "Google Play Store থেকে NID Wallet অ্যাপ"
# has more Latin letters than Bengali and is still a Bengali sentence.
_BENGALI = re.compile(r"[ঀ-৿]")

# Sentence terminators, the Bengali daṛi included.
SENTENCE_SPLIT = re.compile(r"(?<=[।.!?])")

_SPACE = re.compile(r"\s+")


def has_bengali(text: str) -> bool:
    return bool(_BENGALI.search(text or ""))


def collapse_space(text: str) -> str:
    return _SPACE.sub(" ", text).strip()
